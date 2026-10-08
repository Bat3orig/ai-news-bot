# Dev Мэдээ — AI · Software · UI/UX мэдээний бот

Хөгжүүлэгчийн мэдээг 30 минут тутам шалгаж, **Монгол хэл рүү орчуулан** Telegram group-ийн
**сэдэв тус бүрийн topic** руу илгээж, мөн **зурагтай вэбсайт** дээр нийтэлдэг бот.
GitHub Actions + GitHub Pages дээр үнэгүй ажиллана.

```
GitHub Actions (cron */30)
 1. sources.yaml-ийн RSS-үүдийг татна → шинэ мэдээ олно (state/seen.json)
 2. Мэдээ бүрийн эх хуудсыг нээж зураг (og:image) болон текстийг авна
    (Google News-ийн линкийг жинхэнэ хаяг руу нь задална)
 3. AI-аар Монгол гарчиг, товчлол, дэлгэрэнгүй тайлбар бичүүлнэ
    Gemini 3.8 Flash → Gemini 3.5 Flash-Lite → Claude Haiku 5.5 → (англиар)
 4. data/articles/YYYY/MM/DD/<id>.json  ← мэдээний сан
 5. build_site.py → вэбсайт → GitHub Pages
 6. Telegram: зураг + Монгол гарчиг + товчлол + [Дэлгэрэнгүй] [Эх сурвалж]
    🤖 AI / ⚛️ Software / 🎨 UI/UX topic тус бүр рүү
```

## Сэдвүүд

| Сэдэв | Дэд сэдвүүд |
|---|---|
| 🤖 AI | OpenAI, Gemini, Anthropic, xAI, Qwen, Kimi, AI DevTools |
| ⚛️ Software | React, React Native, Next.js, NestJS, Tauri, Electron, Node.js, Vercel/Cloud |
| 🎨 UI/UX | shadcn/ui, Tailwind CSS, Motion, Design systems, CSS/Web platform |

Бот **зөвхөн эдгээр дэд сэдэвтэй холбоотой** мэдээг илгээнэ. Тодорхойлолт нь `topics.yaml`-д байна.

## Файлын бүтэц

| Файл | Үүрэг |
|---|---|
| `main.py` | `prepare` (татах, орчуулах, хадгалах) ба `send` (Telegram) |
| `build_site.py` | `data/articles/`-аас статик сайт үүсгэнэ → `public/` |
| `topics.yaml` | Сэдэв, дэд сэдэв, keyword, сайтын нэр, хадгалах хугацаа |
| `sources.yaml` | Эх сурвалжууд (аль дэд сэдэвт хамаарах) |
| `newsbot/` | `feeds` (RSS), `enrich` (зураг/текст), `ai` (орчуулга), `telegram`, `store` |
| `site/assets/` | Сайтын CSS, JS |
| `state/seen.json` | Илгээсэн мэдээний ID-ууд |
| `state/outbox.json` | Илгээх дараалал (Telegram алдаа гарвал энд үлдэж дараа нь явна) |
| `state/telegram.json` | Telegram topic-уудын ID (бот өөрөө бөглөнө) |
| `data/articles/` | Мэдээний сан (JSON) |
| `.github/workflows/news.yml` | GitHub Actions |

---

## Тохируулах заавар

### 1. @BotFather-аар бот үүсгэх

