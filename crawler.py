"""Playwright crawler for stockanalysis.com API endpoint discovery.

Strategy:
  Phase 1 - Full page loads: captures /api/quotes, /api/symbol/history,
            /api/mc/*, auth endpoints triggered on each page load.
  Phase 2 - In-browser fetch of __data.json: SvelteKit serves financial/ETF/
            market data via SSR (embedded in HTML, not XHR). We manually fetch
            the __data.json endpoints from the authenticated browser context
            to discover them.
"""

import asyncio
import json
import random
import time
from pathlib import Path

from playwright.async_api import async_playwright, Page, Response

from cookie_parser import parse_cookies, get_user_agent

BASE_URL = "https://stockanalysis.com"

# Phase 1: full page loads (captures real-time price/chart API calls)
FULL_LOAD_PAGES = [
    "/",
    "/stocks/aapl/",
    "/stocks/aapl/history/",
    "/etf/spy/",
    "/etf/spy/history/",
    "/markets/gainers/",
    "/ipos/",
    "/news/",
    "/watchlist/",
    "/stocks/screener/",
]

# Phase 2: fetch __data.json for all important pages from inside the browser
# (triggers SvelteKit's server-side data loader without SSR)
DATA_JSON_PATHS = [
    # Homepage
    "/__data.json?x-sveltekit-trailing-slash=1",
    # Stocks list
    "/stocks/__data.json?x-sveltekit-trailing-slash=1",
    # AAPL detail pages
    "/stocks/aapl/__data.json?x-sveltekit-trailing-slash=1",
    "/stocks/aapl/financials/__data.json?x-sveltekit-trailing-slash=1",
    "/stocks/aapl/financials/__data.json?x-sveltekit-trailing-slash=1&p=quarterly",
    "/stocks/aapl/financials/balance-sheet/__data.json?x-sveltekit-trailing-slash=1",
    "/stocks/aapl/financials/cash-flow-statement/__data.json?x-sveltekit-trailing-slash=1",
    "/stocks/aapl/financials/ratios/__data.json?x-sveltekit-trailing-slash=1",
    "/stocks/aapl/forecast/__data.json?x-sveltekit-trailing-slash=1",
    "/stocks/aapl/news/__data.json?x-sveltekit-trailing-slash=1",
    "/stocks/aapl/history/__data.json?x-sveltekit-trailing-slash=1",
    "/stocks/aapl/dividends/__data.json?x-sveltekit-trailing-slash=1",
    "/stocks/aapl/options/__data.json?x-sveltekit-trailing-slash=1",
    # ETF detail pages
    "/etf/spy/__data.json?x-sveltekit-trailing-slash=1",
    "/etf/spy/holdings/__data.json?x-sveltekit-trailing-slash=1",
    "/etf/spy/dividends/__data.json?x-sveltekit-trailing-slash=1",
    "/etf/spy/history/__data.json?x-sveltekit-trailing-slash=1",
    # IPO pages
    "/ipos/__data.json?x-sveltekit-trailing-slash=1",
    "/ipos/calendar/__data.json?x-sveltekit-trailing-slash=1",
    "/ipos/screener/__data.json?x-sveltekit-trailing-slash=1",
    "/ipos/statistics/__data.json?x-sveltekit-trailing-slash=1",
    # Markets
    "/markets/gainers/__data.json?x-sveltekit-trailing-slash=1",
    "/markets/losers/__data.json?x-sveltekit-trailing-slash=1",
    "/markets/active/__data.json?x-sveltekit-trailing-slash=1",
    "/markets/premarket/__data.json?x-sveltekit-trailing-slash=1",
    "/markets/afterhours/__data.json?x-sveltekit-trailing-slash=1",
    # Screener
    "/stocks/screener/__data.json?x-sveltekit-trailing-slash=1",
    "/etf/screener/__data.json?x-sveltekit-trailing-slash=1",
    # News / Trending
    "/news/__data.json?x-sveltekit-trailing-slash=1",
    "/trending/__data.json?x-sveltekit-trailing-slash=1",
    # Watchlist (login required)
    "/watchlist/__data.json?x-sveltekit-trailing-slash=1",
    # Analysts / Actions
    "/analysts/top-stocks/__data.json?x-sveltekit-trailing-slash=1",
    "/actions/__data.json?x-sveltekit-trailing-slash=1",
    # Lists
    "/list/exchanges/__data.json?x-sveltekit-trailing-slash=1",
]

