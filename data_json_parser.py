"""
Parser for stockanalysis.com SvelteKit __data.json endpoints.

The site uses SvelteKit's "devalue" serialization format to encode page data:
- All values are stored in a flat `data` array
- Dicts and arrays in the flat store contain integer indices (not actual values)
- Index -1 is a universal null sentinel
- Recursively dereferencing indices produces the actual structured data

Response structure:
  { "type": "data", "nodes": [node0, node1, node2] }
  - node[0]: session / user info (usually skipped)
  - node[1]: stock or ETF info (quote, metadata)
  - node[2]: page-specific data (financials, holdings, market movers, etc.)
"""

from __future__ import annotations
from typing import Any


# ---------------------------------------------------------------------------
# Core devalue deref
# ---------------------------------------------------------------------------

def deref(idx: Any, data: list, _depth: int = 0) -> Any:
    """Recursively expand a devalue-encoded index from the flat data array."""
    if _depth > 30:
        return "...(max depth)"

    # If not an integer index, it's already a primitive value
    if not isinstance(idx, int):
        return idx
    if idx == -1 or idx < 0:
        return None
    if idx >= len(data):
        return None

    v = data[idx]

    if isinstance(v, dict):
        return {k: deref(vi, data, _depth + 1) for k, vi in v.items()}
    if isinstance(v, list):
        return [deref(i, data, _depth + 1) for i in v]
    # Primitive: str, int, float, bool, None
    return v


def parse_node(node: dict) -> dict | None:
    """Parse a single SvelteKit data node into a plain Python dict."""
    if node.get("type") == "skip":
        return None
    data = node.get("data", [])
    if not data:
        return None
    # data[0] is always the schema dict
    return deref(0, data)


# ---------------------------------------------------------------------------
# High-level parsers per page type
# ---------------------------------------------------------------------------

def parse_financial_table(node_data: dict) -> dict:
    """
    Extract a financial statement into a column-oriented table.

    Returns:
        {
            "statement":  "income-statement" | "balance-sheet" | ...,
            "period":     "annual" | "quarterly",
            "heading":    "Income Statement",
            "source":     "spg",
            "columns":    ["TTM", "2025-09-27", "2024-09-28", ...],
            "rows": {
                "revenue":          [8618000, 9912000, ...],
                "grossMargin":      [0.453, 0.505, ...],
                ...
            },
            "map":  [{"id": "revenue", "title": "Revenue", ...}, ...]
        }
    """
    fd = node_data.get("financialData", {})
    if not fd:
        return node_data

    # datekey column gives the period labels
    columns = fd.get("datekey", [])

    rows = {}
    for field, values in fd.items():
        if field in ("datekey", "fiscalYear", "fiscalQuarter"):
            continue
        if isinstance(values, list):
            rows[field] = values
        elif values is not None:
            rows[field] = values

    details = node_data.get("details", {}) or {}

    return {
        "statement":  node_data.get("statement"),
        "period":     node_data.get("period"),
        "heading":    node_data.get("heading"),
        "url":        node_data.get("url"),
        "source":     details.get("source"),
        "fiscal_year": details.get("fiscalYear"),
        "columns":    columns,
        "rows":       rows,
        "map":        node_data.get("map", []),
    }


def parse_stock_info(node_data: dict) -> dict:
    """Extract stock/ETF metadata and real-time quote from the info node."""
    info = node_data.get("info", {}) or {}
    quote_raw = info.get("quote", {}) or {}

    # Map terse quote keys to readable names
    QUOTE_KEY_MAP = {
        "p":   "price",
        "pd":  "prev_close",
        "c":   "change",
        "cp":  "change_pct",
        "cl":  "close",
        "o":   "open",
        "h":   "high",
        "l":   "low",
        "v":   "volume",
        "h52": "high_52w",
        "l52": "low_52w",
        "ms":  "market_status",
        "fms": "extended_session",
        "ep":  "ext_price",
        "ec":  "ext_change",
        "ecp": "ext_change_pct",
        "es":  "ext_session_label",
        "ex":  "exchange",
        "td":  "trade_date",
        "ts":  "trade_timestamp_ms",
    }

    quote = {QUOTE_KEY_MAP.get(k, k): v for k, v in quote_raw.items()}

    return {
        "ticker":   info.get("ticker"),
        "symbol":   info.get("symbol"),
        "name":     info.get("name"),
        "type":     info.get("type"),
        "subtype":  info.get("subtype"),
        "exchange": info.get("exchange"),
        "currency": info.get("curr"),
        "quote":    quote,
    }


def parse_market_movers(node_data: dict) -> dict:
    """
    Extract market movers (gainers / losers / active / premarket / afterhours).

    Returns:
        {
            "query":   { sort, order, ... },
            "count":   int,
            "columns": [...],
            "rows":    [[val, val, ...], ...]
        }
    """
    raw_data = node_data.get("data", [])
    data_points = node_data.get("dataPoints", [])

    column_ids = node_data.get("dataPointIds", [])
    column_meta = {dp.get("id"): dp for dp in data_points if isinstance(dp, dict)}

    return {
        "query":        node_data.get("query", {}),
        "results_count": node_data.get("resultsCount"),
        "column_ids":   column_ids,
        "column_meta":  column_meta,
        "rows":         raw_data,
    }


