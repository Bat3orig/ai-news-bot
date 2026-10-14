"""Load topics.yaml and sources.yaml."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

from .util import keyword_pattern

log = logging.getLogger("news-bot")

ROOT = Path(__file__).resolve().parent.parent
TOPICS_FILE = ROOT / "topics.yaml"
SOURCES_FILE = ROOT / "sources.yaml"

PRERELEASE_RE = re.compile(r"(canary|alpha|beta|\brc|nightly|preview|experimental|insiders)", re.I)


@dataclass
class Subtopic:
    id: str
    name: str
    hashtag: str
    section: "Section"
    about: str = ""
    pattern: re.Pattern | None = None


@dataclass
class Section:
    id: str
    name: str
    emoji: str
    subtopics: list[Subtopic] = field(default_factory=list)


@dataclass
class Topics:
    site_title: str
    site_description: str
    sections: list[Section]
    subtopics: dict[str, Subtopic]
    keep_days: int = 180
    send_hours: tuple[int, int] = (0, 24 * 60)  # [start, end) in minutes, local time
    utc_offset: float = 0                       # hours; Mongolia = 8
    max_per_send: int = 10

    @property
    def send_hours_text(self) -> str:
        (a, b), sign = self.send_hours, "+" if self.utc_offset >= 0 else "-"
        return f"{a // 60:02d}:{a % 60:02d}-{b // 60:02d}:{b % 60:02d} UTC{sign}{abs(self.utc_offset):g}"

    def can_send(self, now: datetime) -> bool:
        """True if `now` (aware) is inside the Telegram sending hours."""
        local = now.astimezone(timezone(timedelta(hours=self.utc_offset)))
        minute = local.hour * 60 + local.minute
        start, end = self.send_hours
        return start <= minute < end if start <= end else minute >= start or minute < end

    def classify(self, text: str, section: str | None = None) -> Subtopic | None:
        """Best keyword match (longest matched keyword wins, e.g. React Native > React)."""
        best, best_len = None, 0
        for sub in self.subtopics.values():
            if section and sub.section.id != section:
                continue
            if sub.pattern:
                for m in sub.pattern.finditer(text):
                    if len(m.group(0)) > best_len:
                        best, best_len = sub, len(m.group(0))
        return best


@dataclass
class Source:
    name: str
    url: str
    type: str = "rss"
    subtopic: str | None = None
    section: str | None = None
    keywords: re.Pattern | None = None
    skip_prereleases: bool = False
    title_regex: re.Pattern | None = None

    def accepts_title(self, title: str) -> bool:
        if self.skip_prereleases and PRERELEASE_RE.search(title):
            return False
        if self.title_regex and not self.title_regex.search(title):
            return False
        return True


def parse_hours(text: str) -> tuple[int, int]:
    """'08:00-21:00' -> (480, 1260) minutes."""
    m = re.fullmatch(r"\s*(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})\s*", str(text))
    if not m:
        raise ValueError(f"telegram.send_hours must look like '08:00-21:00', got {text!r}")
    h1, m1, h2, m2 = map(int, m.groups())
    return h1 * 60 + m1, h2 * 60 + m2


def load_topics(path: Path = TOPICS_FILE) -> Topics:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    site = data.get("site") or {}
    tg = data.get("telegram") or {}
    sections, subs = [], {}
    for s in data.get("sections", []):
        sec = Section(id=s["id"], name=s["name"], emoji=s.get("emoji", ""))
        for t in s.get("subtopics", []):
            hashtag = re.sub(r"\W+", "", t.get("hashtag") or t["name"])
            sub = Subtopic(id=t["id"], name=t["name"], hashtag=hashtag, section=sec,
                           about=t.get("about", ""), pattern=keyword_pattern(t.get("keywords") or []))
            if sub.id in subs:
                raise ValueError(f"duplicate subtopic id: {sub.id}")
            sec.subtopics.append(sub)
            subs[sub.id] = sub
        sections.append(sec)
    return Topics(site.get("title", "Dev News"), site.get("description", ""), sections, subs,
                  int(site.get("keep_days", 180)),
                  parse_hours(tg.get("send_hours", "00:00-24:00")),
                  float(tg.get("utc_offset", 0)),
                  max(1, int(tg.get("max_per_send", 10))))


def load_sources(topics: Topics, path: Path = SOURCES_FILE) -> list[Source]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    section_ids = {s.id for s in topics.sections}
    sources, names = [], set()
    for s in data.get("sources", []):
        if not s.get("enabled", True):
            continue
        if not s.get("name") or not s.get("url"):
            log.warning("Skipping source without name/url: %r", s)
            continue
        if s["name"] in names:
            raise ValueError(f"duplicate source name: {s['name']}")
        names.add(s["name"])
        sub, sec = s.get("subtopic"), s.get("section")
        if sub and sub not in topics.subtopics:
            raise ValueError(f"[{s['name']}] unknown subtopic {sub!r} (see topics.yaml)")
        if sec and sec not in section_ids:
            raise ValueError(f"[{s['name']}] unknown section {sec!r} (see topics.yaml)")
        sources.append(Source(
            name=s["name"], url=s["url"], type=s.get("type", "rss"),
            subtopic=sub, section=sec,
            keywords=keyword_pattern(s.get("keywords") or []),
            skip_prereleases=bool(s.get("skip_prereleases")),
            title_regex=re.compile(s["title_regex"], re.I) if s.get("title_regex") else None,
        ))
    return sources