1. Telegram дээр [@BotFather](https://t.me/BotFather) → `/newbot`
2. Нэр, `bot`-оор төгссөн username өгнө → **token** авна (`123456789:AAH...`). Хэнд ч бүү үзүүл.

### 2. Telegram group: Topics асаах, ботыг admin болгох, chat_id авах

1. Group үүсгээд ботоо нэмнэ.
2. **Topics асаах:** Group → ✏️ Edit → **Topics** → асаана.
3. **Ботыг admin болгох:** Group → Administrators → Add Admin → бот → **Manage Topics** болон
   **Post/Send messages** эрхийг асаана.
   → Бот анхны ажиллалтаараа **🤖 AI**, **⚛️ Software**, **🎨 UI/UX** topic-уудыг өөрөө үүсгэнэ.
   Topics асаагаагүй бол бүх мэдээ нэг урсгалд, сэдвийн шошготой ирнэ.
4. **chat_id авах:** group-д `/start@<bot_username>` гэж бичээд:
   ```bash
   curl -s "https://api.telegram.org/bot<TOKEN>/getUpdates"
   ```
   Хариунаас `"chat":{"id":-100xxxxxxxxxx, ...}`-г олно (хасах тэмдэгтэй нь).
   `"result":[]` хоосон бол ботыг group-оос хасаад дахин нэмээд дахин ажиллуулна.

   > ⚠️ **Topics асаахад group "supergroup" болж chat_id өөрчлөгддөг** (`-100...` болно).
   > Topics асаасны **дараа** chat_id-гаа авч, `TELEGRAM_CHAT_ID` secret-ийг шинэчилнэ үү.

### 3. API key-үүд

| Secret | Хаанаас | Заавал эсэх |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | @BotFather | Заавал |
| `TELEGRAM_CHAT_ID` | 2-р алхам | Заавал |
| `GEMINI_API_KEY` | [aistudio.google.com/apikey](https://aistudio.google.com/apikey) → Create API key (үнэгүй) | Зөвлөмж |
| `CLAUDE_API_TOKEN` | [platform.claude.com](https://platform.claude.com) → API keys (кредит шаардлагатай) | Нөөц |

Repo → **Settings → Secrets and variables → Actions → New repository secret**.
AI key огт байхгүй бол бот ажилласаар байна, зүгээр л мэдээг англиар илгээнэ.

### 4. GitHub Pages асаах

Repo → **Settings → Pages → Build and deployment → Source: GitHub Actions**.
Сайтын хаяг: `https://<username>.github.io/<repo>/` (жишээ нь `https://bat3orig.github.io/ai-news-bot/`).

> Pages асаагаагүй байсан ч Telegram бот ажиллана (deploy алхам алдаа өгөөд алгасагдана).

### 5. Ажиллуулах

Repo → **Actions → AI News Bot → Run workflow**. Үүнээс хойш 30 минут тутам автоматаар ажиллана.

- `sources.yaml`-д шинээр нэмэгдсэн эх сурвалжийн одоо байгаа мэдээг илгээхгүй, чимээгүй "харсан" гэж
  тэмдэглэнэ. Зөвхөн дараа нь гарах шинэ мэдээ ирнэ.
- Нэг ажиллалтад дээд тал нь 20 мессеж. Үлдсэн нь дараагийн ажиллалтаар явна.

---

## AI орчуулга (Gemini → Claude)

- Ажиллалт бүр **эхлээд Gemini**-г оролдоно. Квот дууссан (429) эсвэл алдаа гарвал дараагийн загвар руу,
  эцэст нь Claude руу шилжинэ. Дараагийн ажиллалт дахиад Gemini-ээс эхэлнэ, тиймээс квот сэргэмэгц
  автоматаар буцна.
- Нэг ажиллалтын мэдээг 8-аар нь багцалж нэг хүсэлтээр орчуулна (өдөрт ~50–100 хүсэлт).
- Холимог эх сурвалжийн (Hacker News) мэдээг AI мөн ангилж, сэдэвт хамаагүй бол алгасна.
- Гинжийг өөрчлөх: Settings → Secrets and variables → Actions → **Variables** → `AI_PROVIDERS`
  ```
  gemini:gemini-3.8-flash,gemini:gemini-3.5-flash-lite,claude:claude-haiku-5-5
  ```
  Жишээ нь зөвхөн үнэгүй байлгах бол `gemini:gemini-3.8-flash,gemini:gemini-3.5-flash-lite`.
- Gemini-ийн үнэгүй хязгаарыг [AI Studio](https://aistudio.google.com) → таны project-ийн rate limit хэсгээс харна.

## Сайт

- **Нүүр:** сэдэв бүрийн дэд сэдвүүд (тоотой) + сүүлийн мэдээ
- **`/ai/`, `/software/`, `/uiux/`:** сэдвийн бүх мэдээ, 30-аар хуудаслана
- **`/t/<дэд сэдэв>/`:** тухайн дэд сэдвийн бүх мэдээ (жишээ нь `/t/nextjs/`)
- **`/a/<id>.html`:** мэдээний хуудас — зураг, Монгол дэлгэрэнгүй, эх мэдээний холбоос, холбоотой мэдээ
- Бүх мэдээнээс хайх, dark/light горим, гар утсанд тохирсон

### Хадгалалт ба repo-ийн хэмжээ

Мэдээ бүр ~3–6 KB JSON. Өдөрт 50–100 мэдээ гэвэл сард ~10–15 MB, жилд git түүхтэйгээ ~100–150 MB
(git шахдаг тул бодитоор үүнээс бага). GitHub repo-г 1 GB-аас бага байлгахыг зөвлөдөг тул олон жил
асуудалгүй. `topics.yaml` → `site.keep_days` (default 180) хоногоос хуучин мэдээг автоматаар устгана.
`0` бол үүрд хадгална.

---

## Сэдэв / эх сурвалж нэмэх

**Шинэ дэд сэдэв** — `topics.yaml`:
```yaml
      - id: svelte                # URL-д орно: /t/svelte/
        name: Svelte
        hashtag: Svelte
        keywords: [Svelte, SvelteKit]   # холимог эх сурвалжаас ангилахад
        about: Svelte and SvelteKit framework
```

**Шинэ эх сурвалж** — `sources.yaml`:
```yaml
  - name: Svelte Blog
    url: https://svelte.dev/blog/rss.xml
    subtopic: svelte

  - name: sveltejs/svelte                       # GitHub release
    url: https://github.com/sveltejs/svelte/releases.atom
    type: github_release
    subtopic: svelte
    skip_prereleases: true                      # canary/alpha/beta/rc алгасна
```
Албан ёсны RSS байхгүй бол Google News:
`https://news.google.com/rss/search?q=<QUERY>&hl=en-US&gl=US&ceid=US:en` (`type: google_news`).

## Локал дээр турших

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

python main.py --dry-run          # юу илгээгдэхийг хэвлэнэ; state/, data/-г өөрчлөхгүй, Telegram руу илгээхгүй
python build_site.py              # data/articles-аас public/ үүсгэнэ
python -m http.server -d public   # http://localhost:8000
```
AI орчуулгыг локалаар турших бол `export GEMINI_API_KEY=...` хийгээд `--dry-run` ажиллуулна
(dry-run ч гэсэн AI API-г дуудна).

Тусдаа хавтсанд бүтэн туршилт: `python main.py prepare --state-dir /tmp/s --data-dir /tmp/d`

---

## Эх сурвалжийн төлөв (2026-10-08-нд шалгасан)

Бүх URL-ийг `requests` + `feedparser`-ээр шалгасан. 40 эх сурвалж бүгд ажиллаж байна.

**🤖 AI:** OpenAI News, Google DeepMind, Google AI Blog, Google Developers Blog (keyword шүүлттэй),
Anthropic / xAI / Qwen / Kimi (Google News), GitHub Changelog & Blog (AI keyword шүүлттэй),
anthropics/claude-code, openai/codex, openai/openai-python, ollama/ollama releases

**⚛️ Software:** React Blog, facebook/react, React Native Blog, facebook/react-native, Expo Changelog,
Next.js Blog, vercel/next.js, nestjs/nest, Tauri Blog, tauri-apps/tauri, Electron Blog, electron/electron,
Node.js Blog, Vercel

**🎨 UI/UX:** shadcn/ui, shadcn-ui/ui, Tailwind CSS Blog, tailwindlabs/tailwindcss, Motion Blog,
motiondivision/motion, Figma Blog, Smashing Magazine, CSS-Tricks, web.dev, Chrome for Developers

**Холимог:** Hacker News (100+ оноотой, `topics.yaml`-ийн keyword-оор ангилна)

### ❌ Эвдэрсэн / байхгүй (орлуулсан)

| Эх сурвалж | Шалгасан URL | Үр дүн | Орлуулсан |
|---|---|---|---|
| Anthropic | `anthropic.com/news/rss.xml` | 404 | Google News |
| xAI | `x.ai/news/rss.xml` | 404 | Google News |
| Qwen | `qwenlm.github.io/blog/index.xml` | 2025-09-өөс хойш шинэчлэгдээгүй | Google News |
| Qwen / Kimi GitHub | `QwenLM/Qwen3`, `MoonshotAI/Kimi-K2` releases | Release байхгүй | Google News |
| NestJS блог | `trilon.io/blog/rss.xml` | 404 | nestjs/nest releases |

> Next.js, React Native, Electron, Codex зэрэг нь canary/rc/nightly-г өдөр бүр гаргадаг тул
> `skip_prereleases: true` тохиргоогоор зөвхөн тогтвортой хувилбарыг авна.

## Алдаа засах

| Шинж тэмдэг | Шийдэл |
|---|---|
| `TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set` | Secrets-ийн нэрийг шалгах |
| `HTTP 400: chat not found` | chat_id буруу — Topics асаасны дараа chat_id өөрчлөгддөг |
| `Could not create Telegram topic` | Ботыг admin болгож **Manage Topics** эрх өгөх |
| Мэдээ англиар ирж байна | `GEMINI_API_KEY` / `CLAUDE_API_TOKEN` secret, Actions log дахь `AI ... failed` мөр |
| `Deploy to GitHub Pages` алдаа | Settings → Pages → Source: **GitHub Actions** |
| Push дээр `403` | Settings → Actions → General → Workflow permissions → Read and write |
| Топик устгачихсан | Бот автоматаар General руу илгээж, дараагийн ажиллалтад дахин үүсгэнэ |
