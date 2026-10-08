#!/usr/bin/env python3
"""Build the static news site from data/articles/ into public/.

    python build_site.py                 # -> public/
    python build_site.py --out /tmp/site

Pages:
    index.html              latest across all sections
    <section>/index.html    ai/, software/, uiux/
    t/<subtopic>/index.html one subtopic
    a/<id>.html             article page (Open Graph tags for Telegram/Facebook previews)
"""

from __future__ import annotations

import argparse
import html
import json
import math
import os
import shutil
from collections import Counter
from datetime import datetime
from pathlib import Path

from newsbot import store
from newsbot.config import ROOT, Topics, load_topics
from newsbot.util import UB_TZ, parse_iso

ASSETS = ROOT / "site" / "assets"
INDEX_LIMIT = 30
PAGE_SIZE = 30


def e(text) -> str:
    return html.escape(str(text or ""), quote=True)


def site_url() -> str:
    url = os.environ.get("SITE_URL", "").strip()
    if not url and os.environ.get("GITHUB_REPOSITORY"):
        owner, repo = os.environ["GITHUB_REPOSITORY"].split("/", 1)
        url = f"https://{owner.lower()}.github.io/{repo}/"
    return url.rstrip("/") + "/" if url else ""


def fmt_time(iso_str: str) -> str:
    dt = parse_iso(iso_str)
    return dt.astimezone(UB_TZ).strftime("%Y.%m.%d %H:%M") if dt else ""


