# AI News Telegram Bot

AI болон хөгжүүлэгчийн мэдээг 30 минут тутам шалгаж, **зөвхөн шинэ** мэдээг таны Telegram чат руу илгээдэг бот. GitHub Actions дээр үнэгүй ажиллана — сервер хэрэггүй.

Хамрах сэдэв: ChatGPT/OpenAI, Gemini/Google, Claude/Anthropic, Meta, Mistral, xAI, DeepSeek, Qwen, Hugging Face, Microsoft/GitHub, open-source загварууд, AI хөгжүүлэгчийн хэрэгслүүд, Hacker News.

## Хэрхэн ажилладаг вэ

```
GitHub Actions (cron */30) → main.py → sources.yaml дахь feed-үүдийг татна
  → state/seen.json-тэй харьцуулна → шинэ мэдээг Telegram руу илгээнэ
  → seen.json өөрчлөгдсөн бол commit + push хийнэ
```

- **Анхны ажиллалт** (`seen.json` хоосон): юу ч илгээхгүй, одоо байгаа бүх мэдээг "харсан" гэж тэмдэглээд `Bot started, tracking N sources` гэсэн ганц мессеж илгээнэ.
- Зөвхөн **сүүлийн 3 хоногийн** мэдээг, **хуучнаас нь эхлэн** илгээнэ.
- Нэг ажиллалтад **дээд тал нь 20** мессеж, мессеж хооронд 3 секунд. Үлдсэн нь дараагийн ажиллалтаар явна. Telegram 429 өгвөл `retry_after` хүлээгээд дахин оролдоно.
- Нэг эх сурвалж (timeout, 4xx/5xx, parse error) алдаа өгвөл log-д бичээд бусдыг нь үргэлжлүүлнэ.
- Ижил линк хоёр өөр эх сурвалжаас ирвэл нэг л удаа илгээнэ (`utm_*` параметрийг хасаж харьцуулна).
- `seen.json`-оос 30 хоногоос хуучин бичлэгийг автоматаар устгана.
- `sources.yaml`-д **шинээр нэмсэн** эх сурвалжийн одоо байгаа мэдээг мөн чимээгүй "харсан" гэж тэмдэглэнэ (spam болохгүй).

## Файлын бүтэц

| Файл | Үүрэг |
|---|---|
| `main.py` | Үндсэн логик |
| `sources.yaml` | Эх сурвалжийн жагсаалт |
| `state/seen.json` | Илгээсэн мэдээний ID-ууд (бот өөрөө шинэчилнэ) |
| `.github/workflows/news.yml` | GitHub Actions workflow |
| `requirements.txt` | Python dependency (feedparser, requests, PyYAML) |

---

## Тохируулах заавар

### 1. @BotFather-аар бот үүсгэж token авах