# Only keep domains that belong to stockanalysis.com infrastructure
KEEP_DOMAINS = {
    "stockanalysis.com",
    "auth.stockanalysis.com",
}

# Resource types and URL fragments to skip during phase 1
SKIP_RESOURCE_TYPES = {"image", "stylesheet", "font", "media", "websocket", "other"}
SKIP_URL_FRAGMENTS = [
    "google-analytics", "posthog", "doubleclick", "googlesyndication",
    "_next/static", "_next/image", ".png", ".jpg", ".jpeg", ".svg",
    ".woff", ".woff2", ".ttf", ".ico", ".css", "analytics", "gtag",
    "hotjar", "sentry", "ingest.sentry",
]


def is_stockanalysis_domain(url: str) -> bool:
    return any(d in url for d in KEEP_DOMAINS)


def should_skip(url: str, resource_type: str) -> bool:
    if resource_type in SKIP_RESOURCE_TYPES:
        return True
    if any(frag in url for frag in SKIP_URL_FRAGMENTS):
        return True
    return False


async def random_delay(min_s: float = 0.3, max_s: float = 1.0):
    await asyncio.sleep(random.uniform(min_s, max_s))


async def scroll_page(page: Page):
    """Scroll down the page to trigger lazy-load content."""
    await page.evaluate("""
        async () => {
            await new Promise((resolve) => {
                let totalHeight = 0;
                const distance = 400;
                const timer = setInterval(() => {
                    window.scrollBy(0, distance);
                    totalHeight += distance;
                    if (totalHeight >= Math.min(document.body.scrollHeight, 2000)) {
                        clearInterval(timer);
                        resolve();
                    }
                }, 80);
            });
        }
    """)
    await asyncio.sleep(0.3)


def truncate_preview(body) -> object:
    """Truncate large response bodies to keep manageable previews."""
    if isinstance(body, dict):
        preview = {}
        for k, v in body.items():
            if isinstance(v, list) and len(v) > 5:
                preview[k] = v[:5] + [f"... ({len(v)} total items)"]
            elif isinstance(v, dict) and len(str(v)) > 600:
                preview[k] = dict(list(v.items())[:5])
            else:
                preview[k] = v
        return preview
    elif isinstance(body, list):
        return body[:5] + ([f"... ({len(body)} total items)"] if len(body) > 5 else [])
    return body


async def phase1_full_loads(page: Page, captured: list):
    """Phase 1: Full page loads to capture real-time API calls."""
    print("\n=== Phase 1: Full page loads ===")

    async def on_response(response: Response):
        req = response.request
        url = response.url
        resource_type = req.resource_type

        if should_skip(url, resource_type):
            return
        if resource_type not in ("xhr", "fetch"):
            return
        if not is_stockanalysis_domain(url):
            return

        try:
            body = await response.json()
            preview = truncate_preview(body)
        except Exception:
            preview = None

        try:
            post_data = req.post_data
        except Exception:
            post_data = None

        entry = {
            "url": url,
            "method": req.method,
            "resource_type": resource_type,
            "post_data": post_data,
            "status": response.status,
            "response_preview": preview,
            "captured_at": time.time(),
            "phase": 1,
        }
        captured.append(entry)
        print(f"  [P1] {req.method} {url[:90]}")

    page.on("response", on_response)

    for path in FULL_LOAD_PAGES:
        url = BASE_URL + path
        print(f"\n[Page] {path}")
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            try:
                await page.wait_for_load_state("networkidle", timeout=12000)
            except Exception:
                pass
            await scroll_page(page)
            await random_delay(0.5, 1.0)
        except Exception as e:
            print(f"  Error: {e}")
        await random_delay(0.8, 1.5)