def parse_etf_holdings(node_data: dict) -> dict:
    """Extract ETF holdings table."""
    return {
        "holdings":          node_data.get("holdings", []),
        "asset_allocation":  node_data.get("asset_allocation", {}),
        "sectors":           node_data.get("sectors", []),
        "countries":         node_data.get("countries", []),
    }


def parse_ipos(node_data: dict) -> dict:
    """Extract IPO listings (calendar / recent / screener)."""
    return {
        "ipos":     node_data.get("ipos") or node_data.get("data", []),
        "upcoming": node_data.get("upcoming", []),
        "recent":   node_data.get("recent", []),
    }


# ---------------------------------------------------------------------------
# Auto-detect and dispatch
# ---------------------------------------------------------------------------

_FINANCIAL_STATEMENTS = {
    "income-statement", "balance-sheet", "cash-flow-statement", "ratios"
}

def parse_page(response: dict) -> dict:
    """
    Top-level parser. Auto-detects page type from the __data.json response
    and returns structured data.

    Returns a dict with:
        type:    detected page type string
        info:    stock/ETF metadata (if present)
        data:    page-specific parsed content
    """
    nodes = response.get("nodes", [])

    parsed_nodes = [parse_node(n) for n in nodes]

    # The LAST non-null node is always the page-specific content.
    # If the second-to-last non-null node has "info", it's the stock/ETF info.
    non_null = [nd for nd in parsed_nodes[1:] if nd is not None]
    page_node = non_null[-1] if non_null else None
    info_node = non_null[-2] if len(non_null) >= 2 and "info" in non_null[-2] else None

    result: dict[str, Any] = {}

    # Parse info node
    if info_node:
        result["info"] = parse_stock_info(info_node)

    if page_node is None:
        result["type"] = "unknown"
        result["data"] = None
        return result

    # Detect page type and parse accordingly
    statement = page_node.get("statement")
    if statement in _FINANCIAL_STATEMENTS:
        result["type"] = f"financials/{statement}"
        result["data"] = parse_financial_table(page_node)

    elif "holdings" in page_node:
        result["type"] = "etf/holdings"
        result["data"] = parse_etf_holdings(page_node)

    elif "data" in page_node and "dataPoints" in page_node:
        result["type"] = "markets/movers"
        result["data"] = parse_market_movers(page_node)

    elif any(k in page_node for k in ("ipos", "upcoming", "thisWeekData", "nextWeekData")):
        result["type"] = "ipos"
        result["data"] = parse_ipos(page_node)

    elif "count" in page_node and "dataPoints" in page_node:
        result["type"] = "screener"
        result["data"] = page_node  # raw; screener shape varies significantly

    else:
        result["type"] = "page"
        result["data"] = page_node

    return result


# ---------------------------------------------------------------------------
# Convenience: fetch and parse from an authenticated Playwright page
# ---------------------------------------------------------------------------

async def fetch_and_parse(playwright_page, path: str) -> dict:
    """
    Fetch a __data.json URL from inside an authenticated Playwright browser
    context and return the parsed result.

    Usage:
        result = await fetch_and_parse(page, "/stocks/aapl/financials/")
        table  = result["data"]   # financial table
        info   = result["info"]   # stock metadata + quote
    """
    base = "https://stockanalysis.com"
    url = base + path.rstrip("/") + "/__data.json?x-sveltekit-trailing-slash=1"

    raw = await playwright_page.evaluate(f"""
        async () => {{
            const r = await fetch('{url}', {{
                credentials: 'include',
                headers: {{ 'Accept': 'application/json' }}
            }});
            if (!r.ok) return null;
            return await r.json();
        }}
    """)

    if not raw:
        return {{"type": "error", "status": None}}

    return parse_page(raw)


# ---------------------------------------------------------------------------
# CLI demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import asyncio, json, sys

    async def demo():
        from playwright.async_api import async_playwright
        from cookie_parser import parse_cookies, get_user_agent

        path = sys.argv[1] if len(sys.argv) > 1 else "/stocks/aapl/financials/"
        print(f"Fetching: {path}\n")

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            ctx = await browser.new_context(user_agent=get_user_agent())
            await ctx.add_cookies(parse_cookies())
            page = await ctx.new_page()
            await page.goto("https://stockanalysis.com/", wait_until="domcontentloaded", timeout=20000)

            result = await fetch_and_parse(page, path)
            await browser.close()

        page_type = result.get("type")
        print(f"Page type: {page_type}")

        if "info" in result:
            info = result["info"]
            q = info.get("quote", {})
            print(f"Symbol:   {info.get('ticker')} — {info.get('name')}")
            print(f"Price:    {q.get('price')}  ({q.get('change_pct'):+.2f}%)" if q.get("change_pct") else "")

        data = result.get("data", {})
        if page_type and "financials" in page_type:
            print(f"\nStatement: {data.get('heading')}  [{data.get('period')}]")
            print(f"Columns:   {data.get('columns')}")
            print(f"\nFirst 5 metrics:")
            for field, values in list(data.get("rows", {}).items())[:5]:
                print(f"  {field:30s} {values}")
        elif page_type == "markets/movers":
            print(f"\nResults: {data.get('results_count')}")
            print(f"Columns: {data.get('column_ids')}")
        elif page_type == "etf/holdings":
            holdings = data.get("holdings", [])
            print(f"\nHoldings count: {len(holdings)}")
            print(f"First 3: {holdings[:3]}")
        else:
            keys = list(data.keys()) if isinstance(data, dict) else type(data).__name__
            print(f"\nData keys: {keys}")

    asyncio.run(demo())
