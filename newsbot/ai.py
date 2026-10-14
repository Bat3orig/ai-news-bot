"""Mongolian translation/summary with a provider fallback chain.

Default chain (override with the AI_PROVIDERS env var, comma separated):
    gemini:gemini-3.8-flash, gemini:gemini-3.5-flash-lite, claude:claude-haiku-5-5

Every run starts again from the first provider, so when Gemini's free quota
comes back the bot automatically returns to it. Providers without an API key
are skipped. If every provider fails, items are sent in English.
"""

from __future__ import annotations

import json
import logging
import os
from collections import Counter
from datetime import datetime, timezone

import requests

from .config import Topics
from .feeds import Item
from .util import title_tokens

log = logging.getLogger("news-bot")

DEFAULT_PROVIDERS = "gemini:gemini-3.8-flash,gemini:gemini-3.5-flash-lite,claude:claude-haiku-5-5"
CHUNK = 8            # items per AI request
RELATED_TITLES = 60  # past headlines sharing a distinctive word with the chunk
LATEST_TITLES = 15   # plus the newest headlines, always sent
AI_TIMEOUT = 180     # seconds

SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "relevant": {"type": "boolean"},
                    "duplicate": {"type": "boolean"},
                    "score": {"type": "integer"},
                    "subtopic": {"type": "string"},
                    "title_mn": {"type": "string"},
                    "summary_mn": {"type": "string"},
                    "body_mn": {"type": "string"},
                },
                "required": ["id", "relevant", "duplicate", "score", "subtopic", "title_mn",
                             "summary_mn", "body_mn"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["items"],
    "additionalProperties": False,
}

SYSTEM_TEMPLATE = """You are the editor of a Mongolian-language news site for software developers.
You receive news items as JSON. For EVERY item return one object with the same "id":

- relevant: true if the item really is about one of its "subtopic_options". false if it only
  matched by coincidence (e.g. "Electron" the particle, an unrelated company, spam, stock-price noise
  with no product news). Items with a single option come from a dedicated source: keep them true
  unless clearly unrelated.
- duplicate: true if the item is about the same event, announcement or story as a headline in
  "already_published" ("date: headline", up to a week old) or as an EARLIER item in this batch.
  It IS a duplicate when another outlet reports it, when it is published days later, when the
  headline takes a different angle or wording, or when it is a follow-up/reaction/analysis that
  adds no major new fact. It is NOT a duplicate if it is a different announcement (even by the
  same company on the same day) or a real new development (e.g. the actual release after a rumor).
- score: how useful the item is for software developers who build with these tools (1-5):
  5 = new model, major version, new API/SDK/CLI/tool or feature, pricing, rate-limit or
    deprecation change, open-weight release.
  4 = notable product feature developers use, technical deep-dive, engineering post, credible
    benchmark, important release notes.
  3 = other news that directly changes how developers build or use these tools (API terms or
    usage-policy changes, major outages, security issues in dev tools).
  2 = business and general news: partnerships, customers, resellers, hiring, funding, valuation,
    revenue, IPO, lawsuits, politics, government and military deals, executives' opinions,
    AI-safety incidents and lab drama (e.g. a model sending a false tip to police), consumer
    gadgets and hardware, general-audience explainers.
  1 = spam, SEO comparison pages, crypto or stock price predictions, listicles, unrelated items.
  Use 1 when relevant is false. Release notes from a dedicated repository are at least 3.
- subtopic: exactly one id from that item's "subtopic_options".
- title_mn: a natural Mongolian headline (Cyrillic), at most 110 characters.
- summary_mn: 2-3 sentences, at most 320 characters: the key news for a Telegram post.
- body_mn: 3-5 short paragraphs (150-300 words) explaining what happened, the important details and
  numbers, and why it matters for developers. Separate paragraphs with a blank line. Plain text,
  no markdown, no headings.

Rules:
- Write fluent, natural Mongolian in Cyrillic script, as a Mongolian tech journalist would.
- Keep names of products, companies, libraries, models, versions and code identifiers in their
  original Latin spelling (React, Next.js, GPT-5, shadcn/ui, useEffect).
- Use only facts from the provided text. Do not invent numbers, dates, quotes or features.
- If the text is thin (only a headline), keep body_mn to 1-2 paragraphs stating what is known.
- For release notes, summarize the most important changes for developers.
- Respond with JSON only: {{"items": [...]}}.

Subtopics:
{taxonomy}"""


