"""Small shared helpers."""

from __future__ import annotations

import hashlib
import html
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)
UB_TZ = timezone(timedelta(hours=8))  # Asia/Ulaanbaatar (no DST)


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def short_key(text: str) -> str:
    # 16 hex chars (64 bits) avoids collisions and keeps files small.
    return sha256(text)[:16]


def normalize_url(url: str) -> str:
    """Strip utm_* params and the fragment, lowercase scheme/host."""
    parts = urlsplit(url.strip())
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
             if not k.lower().startswith("utm_")]
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path,
                       urlencode(query), ""))


def link_key(url: str) -> str:
    return short_key(normalize_url(url))


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


def keyword_pattern(keywords: list[str]) -> re.Pattern | None:
    """Whole-word, case-insensitive, optional plural 's' ("AI" won't match "said")."""
    if not keywords:
        return None
    alts = "|".join(re.escape(k) for k in sorted(keywords, key=len, reverse=True))
    return re.compile(rf"(?<![\w/.-])(?:{alts})s?(?![\w])", re.I)


# Title similarity (same story from several outlets). Deliberately strict: in this feed almost
# every headline shares "Anthropic", "Claude", "AI Gateway"..., so looser matching drops
# different stories. Reworded duplicates are left to the AI ("duplicate" field).
_STOP = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with", "by", "at", "from",
    "is", "are", "as", "its", "it", "new", "how", "why", "what", "after", "over", "into", "now",
    "that", "this", "be", "has", "have", "will", "can", "up", "out", "says", "said",
}


def title_tokens(title: str) -> frozenset[str]:
    words = re.findall(r"[\w+.-]+", title.lower())
    return frozenset(w.strip(".-") for w in words if len(w) > 2 and w not in _STOP)


def similar_titles(a: frozenset[str], b: frozenset[str]) -> bool:
    inter = len(a & b)
    # Overlap coefficient: robust when one headline is much longer than the other.
    return inter >= 4 and inter / min(len(a), len(b)) >= 0.8


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
