# CLAUDE.md — Dev Мэдээ (ai-news-bot)

Project context for Claude Code. Read this first; it is everything the previous sessions established.

## Working with the user
- The user writes in **Mongolian** — reply in Mongolian. Keep code, comments and commit messages in English.
  `README.md` and user-facing text (Telegram messages, site UI, YAML comments) are in Mongolian.
- The user is not deeply technical about GitHub/Telegram setup: give exact click paths and commands.
- The user approved Claude pushing to `origin main` for this project. Still say what you pushed.
- Never hardcode secrets. No API keys exist on this machine; `gh` CLI is installed but **not logged in**
  (can't read Actions logs — ask the user to paste them).

## What it is
A Telegram + website news bot for developers, running free on GitHub Actions + GitHub Pages.
- Repo: https://github.com/Bat3orig/ai-news-bot (public, branch `main`)
- Site: https://bat3orig.github.io/ai-news-bot/
- Every 30 min: fetch feeds → pick new items → read article page (image/text) → translate to Mongolian
  with AI → save `data/articles/…json` → build & deploy site → post to Telegram forum topics.

Topics (`topics.yaml`, chosen by the user — only these are sent):
- **AI**: OpenAI, Gemini, Anthropic, xAI, Qwen, Kimi, AI DevTools
- **Software**: React, React Native, Next.js, NestJS, Tauri, Electron, Node.js, Vercel/Cloud
- **UI/UX**: shadcn/ui, Tailwind CSS, Motion, Design systems, CSS/Web platform
- **Software › Packages** (2026-10-14): JavaScript Weekly, Node Weekly, React Status, Frontend Focus
  newsletters; the AI writes about the 3–5 notable packages in each issue (`ai_hint`).
- **GitHub** (2026-10-14): trending repos from mshibanami/GitHubTrendingRSS daily feeds for
  TypeScript, JavaScript (both → `gh-js`), Python, Rust. Entries are undated, ranked; `limit: 2–3`
  per feed per fetch, the rest marked seen. Subtopics are `dedicated: true` (AI never assigns them
  to mixed sources such as Hacker News).
- **Vibe coding** (2026-10-14, own Telegram topic): the user wants **usage-side** content (tips,
  workflows, tool how-tos), not business news. Sources: Simon Willison (`/atom/entries/`), Addy
  Osmani, Harper Reed, Builder.io, Cursor changelog. Reddit works locally but usually blocks
  Actions IPs, so it is not used. Google News "vibe coding" is too business-heavy, so it is not used.
- Source fields `limit` and `ai_hint` (passed to the AI as `editor_note`) are in `sources.yaml`.

## Layout
| Path | Role |
|---|---|
| `main.py` | CLI: `prepare` (fetch/enrich/translate/save/outbox), `send` (Telegram), default = both; `--dry-run`, `--state-dir`, `--data-dir` |
| `build_site.py` | static site from `data/articles` → `public/` (gitignored). Pages: `/`, `/<section>/`, `/t/<subtopic>/` (30/page, `page-N.html`), `/a/<id>.html`, `search.json` |
| `newsbot/config.py` | loads `topics.yaml` / `sources.yaml`; keyword classifier (longest keyword wins); prerelease regex |
| `newsbot/feeds.py` | parallel fetch (8 threads), item build, selection/dedup/bootstrap |
| `newsbot/enrich.py` | Google News URL decoding (batchexecute), og:image + `<p>` text via stdlib HTMLParser |
| `newsbot/ai.py` | provider chain, JSON output, 8 items per request |
| `newsbot/telegram.py` | Bot API client, forum topics, sendPhoto → sendMessage fallback |
| `newsbot/store.py` | `state/` JSON files, article files, pruning |
| `site/assets/` | `style.css` (light/dark tokens), `app.js` (theme, relative time, global search) |
| `.github/workflows/news.yml` | prepare → build → upload/deploy Pages (continue-on-error) → send → commit `state data` |

State (committed by the bot every run):
- `state/seen.json` — `{"sources": [...names fetched at least once], "items": {16-hex key: "YYYY-MM-DD"}}`. Keys = sha256[:16] of entry.id and of utm-stripped link (+ resolved Google News URL). Pruned after 30 days.
- `state/outbox.json` — messages waiting to be sent (survives Telegram failures). Max 20 per run.
- `state/telegram.json` — `chat_id`, `forum`, `threads` {section: thread_id}, `names` (topic names applied).
- `data/articles/YYYY/MM/DD/<id>.json` — the "database". Deleted after `site.keep_days` (180).

## Key behaviors / decisions (don't regress)
- **First run** (empty seen.json): send nothing, mark all seen, send "Bot started, tracking N sources".
- **New source** (name not in `state.sources`): its current items are marked seen silently. Renaming a source = new source.
- Only items newer than 3 days; oldest first; 3 s between messages; honor 429 `retry_after`.
- Sending hours (2026-10-14, user request): Telegram only 08:00–21:00 Mongolia time (`topics.yaml` →
  `telegram.send_hours` / `utc_offset: 8`), max 10 messages per run (`max_per_send`); the rest stay in
  the outbox for the next run. `prepare` keeps running at night (site stays fresh): 20 items per run,
  paused while the outbox holds ≥50 (`MAX_OUTBOX`). `send --ignore-hours` bypasses the window for tests.
- Sources with `subtopic:` are trusted; sources without (Hacker News, Smashing with `section:`) must match `topics.yaml` keywords, and the AI can mark them `relevant: false` → dropped.
- Noise filter (2026-10-14, user request — Google News flooded the AI topic with business/spam):
  1. `sources.yaml` → `block:` publishers (substring of outlet name or resolved URL host) and title
     keywords; dropped before the AI (`drop_blocked`, run before and after enrich).
  2. AI `score` 1–5 = usefulness for developers; below `topics.yaml` → `filter.min_score` (3) is
     dropped, except `github_release` sources. 2 = business/partnerships/IPO/lawsuits/politics/
     AI-safety incidents/gadgets. User said AI-incident stories (e.g. "Claude sent police a false
     tip") are NOT wanted. Score is saved in the article JSON (`score`) for tuning.
- `skip_prereleases` drops canary/alpha/beta/rc/nightly; `title_regex` for multi-package repos (tauri, shadcn).
- GitHub release titles get the repo prefix ("claude-code v2.1.290").
- Duplicate stories (Google News brings one story from 3–6 outlets), two layers:
  1. `drop_duplicates` in `main.py`: near-identical headlines vs. articles of the last 7 days
     (`store.recent_titles`) and earlier items in the run. Deliberately strict (≥4 shared words and
     ≥80% overlap) — looser matching dropped different stories, since most headlines share
     "Anthropic"/"Claude"/"AI Gateway". Tested on real data: no false positives.
  2. The AI gets `already_published` ("date: title"): `ai._related` picks up to 60 headlines of the
     last 7 days that share a word rare in that week with the chunk's titles/text, plus the newest 15
     and titles kept by earlier chunks. It returns `duplicate: true` for the same story even days
     later / reworded / follow-ups → skipped. (Before: last 80 titles ≈ 1–2 days, so one story
     came back 6 times over 3 days.)
- AI chain (env `AI_PROVIDERS`, repo variable optional): `gemini:gemini-3.8-flash,gemini:gemini-3.5-flash-lite,claude:claude-haiku-5-5`. Each run restarts from Gemini; a provider that 429s is skipped for the rest of the run; no keys → English fallback. Claude uses the official `anthropic` SDK with `output_config={"effort": "low", "format": json_schema}`. Haiku 5.5 was chosen by the user for cost (~$2–4/month worst case).
- Secrets: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `GEMINI_API_KEY`, `CLAUDE_API_TOKEN` (mapped to `ANTHROPIC_API_KEY` in the workflow).
- Telegram: group has Topics on, bot is admin with Manage Topics. Bot creates/renames topics to plain names "AI", "Software", "UI/UX" (no emoji — user asked; Telegram shows its own icon). Deleted topic → post to General, recreate next run. Messages: photo + caption (≤1024 visible chars) with header `🤖 <b>AI</b> · #OpenAI`, Mongolian title, summary, links "Дэлгэрэнгүй" (site) · "Эх сурвалж".
- Site is built **before** sending so the "Дэлгэрэнгүй" links work on arrival.

## Commands
```bash
.venv/bin/python main.py --dry-run                 # full run, prints; writes nothing, sends nothing
.venv/bin/python main.py prepare --state-dir /tmp/s --data-dir /tmp/d   # isolated real run
.venv/bin/python build_site.py --data-dir /tmp/d --out /tmp/site
python -m http.server -d public
```
- `.venv` (Python 3.12) exists locally; `pip install -r requirements.txt` if missing.
- **Always `git pull --rebase origin main` before editing** — the bot commits `state/` and `data/` every 30 min.
- Headless Chrome screenshots work: `"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --headless=new --screenshot=...` (min window width is ~500px; use an iframe to test 375px).
- Use the scratchpad for test state, never the real `state/` with non-dry runs.

## Status (2026-10-14)
- Deployed and running. gemini-3.8-flash works part of the time (45 articles 10/09–10/14), so the
  model id is right; the fallbacks are its free-quota 429s. No action needed.
- 2026-10-14: sending hours (08:00–21:00 MN, 10 per run) committed and pushed (`3050d14`).
- 2026-10-14: noise filter (block list, AI score, 7-day dedup) pushed by the user (`2187778`).
  The AI score and dedup are tested only with mocks, so check the "AI: low value" and
  "AI: duplicate story" log lines.
- 2026-10-14: GitHub / Vibe coding topics and Packages added. New sources bootstrap silently on
  their first run, so the first posts arrive at the next feed update (trending updates daily).
- **PENDING:** cleanup of old articles. The user asked for it, but deleting was blocked. The review
  kept 63 of 237 (releases, Vercel/AI Gateway, Copilot changelog, model launches, Claude features,
  technical HN posts) and dropped 174 (business, partnerships, IPO, crypto, AI-incident stories,
  "cruelty to Claude" copies, customer stories, SEO sites). Redo the review with the new rules, and
  get explicit approval before deleting.
- 2026-10-09: duplicate-story dedup added (see Key behaviors); the AI layer is tested only with a
  mocked provider — check the next runs' "AI: duplicate story" log lines.
- Open suggestion awaiting the user's answer: whether to drop the emoji (🤖/⚛️/🎨) from the message
  header line too.
- Verified sources/broken list is in `README.md`.
