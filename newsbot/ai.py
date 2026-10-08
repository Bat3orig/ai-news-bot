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

import requests

from .config import Topics
from .feeds import Item

log = logging.getLogger("news-bot")

DEFAULT_PROVIDERS = "gemini:gemini-3.8-flash,gemini:gemini-3.5-flash-lite,claude:claude-haiku-5-5"
CHUNK = 8            # items per AI request
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
                    "subtopic": {"type": "string"},
                    "title_mn": {"type": "string"},
                    "summary_mn": {"type": "string"},
                    "body_mn": {"type": "string"},
                },
                "required": ["id", "relevant", "subtopic", "title_mn", "summary_mn", "body_mn"],
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


def _payload(items: list[Item], topics: Topics) -> str:
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
    return json.dumps({"items": rows}, ensure_ascii=False)


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
        out[rid] = row
    return out


def translate(items: list[Item], topics: Topics) -> dict[str, dict]:
    """Return {item.id: {...mn fields..., "ai": "provider:model"}} for items that succeeded."""
    chain = provider_chain()
    if not chain:
        log.warning("No AI provider configured (GEMINI_API_KEY / ANTHROPIC_API_KEY); sending in English")
        return {}
    system = SYSTEM_TEMPLATE.format(taxonomy=_taxonomy(topics))
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
                text = fn(model, system, _payload(pending, topics))
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
            log.info("AI %s:%s translated %d/%d items", name, model, len(got), len(pending))
            pending = [it for it in pending if it.id not in got]
        if pending:
            log.warning("%d items left untranslated (English fallback)", len(pending))
    return results
