"""Telegram Bot API client with forum-topic (Group Topics) support."""

from __future__ import annotations

import html
import logging
import re
import time

import requests

from .config import Topics
from .util import truncate

log = logging.getLogger("news-bot")

SEND_DELAY = 3       # seconds between messages (group rate limit)
RETRIES = 3
CAPTION_LIMIT = 1024
MESSAGE_LIMIT = 4096
TIMEOUT = 20


class TelegramFatalError(Exception):
    """Unrecoverable error (bad token, wrong chat id, bot removed)."""


class TelegramRejected(Exception):
    """This one message was rejected (e.g. bad image URL); try another form or skip."""

    def __init__(self, description: str):
        super().__init__(description)
        self.description = description


# --------------------------------------------------------------------------- #
# Formatting
# --------------------------------------------------------------------------- #

def _e(text: str) -> str:
    return html.escape(text or "", quote=False)


def format_article(art: dict, topics: Topics, limit: int) -> str:
    """HTML message. `limit` is the visible-character budget (caption 1024 / text 4096)."""
    sub = topics.subtopics.get(art.get("subtopic", ""))
    header = ""
    if sub:
        header = f"{sub.section.emoji} <b>{_e(sub.section.name)}</b> · #{sub.hashtag}\n"
    title = art.get("title_mn") or art["title"]
    summary = art.get("summary_mn") or art.get("summary_en") or ""
    links = []
    if art.get("site_url"):
        links.append(f'<a href="{html.escape(art["site_url"], quote=True)}">Дэлгэрэнгүй</a>')
    links.append(f'<a href="{html.escape(art["url"], quote=True)}">Эх сурвалж</a>')
    footer = " · ".join(links) + f" — {_e(art.get('source_label') or art['source'])}"

    def build(summ: str) -> str:
        body = f"<b>{_e(title)}</b>"
        if summ:
            body += f"\n\n{_e(summ)}"
        return f"{header}{body}\n\n{footer}"

    def visible(text: str) -> int:
        return len(html.unescape(re.sub(r"<[^>]+>", "", text)))

    msg = build(summary)
    if visible(msg) > limit:
        budget = max(0, len(summary) - (visible(msg) - limit) - 2)
        msg = build(truncate(summary, budget) if budget > 20 else "")
    return msg


# --------------------------------------------------------------------------- #
# Client
# --------------------------------------------------------------------------- #

class Telegram:
    def __init__(self, token: str, chat_id: str, state: dict, dry_run: bool = False):
        self.base = f"https://api.telegram.org/bot{token}/"
        self.chat_id = chat_id
        self.dry_run = dry_run
        self.session = requests.Session()
        # state = State.telegram: {"chat_id": ..., "forum": bool, "threads": {section_id: id}}
        if state.get("chat_id") != chat_id:
            state.clear()
            state["chat_id"] = chat_id
        state.setdefault("threads", {})
        self.state = state

    def call(self, method: str, payload: dict) -> dict:
        for attempt in range(1, RETRIES + 1):
            try:
                resp = self.session.post(self.base + method, json=payload, timeout=TIMEOUT)
            except requests.RequestException as exc:
                log.warning("Telegram %s failed (attempt %d): %s", method, attempt, exc)
                time.sleep(SEND_DELAY * attempt)
                continue
            try:
                body = resp.json()
            except ValueError:
                body = {"description": resp.text[:200]}
            if resp.ok and body.get("ok"):
                return body.get("result")
            desc = body.get("description", "")
            if resp.status_code == 429:
                wait = int((body.get("parameters") or {}).get("retry_after", 5)) + 1
                log.warning("Telegram 429, waiting %ss", wait)
                time.sleep(wait)
                continue
            if resp.status_code in (401, 403, 404) or "chat not found" in desc.lower():
                raise TelegramFatalError(f"HTTP {resp.status_code}: {desc}")
            if 400 <= resp.status_code < 500:
                raise TelegramRejected(desc)
            log.warning("Telegram HTTP %s (attempt %d): %s", resp.status_code, attempt, desc)
            time.sleep(SEND_DELAY * attempt)
        raise TelegramFatalError(f"Telegram {method} unavailable after retries")

    # ---- forum topics -------------------------------------------------------

    def setup_topics(self, topics: Topics) -> None:
        """If the group has Topics enabled, make sure each section has a thread."""
        if self.dry_run:
            return
        chat = self.call("getChat", {"chat_id": self.chat_id})
        self.state["forum"] = bool(chat.get("is_forum"))
        if not self.state["forum"]:
            return
        for sec in topics.sections:
            if sec.id in self.state["threads"]:
                continue
            try:
                topic = self.call("createForumTopic",
                                  {"chat_id": self.chat_id, "name": f"{sec.emoji} {sec.name}".strip()})
                self.state["threads"][sec.id] = topic["message_thread_id"]
                log.info("Created Telegram topic %r (thread %s)", sec.name, topic["message_thread_id"])
            except TelegramRejected as exc:
                log.warning("Could not create Telegram topic %r (make the bot an admin with "
                            "'Manage topics'): %s", sec.name, exc)

    def thread_for(self, section_id: str | None) -> int | None:
        if not self.state.get("forum") or not section_id:
            return None
        return self.state["threads"].get(section_id)

    # ---- sending -------------------------------------------------------------

    def send_text(self, text: str, thread: int | None = None, preview_url: str | None = None) -> None:
        if self.dry_run:
            print("-" * 60, f"\n[thread={thread}] {text}")
            return
        payload = {"chat_id": self.chat_id, "text": text, "parse_mode": "HTML"}
        if preview_url:
            payload["link_preview_options"] = {"url": preview_url, "prefer_large_media": True}
        if thread:
            payload["message_thread_id"] = thread
        self.call("sendMessage", payload)

    def send_article(self, art: dict, topics: Topics) -> None:
        sub = topics.subtopics.get(art.get("subtopic", ""))
        section_id = sub.section.id if sub else None
        thread = self.thread_for(section_id)
        try:
            self._send_article(art, topics, thread)
        except TelegramRejected as exc:
            if thread and "thread not found" in exc.description.lower():
                # Topic was deleted in Telegram: forget it (re-created next run) and post to General.
                log.warning("Telegram topic for %s is gone; posting to General", section_id)
                self.state["threads"].pop(section_id, None)
                self._send_article(art, topics, None)
            else:
                raise

    def _send_article(self, art: dict, topics: Topics, thread: int | None) -> None:
        if art.get("image"):
            caption = format_article(art, topics, CAPTION_LIMIT)
            if self.dry_run:
                print("-" * 60, f"\n[thread={thread}] [photo {art['image'][:80]}]\n{caption}")
                return
            payload = {"chat_id": self.chat_id, "photo": art["image"], "caption": caption,
                       "parse_mode": "HTML"}
            if thread:
                payload["message_thread_id"] = thread
            try:
                self.call("sendPhoto", payload)
                return
            except TelegramRejected as exc:
                if "thread not found" in exc.description.lower():
                    raise
                log.info("sendPhoto rejected (%s); sending as text", exc.description)
        self.send_text(format_article(art, topics, MESSAGE_LIMIT), thread, preview_url=art["url"])
