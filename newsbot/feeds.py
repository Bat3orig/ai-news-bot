"""Fetch feeds and select new items."""

from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import feedparser
import requests

from .config import Source, Subtopic, Topics
from .store import State
from .util import USER_AGENT, link_key, short_key, strip_html

log = logging.getLogger("news-bot")

FETCH_TIMEOUT = 15
MAX_AGE = timedelta(days=3)


@dataclass
class Item:
    source: Source
    subtopic: Subtopic | None
    title: str
    link: str
    summary: str             # plain text from the feed
    summary_html: str        # raw, used to find an <img>
    published: datetime | None
    keys: list[str]
    publisher: str = ""      # Google News: original outlet
    feed_image: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def id(self) -> str:
        return self.keys[0]

    @property
    def sort_time(self) -> datetime:
        return self.published or datetime.now(timezone.utc)


def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": USER_AGENT,
        "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, text/html, */*",
        "Accept-Language": "en-US,en;q=0.9",
    })
    return s


def fetch_entries(session: requests.Session, src: Source) -> list:
    resp = session.get(src.url, timeout=FETCH_TIMEOUT)
    resp.raise_for_status()
    feed = feedparser.parse(resp.content)
    if feed.bozo and not feed.entries:
        raise ValueError(f"parse error: {feed.get('bozo_exception')!r}")
    return feed.entries


def entry_time(entry) -> datetime | None:
    for attr in ("published_parsed", "updated_parsed", "created_parsed"):
        value = entry.get(attr)
        if value:
            try:
                return datetime(*value[:6], tzinfo=timezone.utc)
            except (TypeError, ValueError):
                continue
    return None


def entry_image(entry) -> str:
    for m in entry.get("media_content") or []:
        if m.get("url") and (m.get("medium") == "image" or "image" in (m.get("type") or "")
                             or re.search(r"\.(jpe?g|png|webp|gif)(\?|$)", m["url"], re.I)):
            return m["url"]
    for m in entry.get("media_thumbnail") or []:
        if m.get("url"):
            return m["url"]
    for link in entry.get("links") or []:
        if link.get("rel") == "enclosure" and (link.get("type") or "").startswith("image"):
            return link.get("href", "")
    html_text = entry.get("summary") or ""
    for c in entry.get("content") or []:
        html_text += c.get("value", "")
    m = re.search(r"<img[^>]+src=[\"']([^\"']+)", html_text, re.I)
    return m.group(1) if m else ""


def build_item(entry, src: Source, topics: Topics) -> Item | None:
    link = (entry.get("link") or "").strip()
    title = strip_html(entry.get("title") or "")
    if not link or not title:
        return None
    lk = link_key(link)
    # Unique id: entry.id, or sha256 of the (utm-stripped) link. The link key is
    # stored too, so the same URL from two sources is only sent once.
    id_key = short_key(entry["id"]) if entry.get("id") else lk
    summary_html = entry.get("summary") or entry.get("description") or ""
    if src.type == "github_release" and entry.get("content"):
        summary_html = entry["content"][0].get("value", summary_html)
    if src.type == "github_release":
        # "v2.1.290" -> "claude-code v2.1.290"
        repo = src.url.rstrip("/").split("/")[-2] if "/releases" in src.url else ""
        if repo and repo.lower() not in title.lower():
            title = f"{repo} {title}"
    publisher = ""
    if src.type == "google_news":
        publisher = (entry.get("source") or {}).get("title", "")
        if publisher and title.endswith(f" - {publisher}"):
            title = title[: -len(publisher) - 3].strip()
    return Item(
        source=src,
        subtopic=topics.subtopics.get(src.subtopic) if src.subtopic else None,
        title=title, link=link,
        summary=strip_html(summary_html), summary_html=summary_html,
        published=entry_time(entry),
        keys=list(dict.fromkeys([id_key, lk])),
        publisher=publisher,
        feed_image=entry_image(entry),
    )


def collect(sources: list[Source], topics: Topics, state: State, now: datetime,
            workers: int = 8) -> tuple[list[Item], dict]:
    """Fetch every source; return new candidate items (unsorted) and stats.

    Sources fetched for the first time are bootstrapped: their current items are
    marked as seen without being sent.
    """
    session = make_session()
    today = now.date().isoformat()
    cutoff = now - MAX_AGE

    def fetch(src):
        try:
            return src, fetch_entries(session, src), None
        except Exception as exc:  # noqa: BLE001 - one bad source must not stop the run
            return src, None, exc

    with ThreadPoolExecutor(workers) as pool:
        results = list(pool.map(fetch, sources))

    candidates: list[Item] = []
    run_keys: set[str] = set()
    stats = {"ok": [], "failed": [], "bootstrapped": 0}
    for src, entries, exc in results:
        if exc is not None:
            log.warning("[%s] fetch failed: %s", src.name, exc)
            stats["failed"].append(src.name)
            continue
        stats["ok"].append(src.name)
        bootstrap = state.first_run or src.name not in state.sources
        fresh = 0
        for entry in entries:
            item = build_item(entry, src, topics)
            if item is None:
                continue
            if state.is_seen(item.keys):
                if item.published is None:
                    # Undated items have no age filter: keep them alive while they
                    # are still in the feed so they aren't re-sent after pruning.
                    state.mark(item.keys, today)
                continue
            if item.published and item.published < cutoff:
                continue
            if not src.accepts_title(item.title):
                continue
            text = f"{item.title}\n{item.summary}"
            if src.keywords and not src.keywords.search(text):
                continue
            if item.subtopic is None:
                item.subtopic = topics.classify(text, src.section)
                if item.subtopic is None:
                    continue  # not about any of our topics
            if any(k in run_keys for k in item.keys):
                continue
            run_keys.update(item.keys)
            if bootstrap:
                state.mark(item.keys, today)
                stats["bootstrapped"] += 1
            else:
                candidates.append(item)
                fresh += 1
        log.info("[%s] %d entries, %d new%s", src.name, len(entries), fresh,
                 " (bootstrap)" if bootstrap else "")
        if src.name not in state.sources:
            state.sources.append(src.name)

    # Forget sources removed from sources.yaml so re-adding them bootstraps again.
    names = {s.name for s in sources}
    state.sources = [n for n in state.sources if n in names]
    log.info("Sources OK: %d, failed: %d %s", len(stats["ok"]), len(stats["failed"]),
             stats["failed"] or "")
    return candidates, stats
