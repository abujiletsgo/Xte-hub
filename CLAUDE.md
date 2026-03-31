# XteSync - E-Reader Briefing System

FastAPI backend that ingests URLs (articles, YouTube, podcasts), summarizes them via Gemini, clusters related stories, and generates three-layer EPUB briefings optimized for Xteink e-readers.

## Stack

- **Backend:** Python 3.11+, FastAPI, uvicorn, aiosqlite
- **AI:** Google Gemini 2.0 Flash (via `google-genai`) for synthesis + editorial
- **Content:** readability-lxml, BeautifulSoup, yt-dlp, youtube-transcript-api
- **Output:** ebooklib EPUBs with e-ink-optimized CSS (480x800 Xteink X4)
- **Firmware:** CrossPoint C++ mod for chapter navigation via long-press buttons

## Structure

```
src/xtesync/           Python package (FastAPI app)
  main.py              App entry, routers, lifespan
  database.py          SQLite schema + async queries (items, clusters, sync_state, channels)
  models.py            Pydantic models, category icons/order
  routers/             API endpoints: items, briefings, channels, device
  services/            Business logic: content extraction, synthesis, editorial,
                       epub_builder, classifier, feed, news, sync
  static/              Frontend HTML
crosspoint/            Xteink firmware mod (C++ EpubReaderActivity)
simulator/             Browser-based e-reader simulator
data/                  SQLite DB + generated EPUB content
```

## Key Patterns

- `uv run` for all Python execution
- Entry point: `uv run uvicorn xtesync.main:app --reload` (port 8000)
- DB at `data/xtesync.db` -- auto-created on startup via `init_db()`
- Gemini API key via `GEMINI_API_KEY` env var
- Three-layer depth: Daily Briefing (headlines) -> In-Depth Summary -> Raw Reading
- 12 content categories with fixed order (korean_news through general)
- Items flow: pending -> extracting -> summarizing -> ready -> briefing EPUB

## API Endpoints

- `POST /api/items/url` -- submit URL for processing
- `POST /api/briefings/generate` -- generate daily EPUB briefing
- `GET /api/briefings/{date}/download` -- download EPUB file
- `GET /api/briefings/sync/pending` -- pending syncs for device

## Testing

```bash
uv run pytest                    # full suite
uv run pytest -x -q              # quick, stop on first failure
```

## Rules

- Never commit `data/xtesync.db` (user data)
- EPUB CSS must work on e-ink (no color, high contrast, serif fonts)
- Category order in `models.py CATEGORY_ORDER` is canonical -- match everywhere
- CrossPoint firmware changes require testing on actual Xteink device