class ProviderError(Exception):
    pass


class QuotaError(ProviderError):
    """Rate limit / quota exhausted: skip this provider for the rest of the run."""


def _taxonomy(topics: Topics) -> str:
    return "\n".join(f"- {s.id}: {s.name} ({s.section.name}) — {s.about}"
                     for s in topics.subtopics.values())


def _related(items: list[Item], past: list[tuple[str, str]]) -> list[str]:
    """Past headlines ("date: title") that may be the same story as one of `items`.

    A week of headlines is too long to send whole, so pick the ones sharing a distinctive word
    (one that is rare in the week, unlike "Anthropic"/"Claude"/"AI") with an item's title or
    text, plus the newest few.
    """
    if not past:
        return []
    toks = [title_tokens(t) for _, t in past]
    df = Counter(w for ts in toks for w in ts)
    rare = max(3, len(past) // 25)
    want = set()
    for it in items:
        want |= title_tokens(f"{it.title} {(it.extra.get('text') or it.summary)[:400]}")
    want = {w for w in want if df.get(w, 0) <= rare}
    scored = [(len(ts & want), i) for i, ts in enumerate(toks)]
    picked = {i for n, i in sorted(scored, reverse=True)[:RELATED_TITLES] if n}
    picked |= set(range(max(0, len(past) - LATEST_TITLES), len(past)))
    return [f"{past[i][0]}: {past[i][1]}" for i in sorted(picked)]


def _payload(items: list[Item], topics: Topics, already: list[str]) -> str:
    rows = []
    for it in items:
        if it.source.subtopic:
            options = [it.source.subtopic]
        elif it.source.section:
            options = [s.id for s in topics.subtopics.values() if s.section.id == it.source.section]
        else:
            options = list(topics.subtopics)
        # Put the keyword guess first as a hint.
        if it.subtopic and it.subtopic.id in options:
            options.remove(it.subtopic.id)
            options.insert(0, it.subtopic.id)
        rows.append({
            "id": it.id,
            "source": it.publisher or it.source.name,
            "title": it.title,
            "text": it.extra.get("text") or it.summary,
            "subtopic_options": options,
        })
    return json.dumps({"already_published": already, "items": rows},
                      ensure_ascii=False)


# --------------------------------------------------------------------------- #
# Providers
# --------------------------------------------------------------------------- #

def _gemini(model: str, system: str, user: str) -> str:
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    resp = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        headers={"x-goog-api-key": key, "Content-Type": "application/json"},
        json={
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {"responseMimeType": "application/json", "maxOutputTokens": 32768},
        },
        timeout=AI_TIMEOUT,
    )
    if resp.status_code == 429:
        raise QuotaError(f"HTTP 429: {resp.text[:300]}")
    if not resp.ok:
        raise ProviderError(f"HTTP {resp.status_code}: {resp.text[:300]}")
    data = resp.json()
    cands = data.get("candidates") or []
    if not cands:
        raise ProviderError(f"no candidates: {str(data.get('promptFeedback'))[:200]}")
    parts = (cands[0].get("content") or {}).get("parts") or []
    text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
    if cands[0].get("finishReason") not in (None, "STOP"):
        raise ProviderError(f"finishReason={cands[0].get('finishReason')}")
    return text


_claude_client = None


def _claude(model: str, system: str, user: str) -> str:
    import anthropic

    global _claude_client
    if _claude_client is None:
        _claude_client = anthropic.Anthropic(timeout=AI_TIMEOUT, max_retries=2)
    try:
        resp = _claude_client.messages.create(
            model=model,
            max_tokens=16000,
            system=system,
            messages=[{"role": "user", "content": user}],
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
        )
    except anthropic.RateLimitError as exc:
        raise QuotaError(str(exc)) from exc
    except anthropic.APIStatusError as exc:
        if exc.status_code == 402 or "credit balance" in str(exc).lower():
            raise QuotaError(str(exc)) from exc
        raise ProviderError(f"HTTP {exc.status_code}: {exc.message}") from exc
    except anthropic.APIConnectionError as exc:
        raise ProviderError(f"connection error: {exc}") from exc
    if resp.stop_reason != "end_turn":
        raise ProviderError(f"stop_reason={resp.stop_reason}")
    return next((b.text for b in resp.content if b.type == "text"), "")


