#!/usr/bin/env python3
"""Telegram dev-news bot (AI / Software / UI/UX) with a Mongolian static site.

Usage:
    python main.py prepare     # fetch feeds, enrich, translate, save articles, fill outbox
    python main.py send        # send the outbox to Telegram
    python main.py             # prepare + send
    python main.py --dry-run   # print what would happen; writes nothing, sends nothing

GitHub Actions runs `prepare`, builds/deploys the site, then `send`, so the
"Дэлгэрэнгүй" links already work when the messages arrive.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from newsbot import ai, enrich, feeds, store
from newsbot.config import load_sources, load_topics
from newsbot.telegram import SEND_DELAY, Telegram, TelegramFatalError, TelegramRejected
from newsbot.util import iso, link_key, truncate

log = logging.getLogger("news-bot")

MAX_PER_RUN = 20  # messages per run; the rest go out next run


def site_url() -> str:
    url = os.environ.get("SITE_URL", "").strip()
    if not url and os.environ.get("GITHUB_REPOSITORY"):
        owner, repo = os.environ["GITHUB_REPOSITORY"].split("/", 1)
        url = f"https://{owner.lower()}.github.io/{repo}/"
    return url.rstrip("/") + "/" if url else ""


def to_article(item: feeds.Item, tr: dict | None, topics, now: datetime) -> dict:
    sub_id = item.subtopic.id if item.subtopic else ""
    ai_sub = topics.subtopics.get((tr or {}).get("subtopic", ""))
    # Dedicated sources keep their subtopic; mixed sources take the AI's choice
    # (if it is inside the source's allowed section).
    if ai_sub and not item.source.subtopic and \
            (not item.source.section or ai_sub.section.id == item.source.section):
        sub_id = ai_sub.id
    return {
        "id": item.id,
        "subtopic": sub_id,
        "source": item.source.name,
        "source_label": item.publisher or item.source.name,
        "url": item.extra.get("url") or item.link,
        "image": item.extra.get("image", ""),
        "title": item.title,
        # Google News "summaries" just repeat the headline; use the page description.
        "summary_en": truncate(item.extra.get("description", "") if item.source.type == "google_news"
                               else item.summary or item.extra.get("description", ""), 600),
        "title_mn": (tr or {}).get("title_mn", ""),
        "summary_mn": (tr or {}).get("summary_mn", ""),
        "body_mn": (tr or {}).get("body_mn", ""),
        "published": iso(item.published) if item.published else iso(now),
        "added": iso(now),
        "ai": (tr or {}).get("ai", ""),
    }


def prepare(state: store.State, data_dir: Path, dry_run: bool) -> bool:
    """Returns True if new articles were added (site needs a rebuild)."""
    topics = load_topics()
    sources = load_sources(topics)
    now = datetime.now(timezone.utc)
    today = now.date().isoformat()
    first_run = state.first_run

    candidates, stats = feeds.collect(sources, topics, state, now)

    if first_run:
        if not stats["ok"]:
            log.error("First run but every source failed; not initializing state")
            raise SystemExit(1)
        log.info("First run: marked %d items as seen, sending nothing", stats["bootstrapped"])
        state.outbox.append({"kind": "notice", "text": f"Bot started, tracking {len(sources)} sources"})
        return False

    room = max(0, MAX_PER_RUN - len(state.outbox))
    candidates.sort(key=lambda it: it.sort_time)
    batch = candidates[:room]
    log.info("%d new items, processing %d (outbox has %d, max %d per run)",
             len(candidates), len(batch), len(state.outbox), MAX_PER_RUN)
    if len(candidates) > len(batch):
        log.info("%d items left for the next run", len(candidates) - len(batch))
    if not batch:
        return False

    enrich.enrich(batch)
    # Google News links resolve to the publisher URL: drop duplicates of items
    # we already have from an official feed (e.g. anthropic.com/news).
    unique, seen_urls = [], set()
    for it in batch:
        rk = link_key(it.extra.get("url") or it.link)
        if rk not in it.keys:
            if state.is_seen([rk]) or rk in seen_urls:
                log.info("Duplicate after URL resolve, skipping: %s", it.title[:70])
                state.mark(it.keys + [rk], today)
                continue
            it.keys.append(rk)
        seen_urls.add(rk)
        unique.append(it)

    translations = ai.translate(unique, topics)

    added = 0
    for it in unique:
        tr = translations.get(it.id)
        state.mark(it.keys, today)
        if tr and not tr.get("relevant", True) and not it.source.subtopic:
            log.info("AI: not relevant, skipping: %s", it.title[:70])
            continue
        art = to_article(it, tr, topics, now)
        if not art["subtopic"]:
            continue
        if dry_run:
            print("=" * 60)
            print(f"[{art['subtopic']}] {art['title_mn'] or art['title']}  ({art['ai'] or 'English'})")
            print(f"  url:   {art['url']}\n  image: {art['image'] or '-'}")
            print(f"  {art['summary_mn'] or art['summary_en'][:200]}")
        else:
            store.save_article(art, data_dir)
        state.outbox.append({"kind": "article", "article": art})
        added += 1
    return added > 0


def send(state: store.State, dry_run: bool) -> int:
    if not state.outbox:
        log.info("Outbox empty, nothing to send")
        return 0
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not dry_run and (not token or not chat_id):
        log.error("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set (or use --dry-run)")
        return 2
    topics = load_topics()
    base = site_url()
    tg = Telegram(token, chat_id, state.telegram, dry_run)
    try:
        tg.setup_topics(topics)
    except TelegramRejected as exc:
        log.warning("Telegram getChat failed: %s", exc)

    sent = 0
    exit_code = 0
    remaining = list(state.outbox)
    try:
        while remaining:
            entry = remaining[0]
            if sent and not dry_run:
                time.sleep(SEND_DELAY)
            try:
                if entry["kind"] == "notice":
                    tg.send_text(entry["text"])
                else:
                    art = dict(entry["article"])
                    if base:
                        art["site_url"] = f"{base}a/{art['id']}.html"
                    tg.send_article(art, topics)
                sent += 1
            except TelegramRejected as exc:
                # Don't let one bad message block the queue forever.
                log.error("Telegram rejected message, dropping it: %s", exc.description)
            remaining.pop(0)
    except TelegramFatalError as exc:
        log.error("Telegram error, stopping (%d left in outbox): %s", len(remaining), exc)
        exit_code = 1
    if not dry_run:
        state.outbox = remaining
    log.info("Sent %d messages", sent)
    return exit_code


def main() -> int:
    parser = argparse.ArgumentParser(description="Telegram dev-news bot")
    parser.add_argument("phase", nargs="?", choices=["prepare", "send", "all"], default="all")
    parser.add_argument("--dry-run", action="store_true",
                        help="print instead of sending; do not modify state/ or data/")
    parser.add_argument("--state-dir", type=Path, default=store.STATE_DIR)
    parser.add_argument("--data-dir", type=Path, default=store.DATA_DIR)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        stream=sys.stderr)
    logging.getLogger("httpx").setLevel(logging.WARNING)

    state = store.State(args.state_dir)
    now = datetime.now(timezone.utc)
    exit_code = 0
    changed = False
    if args.phase in ("prepare", "all"):
        changed = prepare(state, args.data_dir, args.dry_run)
        pruned = state.prune(now)
        if not args.dry_run:
            pruned_articles = store.prune_articles(now, load_topics().keep_days, args.data_dir)
            if pruned or pruned_articles:
                log.info("Pruned %d seen entries, %d articles", pruned, pruned_articles)
            changed = changed or pruned_articles > 0
    if args.phase in ("send", "all"):
        exit_code = send(state, args.dry_run)

    if args.dry_run:
        log.info("Dry run: state/ and data/ not modified")
    else:
        state.save()
    if os.environ.get("GITHUB_OUTPUT") and args.phase != "send":
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as fh:
            fh.write(f"changed={'true' if changed else 'false'}\n")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