1. Telegram дээр [@BotFather](https://t.me/BotFather)-г нээнэ.
2. `/newbot` гэж бичнэ.
3. Ботын нэр (жишээ нь `My AI News`), дараа нь `bot`-оор төгссөн username (жишээ нь `my_ai_news_bot`) өгнө.
4. BotFather танд иймэрхүү **token** өгнө:
   ```
   123456789:AAHk1x2y3z-AbCdEfGhIjKlMnOpQrStUvWx
   ```
   Үүнийг хэнд ч бүү үзүүл, код дотор бүү бич.

### 2. Telegram group үүсгэж, ботоо нэмээд chat_id авах

1. Telegram дээр шинэ group үүсгэнэ (жишээ нь "AI News").
2. Group-ийн гишүүдэд ботоо нэмнэ (username-аар нь хайна).
3. Group дотор ямар нэг мессеж бичнэ. Ботын privacy mode идэвхтэй үед энгийн мессеж ботод хүрэхгүй байж болох тул команд илгээх нь найдвартай:
   ```
   /start@my_ai_news_bot
   ```
4. Терминал дээр (`<TOKEN>`-г өөрийн token-оор солино):
   ```bash
   curl -s "https://api.telegram.org/bot<TOKEN>/getUpdates"
   ```
   Хариунаас `"chat":{"id":-100xxxxxxxxxx,"title":"AI News","type":"supergroup"...}` хэсгийг олно. Энэ `id` (хасах тэмдэгтэйгээ хамт) нь таны **chat_id**.

   `jq` суусан бол шууд гаргаж болно:
   ```bash
   curl -s "https://api.telegram.org/bot<TOKEN>/getUpdates" | jq '.result[] | (.message // .my_chat_member).chat | {id, title, type}'
   ```
   > `"result":[]` хоосон гарвал group дотор дахин `/start@my_ai_news_bot` бичээд дахин оролдоно уу.
   > Group-ийг supergroup болгоход chat_id өөрчлөгддөг (`-100...` болно) — тэр үед шинэ id-г ашиглана.

5. Шалгах (group-д "test" гэж ирэх ёстой):
   ```bash
   curl -s "https://api.telegram.org/bot<TOKEN>/sendMessage" -d chat_id=<CHAT_ID> -d text=test
   ```

> Хувийн чат руу илгээх бол ботдоо `/start` гэж бичээд дээрх `getUpdates`-ээр өөрийн chat_id-г (эерэг тоо) авна.

### 3. GitHub repo үүсгэх

1. GitHub дээр шинэ repo үүсгэнэ (README, .gitignore нэмэлгүй, хоосон).
   - **Public (зөвлөмж):** GitHub Actions минут хязгааргүй үнэгүй.
   - **Private:** сард 2,000 минут үнэгүй. Нэг ажиллалт ~1 минут (GitHub job бүрийг минут руу дээш тоймлодог) × өдөрт 48 × 30 хоног ≈ 1,440 минут — хязгаарт багтана.
   - Public repo-д `seen.json` дахь hash-ууд л харагдана; token, chat_id нь Secrets-д нууцлагдсан тул ил гарахгүй.
2. Энэ хавтсыг push хийнэ (git аль хэдийн init хийгдсэн, анхны commit бэлэн):
   ```bash
   cd ai-news-bot
   git remote add origin https://github.com/<USERNAME>/<REPO>.git
   git push -u origin main
   ```

### 4. Secrets нэмэх

Repo → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**:

| Name | Value |
|---|---|
| `TELEGRAM_BOT_TOKEN` | BotFather-ийн өгсөн token |
| `TELEGRAM_CHAT_ID` | 2-р алхмын chat_id (жишээ нь `-1001234567890`) |

> Workflow нь `permissions: contents: write` гэж зарласан тул `seen.json`-г push хийж чадна. Хэрэв push дээр `403` алдаа гарвал **Settings → Actions → General → Workflow permissions**-ийг **Read and write permissions** болгоно уу.

### 5. Анх удаа гараар ажиллуулах (workflow_dispatch)

1. Repo → **Actions** таб. (Анх удаа бол "I understand my workflows, go ahead and enable them" товчийг дарна.)
2. Зүүн талаас **AI News Bot** → **Run workflow** → **Run workflow**.
3. 1–2 минутын дараа:
   - Telegram group-д `Bot started, tracking 22 sources` гэж ирнэ.
   - Repo-д `github-actions[bot]`-ийн `chore: update seen.json` commit гарч ирнэ.
4. Үүнээс хойш 30 минут тутам автоматаар ажиллаж, зөвхөн шинэ мэдээг илгээнэ.

> GitHub-ийн `schedule` нь ачааллаас шалтгаалж 5–20 минут хоцрох нь энгийн үзэгдэл.
> Public repo-д 60 хоног ямар ч үйл ажиллагаа (commit гэх мэт) байхгүй бол GitHub scheduled workflow-г автоматаар унтраадаг. Тийм болбол Actions табаас дахин **Enable** хийнэ.

### 6. Эх сурвалж нэмэх

`sources.yaml`-д шинэ бичлэг нэмнэ:

```yaml
  - name: My New Source            # давхардахгүй нэр, мессежид тод харагдана
    url: https://example.com/feed.xml
    type: rss                      # rss | atom | github_release | google_news
    category: OpenSource           # -> #OpenSource hashtag
    keywords: [AI, LLM, agent]     # сонголттой: гарчиг/товчлолд эдгээрийн аль нэг байвал л илгээнэ
    summary: true                  # сонголттой: товчлол харуулах эсэх
    enabled: true                  # сонголттой: false бол түр унтраана
```

Түгээмэл загварууд:

- **GitHub release:** `https://github.com/<owner>/<repo>/releases.atom`
- **Албан ёсны RSS байхгүй компани (Google News):**
  `https://news.google.com/rss/search?q=<QUERY>&hl=en-US&gl=US&ceid=US:en`
  - Хоосон зайг `+`, хашилтыг `%22` гэж бичнэ: `q=%22Mistral+AI%22`
  - Сүүлийн 1 хоногоор хязгаарлах: `q=DeepSeek+when:1d`
- **Hacker News:** `https://hnrss.org/newest?points=100` (+ `keywords` заавал)

`keywords` нь том жижиг үсэг ялгахгүй, **бүтэн үгээр** таарна (жишээ нь `AI` нь "said"-тэй таарахгүй, `model` нь "models"-тэй таарна).

Шинэ эх сурвалж нэмсний дараа:
```bash
python main.py --dry-run
```
ажиллуулж log-д `[My New Source] N entries ...` гарч байгаа эсэхийг шалгаад commit + push хийнэ. Шинэ эх сурвалжийн одоо байгаа мэдээ илгээгдэхгүй, зөвхөн дараа нь гарах шинэ мэдээ ирнэ.

### 7. Локал дээр `--dry-run`-аар тестлэх

```bash
cd ai-news-bot
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

python main.py --dry-run
```

`--dry-run` нь Telegram руу илгээхгүй, мессежүүдийг консол руу хэвлэнэ, `seen.json`-г **өөрчлөхгүй**. Token шаардлагагүй.

- `seen.json` хоосон үед зөвхөн `Bot started, tracking N sources` хэвлэнэ (анхны ажиллалтын горим).
- GitHub дээр бот ажиллаж эхэлсний дараа `git pull` хийгээд `--dry-run` ажиллуулбал дараагийн ажиллалтаар юу илгээгдэхийг харна.
- Өөр state файлаар туршиж болно: `python main.py --dry-run --state /tmp/test-seen.json`

Жинхэнээр локалаас илгээх (ховор хэрэг болно — GitHub дээрх `seen.json`-той зөрчилдөж болзошгүй):
```bash
export TELEGRAM_BOT_TOKEN="123456789:AA..."
export TELEGRAM_CHAT_ID="-1001234567890"
python main.py
```

---

## Эх сурвалжийн төлөв (2026-10-08-нд шалгасан)

Бүх URL-ийг Python (`requests` + `feedparser`, 15 секундийн timeout, энгийн User-Agent)-ээр шалгасан.

### ✅ Ажиллаж байгаа (sources.yaml-д орсон)

| Нэр | URL | Тэмдэглэл |
|---|---|---|
| OpenAI News | `https://openai.com/news/rss.xml` | |
| Google DeepMind | `https://deepmind.google/blog/rss.xml` | |
| Google AI Blog | `https://blog.google/technology/ai/rss/` | Gemini мэдээ эндээс |
| Google Developers Blog | `https://developers.googleblog.com/feeds/posts/default` | Огноо байхгүй feed — анх харсан цагаар нь тооцно |
| Anthropic (Google News) | `news.google.com/rss/search?q=Anthropic+Claude` | |
| Hugging Face Blog | `https://huggingface.co/blog/feed.xml` | |
| Meta AI (Google News) | `news.google.com/rss/search?q="Meta AI" OR "Llama model"` | |
| Mistral AI (Google News) | `news.google.com/rss/search?q="Mistral AI"` | |
| xAI (Google News) | `news.google.com/rss/search?q=xAI+Grok` | |
| DeepSeek (Google News) | `news.google.com/rss/search?q=DeepSeek` | |
| Qwen (Google News) | `news.google.com/rss/search?q=Qwen+Alibaba` | |
| Microsoft Official Blog | `https://blogs.microsoft.com/feed/` | AI/Copilot/Azure keyword шүүлттэй |
| Microsoft Foundry Blog (Azure AI) | `https://devblogs.microsoft.com/foundry/feed/` | |
| GitHub Changelog | `https://github.blog/changelog/feed/` | AI/Copilot keyword шүүлттэй |
| GitHub Blog | `https://github.blog/feed/` | AI/Copilot keyword шүүлттэй |
| ollama/ollama | `github.com/ollama/ollama/releases.atom` | |
| ggml-org/llama.cpp | `github.com/ggml-org/llama.cpp/releases.atom` | ⚠️ Өдөрт 10+ build release — их шуугиантай. Хэрэггүй бол `enabled: false` |
| vllm-project/vllm | `github.com/vllm-project/vllm/releases.atom` | |
| huggingface/transformers | `github.com/huggingface/transformers/releases.atom` | |
| anthropics/claude-code | `github.com/anthropics/claude-code/releases.atom` | |
| openai/openai-python | `github.com/openai/openai-python/releases.atom` | |
| Hacker News | `https://hnrss.org/newest?points=100` | Keyword шүүлттэй. Заримдаа түр `connection reset` өгдөг — дараагийн ажиллалтаар нөхөгдөнө |

### ❌ Эвдэрсэн / байхгүй (Google News-ээр орлуулсан)

| Эх сурвалж | Шалгасан URL | Үр дүн | Орлуулсан |
|---|---|---|---|
| Anthropic | `https://www.anthropic.com/news/rss.xml` | 404 — албан ёсны RSS байхгүй | Google News |
| Meta AI | `https://ai.meta.com/blog/rss/` | 400 — bot хамгаалалттай, RSS байхгүй | Google News |
| Mistral AI | `https://mistral.ai/news/rss.xml` | 404 | Google News |
| xAI | `https://x.ai/news/rss.xml` | 404 | Google News |
| DeepSeek | `https://api-docs.deepseek.com/news/rss.xml` | 200 боловч хоосон | Google News |
| Qwen | `https://qwenlm.github.io/blog/index.xml` | Ажилладаг боловч 2025-09-өөс хойш шинэчлэгдээгүй | Google News |
| Microsoft AI Blog | `https://blogs.microsoft.com/ai/feed/` | 410 Gone | Microsoft Official Blog + Foundry Blog |
| Microsoft Copilot Blog | `https://www.microsoft.com/en-us/microsoft-copilot/blog/feed/` | 200 боловч хоосон | — |

> **Google News-ийн тухай:** query-д таарсан бүх хэвлэлийн мэдээг авчирдаг тул өдөрт хэдэн арван мессеж болж магадгүй. Хэт олон байвал query-г нарийсгах (`q=%22Anthropic%22+Claude+when:1d`), `keywords` нэмэх, эсвэл `enabled: false` болгоно уу. Мөн Google News-ийн линк нь `news.google.com/rss/articles/...` redirect хэлбэртэй тул албан ёсны блогийн ижил мэдээтэй давхардлыг таньж чадахгүй.

## Алдаа засах

| Шинж тэмдэг | Шалтгаан / шийдэл |
|---|---|
| Workflow `TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set` | Secrets нэмээгүй эсвэл нэрийг буруу бичсэн |
| `Telegram error, stopping: HTTP 401` | Token буруу |
| `HTTP 400: Bad Request: chat not found` / `403` | chat_id буруу, эсвэл бот group-оос хасагдсан |
| Push дээр `403` | Settings → Actions → General → Workflow permissions → Read and write |
| Анхны мессежийг дахин авахыг хүсвэл | `state/seen.json`-г `{}` болгож commit хийгээд workflow-г ажиллуулна |
| Нэг эх сурвалж байнга `fetch failed` | URL-ийг `curl -I <url>`-ээр шалгаад солих эсвэл `enabled: false` |
