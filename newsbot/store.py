"""Persistent state: seen items, outbox, Telegram topic ids, article JSON files."""

from __future__ import annotations

import json
import logging
import shutil
from datetime import datetime, timedelta
from pathlib import Path

from .config import ROOT

log = logging.getLogger("news-bot")

STATE_DIR = ROOT / "state"
DATA_DIR = ROOT / "data"
SEEN_TTL = timedelta(days=30)


def read_json(path: Path, default):
    try:
        raw = path.read_text(encoding="utf-8").strip()
        return json.loads(raw) if raw else default
    except FileNotFoundError:
        return default
    except json.JSONDecodeError:
        log.error("%s is not valid JSON; treating it as empty", path)
        return default


def write_json(path: Path, data, indent: int | None = 1) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=indent, ensure_ascii=False) + "\n", encoding="utf-8")


class State:
    """state/seen.json + state/outbox.json + state/telegram.json"""

    def __init__(self, state_dir: Path = STATE_DIR):
        self.dir = state_dir
        seen = read_json(state_dir / "seen.json", {})
        self.sources: list[str] = list(seen.get("sources", []))
        self.seen: dict[str, str] = dict(seen.get("items", {}))
        self.outbox: list[dict] = read_json(state_dir / "outbox.json", [])
        self.telegram: dict = read_json(state_dir / "telegram.json", {})

    @property
    def first_run(self) -> bool:
        return not self.seen and not self.sources

    def is_seen(self, keys) -> bool:
        return any(k in self.seen for k in keys)

    def mark(self, keys, day: str) -> None:
        for k in keys:
            self.seen[k] = day

    def prune(self, now: datetime) -> int:
        cutoff = (now - SEEN_TTL).date().isoformat()
        old = [k for k, day in self.seen.items() if day < cutoff]
        for k in old:
            del self.seen[k]
        return len(old)

    def save(self) -> None:
        write_json(self.dir / "seen.json",
                   {"sources": sorted(self.sources), "items": dict(sorted(self.seen.items()))})
        write_json(self.dir / "outbox.json", self.outbox)
        write_json(self.dir / "telegram.json", self.telegram)


# --------------------------------------------------------------------------- #
# Articles: data/articles/YYYY/MM/DD/<id>.json
# --------------------------------------------------------------------------- #

def article_path(article: dict, data_dir: Path = DATA_DIR) -> Path:
    day = article["added"][:10].replace("-", "/")
    return data_dir / "articles" / day / f"{article['id']}.json"


def save_article(article: dict, data_dir: Path = DATA_DIR) -> Path:
    path = article_path(article, data_dir)
    write_json(path, article)
    return path


def load_articles(data_dir: Path = DATA_DIR) -> list[dict]:
    articles = []
    for path in sorted((data_dir / "articles").glob("*/*/*/*.json")):
        art = read_json(path, None)
        if art:
            articles.append(art)
    return articles


def prune_articles(now: datetime, keep_days: int, data_dir: Path = DATA_DIR) -> int:
    """Delete day folders older than keep_days (0 = keep forever)."""
    if keep_days <= 0:
        return 0
    cutoff = (now - timedelta(days=keep_days)).date().isoformat()
    removed = 0
    for day_dir in sorted((data_dir / "articles").glob("*/*/*")):
        day = "-".join(day_dir.parts[-3:])
        if day_dir.is_dir() and day < cutoff:
            removed += len(list(day_dir.glob("*.json")))
            shutil.rmtree(day_dir)
    for d in sorted((data_dir / "articles").glob("*/*"), reverse=True) + \
            sorted((data_dir / "articles").glob("*")):
        if d.is_dir() and not any(d.iterdir()):
            d.rmdir()
    return removed