PROVIDERS = {
    "gemini": (_gemini, "GEMINI_API_KEY"),
    "claude": (_claude, "ANTHROPIC_API_KEY"),
}


def provider_chain() -> list[tuple[str, str]]:
    chain = []
    spec = os.environ.get("AI_PROVIDERS", "").strip() or DEFAULT_PROVIDERS
    for part in spec.split(","):
        if ":" not in part:
            continue
        name, model = (p.strip() for p in part.split(":", 1))
        if name not in PROVIDERS:
            log.warning("Unknown AI provider %r", name)
            continue
        if not os.environ.get(PROVIDERS[name][1], "").strip():
            continue
        chain.append((name, model))
    return chain


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #

def _parse(text: str, expected: set[str], topics: Topics) -> dict[str, dict]:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`").removeprefix("json").strip()
    data = json.loads(text)
    out = {}
    for row in data.get("items", []):
        rid = str(row.get("id", ""))
        if rid not in expected:
            continue
        if not all(isinstance(row.get(k), str) and row[k].strip()
                   for k in ("title_mn", "summary_mn", "body_mn")):
            continue
        if row.get("subtopic") not in topics.subtopics:
            row["subtopic"] = ""
        row["relevant"] = row.get("relevant") is not False
        row["duplicate"] = row.get("duplicate") is True
        try:
            row["score"] = min(5, max(1, int(row.get("score"))))
        except (TypeError, ValueError):
            row["score"] = 3  # unknown: neither keep nor drop on its own
        out[rid] = row
    return out


def translate(items: list[Item], topics: Topics,
              recent: list[tuple[str, str]]) -> dict[str, dict]:
    """Return {item.id: {...mn fields..., "ai": "provider:model"}} for items that succeeded.

    `recent` = (date, title) of articles published in the last days, oldest first.
    """
    chain = provider_chain()
    if not chain:
        log.warning("No AI provider configured (GEMINI_API_KEY / ANTHROPIC_API_KEY); sending in English")
        return {}
    system = SYSTEM_TEMPLATE.format(taxonomy=_taxonomy(topics))
    kept: list[str] = []  # titles kept by earlier chunks of this run
    titles = {it.id: it.title for it in items}
    today = datetime.now(timezone.utc).date().isoformat()
    exhausted: set[tuple[str, str]] = set()
    results: dict[str, dict] = {}
    for start in range(0, len(items), CHUNK):
        pending = items[start:start + CHUNK]
        for name, model in chain:
            if not pending:
                break
            if (name, model) in exhausted:
                continue
            fn = PROVIDERS[name][0]
            try:
                already = _related(pending, recent) + [f"{today}: {t}" for t in kept]
                text = fn(model, system, _payload(pending, topics, already))
                got = _parse(text, {it.id for it in pending}, topics)
            except QuotaError as exc:
                log.warning("AI %s:%s quota/rate limit, falling back: %s", name, model, exc)
                exhausted.add((name, model))
                continue
            except (ProviderError, ValueError, requests.RequestException) as exc:
                log.warning("AI %s:%s failed, falling back: %s", name, model, exc)
                continue
            for rid, row in got.items():
                row["ai"] = f"{name}:{model}"
                results[rid] = row
                # Later chunks must see what this one kept, to catch cross-chunk duplicates.
                if row["relevant"] and not row["duplicate"]:
                    kept.append(titles[rid])
            log.info("AI %s:%s translated %d/%d items", name, model, len(got), len(pending))
            pending = [it for it in pending if it.id not in got]
        if pending:
            log.warning("%d items left untranslated (English fallback)", len(pending))
    return results
