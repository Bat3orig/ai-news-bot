#!/usr/bin/env python3
"""Telegram AI news bot.

Fetches the feeds listed in sources.yaml, finds items that were not sent
before (state/seen.json) and pushes them to a Telegram chat.

Usage:
    python main.py              # fetch and send to Telegram
    python main.py --dry-run    # print to console, do not touch seen.json
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import logging
import os
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import feedparser
import requests
import yaml

ROOT = Path(__file__).resolve().parent
SOURCES_FILE = ROOT / "sources.yaml"
STATE_FILE = ROOT / "state" / "seen.json"

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)
FETCH_TIMEOUT = 15          # seconds per source
MAX_AGE = timedelta(days=3)  # only send items newer than this
STATE_TTL = timedelta(days=30)  # prune seen entries older than this
MAX_MESSAGES = 20           # per run
SEND_DELAY = 3              # seconds between Telegram messages
SUMMARY_LIMIT = 300         # characters
TELEGRAM_RETRIES = 3

log = logging.getLogger("news-bot")


class TelegramFatalError(Exception):
    """Unrecoverable Telegram error (bad token, wrong chat id, ...)."""


@dataclass
class Item:
    source: dict
    title: str
    link: str
    summary: str
    published: datetime | None
    keys: list[str] = field(default_factory=list)

    @property
    def sort_time(self) -> datetime:
        # Undated items are treated as "just appeared".
        return self.published or datetime.now(timezone.utc)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def short_key(text: str) -> str:
    # 16 hex chars (64 bits) is plenty to avoid collisions and keeps seen.json small.
    return sha256(text)[:16]


def normalize_url(url: str) -> str:
    """Strip utm_* params and the fragment, lowercase scheme/host."""
    parts = urlsplit(url.strip())
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
             if not k.lower().startswith("utm_")]
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path,
                       urlencode(query), ""))


def strip_html(text: str) -> str:
    text = re.sub(r"<(script|style)\b.*?</\1>", " ", text or "", flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    # WordPress feeds append "The post X appeared first on Y."
    return re.sub(r"\s*The post .{0,300}? appeared first on .{0,100}$", "", text)


def truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    cut = text[: limit - 1]
    if " " in cut[limit // 2:]:
        cut = cut[: cut.rfind(" ")]
    return cut.rstrip(" ,.;:-") + "…"


def entry_time(entry) -> datetime | None:
    for attr in ("published_parsed", "updated_parsed", "created_parsed"):
        value = entry.get(attr)
        if value:
            try:
                return datetime(*value[:6], tzinfo=timezone.utc)
            except (TypeError, ValueError):
                continue
    return None


def keyword_patterns(keywords: list[str]) -> list[re.Pattern]:
    # Whole-word match (optional plural "s") so "AI" does not match "said".
    return [re.compile(rf"(?<![\w]){re.escape(k)}s?(?![\w])", re.I) for k in keywords]


def hashtag(category: str) -> str:
    tag = re.sub(r"\W+", "", category or "")
    return f"#{tag}" if tag else ""


# --------------------------------------------------------------------------- #
# Config & state
# --------------------------------------------------------------------------- #

def load_sources(path: Path) -> list[dict]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    sources = []
    for src in data.get("sources", []):
        if not src.get("enabled", True):
            continue
        if not src.get("name") or not src.get("url"):
            log.warning("Skipping source without name/url: %r", src)
            continue
        src.setdefault("type", "rss")
        src.setdefault("category", "")
        # Google News summaries just repeat the title, so they are off by default.
        src.setdefault("summary", src["type"] != "google_news")
        src["_patterns"] = keyword_patterns(src.get("keywords") or [])
        sources.append(src)
    return sources


def load_state(path: Path) -> dict:
    try:
        raw = path.read_text(encoding="utf-8").strip()
        data = json.loads(raw) if raw else {}
    except FileNotFoundError:
        data = {}
    except json.JSONDecodeError:
        log.error("%s is not valid JSON; treating it as empty", path)
        data = {}
    return {"sources": list(data.get("sources", [])), "items": dict(data.get("items", {}))}


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"sources": sorted(state["sources"]), "items": dict(sorted(state["items"].items()))}
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def prune_state(state: dict, now: datetime) -> int:
    cutoff = (now - STATE_TTL).date().isoformat()
    old = [k for k, day in state["items"].items() if day < cutoff]
    for k in old:
        del state["items"][k]
    return len(old)


# --------------------------------------------------------------------------- #
# Fetching
# --------------------------------------------------------------------------- #

def fetch_entries(session: requests.Session, src: dict) -> list:
    resp = session.get(src["url"], timeout=FETCH_TIMEOUT)
    resp.raise_for_status()
    feed = feedparser.parse(resp.content)
    if feed.bozo and not feed.entries:
        raise ValueError(f"parse error: {feed.get('bozo_exception')!r}")
    return feed.entries


def build_item(entry, src: dict) -> Item | None:
    link = (entry.get("link") or "").strip()
    title = strip_html(entry.get("title") or "")
    if not link or not title:
        return None
    clean_link = normalize_url(link)
    link_key = short_key(clean_link)
    # Unique id: entry.id, or sha256 of the (utm-stripped) link.
    # The link key is always stored too, so the same URL coming from two
    # different sources is only sent once.
    id_key = short_key(entry["id"]) if entry.get("id") else link_key
    summary = strip_html(entry.get("summary") or entry.get("description") or "")
    return Item(
        source=src,
        title=title,
        link=link,
        summary=summary,
        published=entry_time(entry),
        keys=list(dict.fromkeys([id_key, link_key])),
    )


def matches_keywords(item: Item) -> bool:
    patterns = item.source["_patterns"]
    if not patterns:
        return True
    text = f"{item.title}\n{item.summary}"
    return any(p.search(text) for p in patterns)


# --------------------------------------------------------------------------- #
# Telegram
# --------------------------------------------------------------------------- #

def format_message(item: Item) -> str:
    src = item.source
    lines = [
        f"<b>{html.escape(src['name'], quote=False)}</b>",
        f'<a href="{html.escape(item.link, quote=True)}">{html.escape(item.title, quote=False)}</a>',
    ]
    if src.get("summary") and item.summary and item.summary != item.title:
        lines += ["", html.escape(truncate(item.summary, SUMMARY_LIMIT), quote=False)]
    tag = hashtag(src.get("category", ""))
    if tag:
        lines += ["", tag]
    return "\n".join(lines)


class Telegram:
    def __init__(self, token: str, chat_id: str, dry_run: bool):
        self.dry_run = dry_run
        self.chat_id = chat_id
        self.url = f"https://api.telegram.org/bot{token}/sendMessage"
        self.session = requests.Session()

    def send(self, text: str) -> bool:
        """Return True on success, False if this message should be skipped."""
        if self.dry_run:
            print("-" * 60)
            print(text)
            return True
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": False,
        }
        for attempt in range(1, TELEGRAM_RETRIES + 1):
            try:
                resp = self.session.post(self.url, json=payload, timeout=FETCH_TIMEOUT)
            except requests.RequestException as exc:
                log.warning("Telegram request failed (attempt %d): %s", attempt, exc)
                time.sleep(SEND_DELAY * attempt)
                continue
            if resp.ok:
                return True
            try:
                body = resp.json()
            except ValueError:
                body = {}
            desc = body.get("description", resp.text[:200])
            if resp.status_code == 429:
                wait = int(body.get("parameters", {}).get("retry_after", 5)) + 1
                log.warning("Telegram 429, waiting %ss", wait)
                time.sleep(wait)
                continue
            if resp.status_code in (401, 403, 404):
                raise TelegramFatalError(f"HTTP {resp.status_code}: {desc}")
            if resp.status_code == 400 and "chat not found" in desc.lower():
                raise TelegramFatalError(f"HTTP 400: {desc}")
            # Other 4xx (e.g. bad HTML): skip this message so it does not block the queue.
            if 400 <= resp.status_code < 500:
                log.error("Telegram rejected message (HTTP %s): %s", resp.status_code, desc)
                return False
            log.warning("Telegram HTTP %s (attempt %d): %s", resp.status_code, attempt, desc)
            time.sleep(SEND_DELAY * attempt)
        raise TelegramFatalError("Telegram unavailable after retries")


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #

def run(dry_run: bool, sources_path: Path, state_path: Path) -> int:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not dry_run and (not token or not chat_id):
        log.error("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set (or use --dry-run)")
        return 2

    sources = load_sources(sources_path)
    state = load_state(state_path)
    seen = state["items"]
    first_run = not seen and not state["sources"]
    now = datetime.now(timezone.utc)
    today = now.date().isoformat()
    cutoff = now - MAX_AGE

    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT,
                            "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*"})

    candidates: list[Item] = []
    run_keys: set[str] = set()
    ok, failed, bootstrapped = [], [], 0
    for src in sources:
        try:
            entries = fetch_entries(session, src)
        except Exception as exc:  # noqa: BLE001 - one bad source must not stop the run
            log.warning("[%s] fetch failed: %s", src["name"], exc)
            failed.append(src["name"])
            continue
        ok.append(src["name"])
        # A source we have never fetched successfully (first run, or newly added
        # to sources.yaml): mark its current items as seen without sending.
        bootstrap = first_run or src["name"] not in state["sources"]
        fresh = 0
        for entry in entries:
            item = build_item(entry, src)
            if item is None:
                continue
            if any(k in seen for k in item.keys):
                if item.published is None:
                    # Undated items have no age filter, so keep them alive while
                    # they are still in the feed to avoid re-sending after pruning.
                    for k in item.keys:
                        seen[k] = today
                continue
            if item.published and item.published < cutoff:
                continue  # too old; never sent, no need to remember it
            if not matches_keywords(item):
                continue
            if any(k in run_keys for k in item.keys):
                continue  # same link from another source in this run
            run_keys.update(item.keys)
            if bootstrap:
                for k in item.keys:
                    seen[k] = today
                bootstrapped += 1
            else:
                candidates.append(item)
                fresh += 1
        log.info("[%s] %d entries, %d new%s", src["name"], len(entries), fresh,
                 " (bootstrap)" if bootstrap else "")
        if src["name"] not in state["sources"]:
            state["sources"].append(src["name"])

    # Forget sources removed from sources.yaml so re-adding them bootstraps again.
    names = {s["name"] for s in sources}
    state["sources"] = [n for n in state["sources"] if n in names]

    log.info("Sources OK: %d, failed: %d %s", len(ok), len(failed), failed or "")

    tg = Telegram(token, chat_id, dry_run)
    exit_code = 0
    try:
        if first_run:
            if not ok:
                log.error("First run but every source failed; not initializing state")
                return 1
            log.info("First run: marked %d items as seen, sending nothing", bootstrapped)
            tg.send(f"Bot started, tracking {len(sources)} sources")
        else:
            candidates.sort(key=lambda it: it.sort_time)
            batch = candidates[:MAX_MESSAGES]
            log.info("%d new items, sending %d (max %d per run)",
                     len(candidates), len(batch), MAX_MESSAGES)
            for i, item in enumerate(batch):
                if i and not dry_run:
                    time.sleep(SEND_DELAY)
                tg.send(format_message(item))
                # Messages Telegram rejected (send() == False) are marked seen too,
                # so a single bad item can't block the queue forever.
                for k in item.keys:
                    seen[k] = today
            if len(candidates) > len(batch):
                log.info("%d items left for the next run", len(candidates) - len(batch))
    except TelegramFatalError as exc:
        log.error("Telegram error, stopping: %s", exc)
        if first_run:
            return 1  # don't save; retry initialization next run
        exit_code = 1

    pruned = prune_state(state, now)
    if pruned:
        log.info("Pruned %d entries older than %d days", pruned, STATE_TTL.days)

    if dry_run:
        log.info("Dry run: %s not modified", state_path)
    else:
        save_state(state_path, state)
    return exit_code


def main() -> int:
    parser = argparse.ArgumentParser(description="Telegram AI news bot")
    parser.add_argument("--dry-run", action="store_true",
                        help="print messages instead of sending; do not modify seen.json")
    parser.add_argument("--sources", type=Path, default=SOURCES_FILE, help="path to sources.yaml")
    parser.add_argument("--state", type=Path, default=STATE_FILE, help="path to seen.json")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        stream=sys.stderr)
    return run(args.dry_run, args.sources, args.state)


if __name__ == "__main__":
    sys.exit(main())