class Site:
    def __init__(self, topics: Topics, articles: list[dict], out: Path, base_url: str):
        self.t = topics
        self.out = out
        self.base = base_url
        known = [a for a in articles if a.get("subtopic") in topics.subtopics]
        self.articles = sorted(known, key=lambda a: (a.get("published") or "", a["id"]), reverse=True)

    # ---- helpers -------------------------------------------------------------

    def sub(self, art):
        return self.t.subtopics[art["subtopic"]]

    def title_of(self, art) -> str:
        return art.get("title_mn") or art.get("title", "")

    def summary_of(self, art) -> str:
        return art.get("summary_mn") or art.get("summary_en", "")

    def write(self, rel: str, content: str) -> None:
        path = self.out / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def page(self, rel: str, title: str, body: str, active: str = "", description: str = "",
             og_image: str = "", og_type: str = "website") -> None:
        depth = rel.count("/")
        root = "../" * depth
        desc = description or self.t.site_description
        full_title = f"{title} — {self.t.site_title}" if title != self.t.site_title else title
        nav = [f'<a href="{root}index.html" class="{"on" if active == "home" else ""}">Нүүр</a>']
        for sec in self.t.sections:
            nav.append(f'<a href="{root}{sec.id}/index.html" class="{"on" if active == sec.id else ""}">'
                       f'{e(sec.emoji)} {e(sec.name)}</a>')
        og = [
            f'<meta property="og:title" content="{e(title)}">',
            f'<meta property="og:description" content="{e(desc)}">',
            f'<meta property="og:type" content="{og_type}">',
            f'<meta property="og:site_name" content="{e(self.t.site_title)}">',
        ]
        if self.base:
            og.append(f'<meta property="og:url" content="{e(self.base + rel.removesuffix("index.html"))}">')
            og.append(f'<link rel="canonical" href="{e(self.base + rel.removesuffix("index.html"))}">')
        if og_image:
            og.append(f'<meta property="og:image" content="{e(og_image)}">')
            og.append('<meta name="twitter:card" content="summary_large_image">')
        self.write(rel, f"""<!doctype html>
<html lang="mn">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(full_title)}</title>
<meta name="description" content="{e(desc)}">
{chr(10).join(og)}
<link rel="icon" href="data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 100 100%22><text y=%22.9em%22 font-size=%2290%22>📰</text></svg>">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<link rel="stylesheet" href="{root}assets/style.css">
<script>try{{var t=localStorage.getItem("theme");if(t)document.documentElement.setAttribute("data-theme",t)}}catch(e){{}}</script>
</head>
<body>
<header class="top"><div class="wrap">
  <a class="brand" href="{root}index.html"><span class="logo">D</span>{e(self.t.site_title)}</a>
  <nav class="nav">{"".join(nav)}</nav>
  <div class="tools">
    <input id="q" class="search" type="search" placeholder="Бүх мэдээнээс хайх…" aria-label="Хайх" data-root="{root}">
    <button id="theme" class="icon-btn" type="button" aria-label="Өнгөний горим">◐</button>
  </div>
</div></header>
<main class="wrap">
<div id="results" hidden></div>
<div id="content">
{body}
</div>
</main>
<footer><div class="wrap">
  Мэдээг AI-аар орчуулж, товчилсон тул алдаа байж болно — эх сурвалжийг шалгаарай.
  Шинэчлэгдсэн: {datetime.now(UB_TZ).strftime("%Y.%m.%d %H:%M")} (УБ цаг)
</div></footer>
<script src="{root}assets/app.js"></script>
</body>
</html>
""")

    def card(self, art: dict, root: str, featured: bool = False) -> str:
        sub = self.sub(art)
        title, summary = self.title_of(art), self.summary_of(art)
        img = art.get("image")
        media = (f'<img src="{e(img)}" alt="" loading="lazy" referrerpolicy="no-referrer" data-fallback>'
                 if img else "")
        search = f"{title} {summary} {sub.name} {art.get('source_label', '')} {art.get('title', '')}".lower()
        en = '' if art.get("title_mn") else '<span class="en">EN</span>'
        return f"""<a class="card sec-{sub.section.id}{' featured' if featured else ''}" href="{root}a/{e(art['id'])}.html" data-search="{e(search)}">
  <div class="media{'' if img else ' noimg'}">{media}<div class="ph"><div><span>{e(sub.section.emoji)}</span>{e(sub.name)}</div></div></div>
  <div class="body">
    <div class="tag">#{e(sub.hashtag)} {en}</div>
    <h2>{e(title)}</h2>
    <p>{e(summary)}</p>
    <div class="meta"><span>{e(art.get('source_label') or art.get('source'))}</span>·<time datetime="{e(art.get('published'))}">{e(fmt_time(art.get('published')))}</time></div>
  </div>
</a>"""

    def grid(self, arts: list[dict], root: str, feature_first: bool = False) -> str:
        if not arts:
            return '<div class="empty">Одоогоор мэдээ алга. Удахгүй нэмэгдэнэ.</div>'
        cards = [self.card(a, root, feature_first and i == 0) for i, a in enumerate(arts)]
        return '<div class="grid">' + "\n".join(cards) + '</div>'

    def chips(self, section, root: str, active: str, counts: Counter) -> str:
        out = [f'<a class="chip{" on" if active == "" else ""}" href="{root}{section.id}/index.html">Бүгд</a>']
        for s in section.subtopics:
            out.append(f'<a class="chip{" on" if active == s.id else ""}" href="{root}t/{s.id}/index.html">'
                       f'{e(s.name)} <span class="n">{counts.get(s.id, 0)}</span></a>')
        return f'<div class="chips sec-{section.id}">{"".join(out)}</div>'

    # ---- pages -----------------------------------------------------------------

    def paged(self, folder: str, title: str, head: str, arts: list[dict], root: str, active: str) -> None:
        pages = max(1, math.ceil(len(arts) / PAGE_SIZE))
        for n in range(1, pages + 1):
            chunk = arts[(n - 1) * PAGE_SIZE: n * PAGE_SIZE]
            name = "index.html" if n == 1 else f"page-{n}.html"
            href = lambda k: "index.html" if k == 1 else f"page-{k}.html"  # noqa: E731
            nav = ""
            if pages > 1:
                links = [f'<a class="pg{" on" if k == n else ""}" href="{href(k)}">{k}</a>'
                         for k in range(1, pages + 1)]
                prev = f'<a class="pg" href="{href(n - 1)}">← Өмнөх</a>' if n > 1 else ""
                nxt = f'<a class="pg" href="{href(n + 1)}">Дараах →</a>' if n < pages else ""
                nav = f'<nav class="pager">{prev}{"".join(links)}{nxt}</nav>'
            self.page(f"{folder}/{name}", title if n == 1 else f"{title} ({n})",
                      head + self.grid(chunk, root, feature_first=(n == 1)) + nav, active=active)

    def build(self) -> None:
        if self.out.exists():
            shutil.rmtree(self.out)
        shutil.copytree(ASSETS, self.out / "assets")
        counts = Counter(a["subtopic"] for a in self.articles)

        # home: latest news + every subtopic grouped by section
        groups = []
        for sec in self.t.sections:
            chips = "".join(
                f'<a class="chip" href="t/{x.id}/index.html">{e(x.name)} <span class="n">{counts[x.id]}</span></a>'
                for x in sec.subtopics)
            groups.append(f'<div class="group sec-{sec.id}"><a class="group-title" href="{sec.id}/index.html">'
                          f'{e(sec.emoji)} {e(sec.name)} <span class="n">'
                          f'{sum(counts[x.id] for x in sec.subtopics)}</span></a><div class="chips">{chips}</div></div>')
        self.page("index.html", self.t.site_title,
                  f'<div class="head"><h1>{e(self.t.site_title)}</h1><p>{e(self.t.site_description)}</p></div>'
                  f'<div class="groups">{"".join(groups)}</div>'
                  f'<h2 class="section-title">Сүүлийн мэдээ</h2>'
                  + self.grid(self.articles[:INDEX_LIMIT], "", feature_first=True), active="home")

        # sections and subtopics: every stored article, PAGE_SIZE per page
        for sec in self.t.sections:
            ids = {x.id for x in sec.subtopics}
            arts = [a for a in self.articles if a["subtopic"] in ids]
            head = (f'<div class="head"><h1>{e(sec.emoji)} {e(sec.name)}</h1>'
                    f'<p>{e(", ".join(x.name for x in sec.subtopics))}</p></div>'
                    + self.chips(sec, "../", "", counts))
            self.paged(f"{sec.id}", sec.name, head, arts, "../", sec.id)
        for sub in self.t.subtopics.values():
            arts = [a for a in self.articles if a["subtopic"] == sub.id]
            head = (f'<div class="head"><h1>{e(sub.name)}</h1>'
                    f'<p>#{e(sub.hashtag)} · {e(sub.section.name)} · {len(arts)} мэдээ</p></div>'
                    + self.chips(sub.section, "../../", sub.id, counts))
            self.paged(f"t/{sub.id}", sub.name, head, arts, "../../", sub.section.id)

        # global search index (loaded by app.js only when someone types)
        index = [{"i": a["id"], "t": self.title_of(a), "e": a.get("title", ""), "s": a["subtopic"],
                  "p": a.get("published", "")} for a in self.articles]
        names = {x.id: [x.name, x.section.id] for x in self.t.subtopics.values()}
        (self.out / "search.json").write_text(
            json.dumps({"subtopics": names, "items": index}, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8")

        # articles
        for art in self.articles:
            self.article(art, counts)

        self.page("404.html", "Олдсонгүй",
                  '<div class="empty"><h1>404</h1><p>Энэ хуудас олдсонгүй.</p>'
                  '<p><a class="btn" href="index.html">Нүүр хуудас руу</a></p></div>')
        (self.out / ".nojekyll").write_text("")

    def article(self, art: dict, counts: Counter) -> None:
        sub = self.sub(art)
        root = "../"
        title = self.title_of(art)
        body_text = art.get("body_mn") or art.get("summary_en") or ""
        paras = "".join(f"<p>{e(p.strip())}</p>" for p in body_text.split("\n") if p.strip())
        img = art.get("image")
        hero = (f'<div class="hero"><img src="{e(img)}" alt="" referrerpolicy="no-referrer" data-fallback></div>'
                if img else "")
        related = [a for a in self.articles if a["subtopic"] == sub.id and a["id"] != art["id"]][:3]
        rel_html = (f'<section class="related"><h3>Холбоотой мэдээ</h3>{self.grid(related, root)}</section>'
                    if related else "")
        ai_note = ""
        if art.get("ai"):
            ai_note = f'<p class="note">Монгол орчуулга, товчлолыг AI ({e(art["ai"].split(":")[-1])}) хийсэн.</p>'
        elif not art.get("title_mn"):
            ai_note = '<p class="note">Энэ мэдээг орчуулж амжаагүй тул англи хэлээр харуулж байна.</p>'
        body = f"""<article class="article sec-{sub.section.id}">
  <div class="crumbs">
    <a class="chip" href="{root}{sub.section.id}/index.html">{e(sub.section.emoji)} {e(sub.section.name)}</a>
    <a class="chip on" href="{root}t/{sub.id}/index.html">#{e(sub.hashtag)}</a>
  </div>
  <h1>{e(title)}</h1>
  <div class="meta"><span>{e(art.get('source_label') or art.get('source'))}</span>·<time datetime="{e(art.get('published'))}">{e(fmt_time(art.get('published')))}</time></div>
  {hero}
  <div class="content">{paras}</div>
  <div class="orig">
    <div><small>Эх мэдээ ({e(art.get('source_label') or art.get('source'))})</small>{e(art.get('title'))}</div>
    <a class="btn" href="{e(art['url'])}" target="_blank" rel="noopener">Эх мэдээг унших →</a>
  </div>
  {ai_note}
  {rel_html}
</article>"""
        self.page(f"a/{art['id']}.html", title, body, active=sub.section.id,
                  description=self.summary_of(art), og_image=img or "", og_type="article")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the static site")
    parser.add_argument("--out", type=Path, default=ROOT / "public")
    parser.add_argument("--data-dir", type=Path, default=store.DATA_DIR)
    args = parser.parse_args()
    topics = load_topics()
    articles = store.load_articles(args.data_dir)
    Site(topics, articles, args.out, site_url()).build()
    print(f"Built {len(articles)} articles into {args.out}")


if __name__ == "__main__":
    main()
