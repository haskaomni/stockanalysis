"""Normalize and deduplicate captured API URLs into unique patterns."""

import json
import re
from pathlib import Path
from urllib.parse import urlparse, parse_qs, urlunparse


def is_stockanalysis_api(url: str) -> bool:
    """Only keep stockanalysis.com/api/* endpoints."""
    return url.startswith("https://stockanalysis.com/api/")


def normalize_url(url: str) -> tuple[str, dict]:
    """Normalize URL — replace dynamic segments with placeholders."""
    parsed = urlparse(url)
    path = parsed.path
    query = parsed.query

    # Replace lowercase ticker segments (e.g. /s/aapl -> /s/{ticker})
    # Pattern: /s/{1-6 lowercase letters} or /e/{1-6 lowercase letters}
    path = re.sub(r"(/[se]/)([a-z]{1,6})(?=/|$)", r"\1{ticker}", path)

    # Replace numeric IDs
    path = re.sub(r"/(\d+)(?=/|$)", r"/{id}", path)

    # Parse query params
    query_params = {}
    if query:
        for key, values in parse_qs(query, keep_blank_values=True).items():
            query_params[key] = values[0] if values else ""

    # Normalized query: keys sorted, values kept as examples
    norm_query_parts = sorted(query_params.keys())
    norm_parsed = parsed._replace(
        path=path,
        query="&".join(f"{k}=" for k in norm_query_parts),
        fragment="",
    )
    return urlunparse(norm_parsed), query_params


def infer_category(path: str) -> str:
    """Infer API category from path."""
    p = path.lower()
    if "/api/mc/" in p:
        return "Markets - Mini Charts"
    if "/api/quotes/s/" in p:
        return "Stocks - Real-time Quotes"
    if "/api/quotes/e/" in p:
        return "ETFs - Real-time Quotes"
    if "/api/symbol/s/" in p and "/history" in p:
        return "Stocks - Price History"
    if "/api/symbol/e/" in p and "/history" in p:
        return "ETFs - Price History"
    if "/api/screener/s" in p:
        return "Screener - Stocks"
    if "/api/screener/etf" in p:
        return "Screener - ETFs"
    if "/api/" in p:
        return "Other"
    return "Other"


def normalize_all(raw_path: str = "output/raw_requests.json",
                  output_path: str = "output/normalized.json") -> list:
    """Filter to /api/ only, normalize, deduplicate."""
    with open(raw_path) as f:
        raw = json.load(f)

    print(f"Loaded {len(raw)} raw requests")

    api_only = [e for e in raw if is_stockanalysis_api(e.get("url", ""))]
    print(f"After /api/ filter: {len(api_only)} endpoints")

    seen = {}
    for entry in api_only:
        url = entry.get("url", "")
        method = entry.get("method", "GET")
        status = entry.get("status")

        # Skip 404s unless it's the only entry for that pattern
        normalized, query_params = normalize_url(url)
        key = (method, normalized)

        if key not in seen:
            path = urlparse(normalized).path
            seen[key] = {
                "method": method,
                "normalized_url": normalized,
                "example_url": url,
                "query_params": query_params,
                "status": status,
                "post_data": entry.get("post_data"),
                "category": infer_category(path),
                "response_preview": entry.get("response_preview"),
                "occurrences": 1,
            }
        else:
            seen[key]["occurrences"] += 1
            # Prefer successful responses
            if seen[key].get("status") != 200 and status == 200:
                seen[key]["status"] = status
                seen[key]["example_url"] = url
                seen[key]["query_params"] = query_params
                seen[key]["response_preview"] = entry.get("response_preview")
            elif seen[key]["response_preview"] is None and entry.get("response_preview"):
                seen[key]["response_preview"] = entry.get("response_preview")
            # Union of query params — accumulate all observed values
            for k, v in query_params.items():
                existing = seen[key]["query_params"].get(k, "")
                if v and v not in existing:
                    seen[key]["query_params"][k] = (existing + " | " + v).strip(" | ") if existing else v

    # Drop endpoints that only ever returned errors
    result = [v for v in seen.values() if v.get("status") != 404]
    result = sorted(result, key=lambda x: (x["category"], x["normalized_url"]))

    with open(output_path, "w") as f:
        json.dump(result, f, indent=2, default=str)

    print(f"Normalized to {len(result)} unique endpoints → {output_path}")
    return result


if __name__ == "__main__":
    results = normalize_all()
    categories = {}
    for r in results:
        cat = r["category"]
        categories[cat] = categories.get(cat, 0) + 1
    print("\nEndpoints by category:")
    for cat, count in sorted(categories.items()):
        print(f"  {cat}: {count}")
