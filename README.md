# stockanalysis-api-crawler

> 🇨🇳 [中文文档](README_CN.md)

Discover and document the internal REST API endpoints of [stockanalysis.com](https://stockanalysis.com) by simulating an authenticated browser session with Playwright.

## Background

stockanalysis.com is a SvelteKit SPA. Most page data is served via server-side rendering (SSR) and SvelteKit's `__data.json` mechanism — not traditional REST calls. This crawler identifies the small set of real `/api/` endpoints that the frontend actively fetches at runtime (price quotes, history charts, market mini-charts, search).

## Discovered Endpoints

See [`output/api_docs.md`](output/api_docs.md) for the full documented API reference.

| Endpoint | Description |
|---|---|
| `GET /api/search?q={query}` | Global search — stocks, ETFs, international symbols |
| `GET /api/quotes/s/{ticker}` | Real-time stock quote |
| `GET /api/quotes/e/{ticker}` | Real-time ETF quote |
| `GET /api/symbol/s/{ticker}/history?type=chart\|annual\|quarterly` | Stock price history |
| `GET /api/symbol/e/{ticker}/history?type=chart` | ETF price history |
| `GET /api/mc/pre?c=1` | Pre-market mini chart (SPY) |
| `GET /api/mc/post?c=1` | After-hours mini chart (SPY) |
| `GET /api/mc/1d?c=1` | Regular-hours mini chart (SPY) |

## How It Works

```
a.sh  →  cookie_parser.py  →  crawler.py  →  normalizer.py  →  generate_docs.py
                                  ↓
                          output/raw_requests.json
                          output/normalized.json
                          output/api_docs.md
```

1. **`cookie_parser.py`** — Parses the `-b '...'` cookie string from a `curl` command exported from browser DevTools.
2. **`crawler.py`** — Launches headless Chromium via Playwright, injects cookies, then runs three phases:
   - **Phase 1**: Full page loads — captures XHR/fetch calls made by the browser automatically (`/api/quotes/`, `/api/mc/`, auth endpoints).
   - **Phase 2**: Fetches `__data.json` for every route from inside the authenticated browser context — discovers SvelteKit data endpoints.
   - **Phase 3**: Directly probes known `/api/` URL patterns.
3. **`normalizer.py`** — Filters to `stockanalysis.com/api/*` only, replaces dynamic path segments (`{ticker}`, `{id}`) with placeholders, deduplicates.
4. **`generate_docs.py`** — Renders `output/api_docs.md` from normalized data.
5. **`run.py`** — Orchestrates all four steps in sequence.

## Setup

**Requirements:** Python 3.12+

```bash
# 1. Clone the repo
git clone https://github.com/YOUR_USERNAME/stockanalysis-api-crawler.git
cd stockanalysis-api-crawler

# 2. Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt
playwright install chromium

# 4. Add your login cookies
#    - Open stockanalysis.com in Chrome and log in
#    - Open DevTools (F12) → Network tab
#    - Refresh the page
#    - Find the first request to stockanalysis.com (the main page request)
#    - Right-click → "Copy as cURL"
#    - Paste the entire curl command into a.sh
cp a.sh.example a.sh
# paste your copied curl command into a.sh (the crawler extracts cookies and User-Agent from it)

# 5. Run
python run.py
```

Output files are written to `output/`:

| File | Description |
|---|---|
| `raw_requests.json` | All captured network requests (gitignored — can be 15MB+) |
| `normalized.json` | Deduplicated endpoint patterns (gitignored) |
| `api_docs.md` | Human-readable API reference ✅ |

## Re-running / Updating Docs

If you already have `output/raw_requests.json` and only want to re-normalize or reformat the docs:

```bash
python normalizer.py          # regenerate normalized.json from raw_requests.json
python generate_docs.py       # regenerate api_docs.md from normalized.json
```

## Notes

- The crawler runs for ~3 minutes (headless Chromium loading ~40 pages).
- Session cookies expire. If you get 401/403 responses, export fresh cookies from your browser.
- The screener (`/stocks/screener/`, `/etf/screener/`) and all financial statement pages serve data through SvelteKit SSR — no separate `/api/` endpoint exists for them.

## License

MIT