async def phase2_data_json(page: Page, captured: list):
    """Phase 2: Fetch __data.json endpoints from within authenticated browser context."""
    print("\n\n=== Phase 2: Fetching __data.json endpoints ===")

    for data_path in DATA_JSON_PATHS:
        full_url = BASE_URL + data_path
        print(f"  [P2] GET {full_url[:90]}")

        try:
            result = await page.evaluate(f"""
                async () => {{
                    const r = await fetch('{full_url}', {{
                        credentials: 'include',
                        headers: {{ 'Accept': 'application/json' }}
                    }});
                    const status = r.status;
                    let body = null;
                    try {{ body = await r.json(); }} catch(e) {{}}
                    return {{ status, body }};
                }}
            """)

            if result and result.get("body"):
                preview = truncate_preview(result["body"])
                entry = {
                    "url": full_url,
                    "method": "GET",
                    "resource_type": "fetch",
                    "post_data": None,
                    "status": result.get("status", 200),
                    "response_preview": preview,
                    "captured_at": time.time(),
                    "phase": 2,
                }
                captured.append(entry)
                print(f"    → status={result.get('status')}")
            else:
                status = result.get("status") if result else "?"
                print(f"    → status={status} (no JSON body)")

        except Exception as e:
            print(f"    → Error: {e}")

        await random_delay(0.3, 0.6)


async def phase3_extra_api(page: Page, captured: list):
    """Phase 3: Directly fetch known API endpoint patterns."""
    print("\n\n=== Phase 3: Direct API endpoint probing ===")

    # Known API endpoint patterns to probe
    api_endpoints = [
        # Quotes
        "/api/quotes/s/aapl",
        "/api/quotes/s/tsla",
        "/api/quotes/s/msft",
        "/api/quotes/e/spy",
        "/api/quotes/e/qqq",
        # Symbol history
        "/api/symbol/s/aapl/history?type=chart",
        "/api/symbol/s/aapl/history?type=annual",
        "/api/symbol/s/aapl/history?type=quarterly",
        "/api/symbol/e/spy/history?type=chart",
        # Market clock
        "/api/mc/pre?c=1",
        "/api/mc/post?c=1",
        "/api/mc/1d?c=1",
        # Screener
        "/api/screener/s?m=marketCap&s=desc&ln=en&c=no,marketCap,lastClose,change1W&p=1&i=stocks",
        "/api/screener/etf?m=totalAssets&s=desc&ln=en&c=no,totalAssets,lastClose,volume&p=1",
    ]

    for api_path in api_endpoints:
        full_url = BASE_URL + api_path
        print(f"  [P3] GET {full_url[:90]}")

        try:
            result = await page.evaluate(f"""
                async () => {{
                    const r = await fetch('{full_url}', {{
                        credentials: 'include',
                        headers: {{
                            'Accept': 'application/json',
                            'Referer': 'https://stockanalysis.com/'
                        }}
                    }});
                    const status = r.status;
                    let body = null;
                    try {{ body = await r.json(); }} catch(e) {{}}
                    return {{ status, body }};
                }}
            """)

            if result:
                status = result.get("status", "?")
                body = result.get("body")
                if body:
                    preview = truncate_preview(body)
                    entry = {
                        "url": full_url,
                        "method": "GET",
                        "resource_type": "fetch",
                        "post_data": None,
                        "status": status,
                        "response_preview": preview,
                        "captured_at": time.time(),
                        "phase": 3,
                    }
                    captured.append(entry)
                    print(f"    → status={status} ✓")
                else:
                    print(f"    → status={status} (no JSON)")
        except Exception as e:
            print(f"    → Error: {e}")

        await random_delay(0.2, 0.5)


async def run_crawler(output_dir: str = "output") -> list:
    """Main crawler entry point."""
    Path(output_dir).mkdir(exist_ok=True)
    captured = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent=get_user_agent(),
            viewport={"width": 1280, "height": 900},
            ignore_https_errors=True,
        )

        cookies = parse_cookies()
        await context.add_cookies(cookies)
        print(f"Injected {len(cookies)} cookies")

        page = await context.new_page()

        # Phase 1: full page loads (network interception)
        await phase1_full_loads(page, captured)

        # Phase 2: fetch __data.json from authenticated browser
        await phase2_data_json(page, captured)

        # Phase 3: probe known API patterns
        await phase3_extra_api(page, captured)

        await browser.close()

    # Save raw results
    raw_path = Path(output_dir) / "raw_requests.json"
    with open(raw_path, "w") as f:
        json.dump(captured, f, indent=2, default=str)
    print(f"\nSaved {len(captured)} requests to {raw_path}")

    return captured


if __name__ == "__main__":
    results = asyncio.run(run_crawler())
    print(f"Total captured: {len(results)}")
