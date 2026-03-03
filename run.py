"""Entry point: run all steps sequentially to crawl and document stockanalysis.com APIs."""

import asyncio
import sys
import time
from pathlib import Path


def main():
    start = time.time()
    output_dir = "output"
    Path(output_dir).mkdir(exist_ok=True)

    print("=" * 60)
    print("stockanalysis.com API Crawler")
    print("=" * 60)

    # Step 1: Validate cookies
    print("\n[Step 1] Parsing cookies from a.sh...")
    try:
        from cookie_parser import parse_cookies, get_user_agent
        cookies = parse_cookies()
        ua = get_user_agent()
        print(f"  OK: {len(cookies)} cookies parsed")
        print(f"  User-Agent: {ua[:60]}...")
    except Exception as e:
        print(f"  ERROR: {e}")
        sys.exit(1)

    # Step 2: Crawl pages
    print("\n[Step 2] Crawling stockanalysis.com with Playwright...")
    try:
        from crawler import run_crawler
        captured = asyncio.run(run_crawler(output_dir))
        print(f"  OK: {len(captured)} API requests captured")
    except Exception as e:
        print(f"  ERROR during crawl: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    raw_path = Path(output_dir) / "raw_requests.json"
    if not raw_path.exists() or raw_path.stat().st_size == 0:
        print("  ERROR: No raw_requests.json produced")
        sys.exit(1)

    # Step 3: Normalize
    print("\n[Step 3] Normalizing and deduplicating endpoints...")
    try:
        from normalizer import normalize_all
        normalized = normalize_all(
            raw_path=str(raw_path),
            output_path=str(Path(output_dir) / "normalized.json"),
        )
        print(f"  OK: {len(normalized)} unique endpoint patterns")
    except Exception as e:
        print(f"  ERROR during normalization: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    # Step 4: Generate docs
    print("\n[Step 4] Generating API documentation...")
    try:
        from generate_docs import generate_docs
        generate_docs(
            normalized_path=str(Path(output_dir) / "normalized.json"),
            output_path=str(Path(output_dir) / "api_docs.md"),
        )
    except Exception as e:
        print(f"  ERROR during doc generation: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    elapsed = time.time() - start
    print(f"\n{'=' * 60}")
    print(f"Done in {elapsed:.1f}s")
    print(f"Output files:")
    for fname in ["raw_requests.json", "normalized.json", "api_docs.md"]:
        fpath = Path(output_dir) / fname
        if fpath.exists():
            size = fpath.stat().st_size
            print(f"  {fpath}  ({size:,} bytes)")
    print("=" * 60)


if __name__ == "__main__":
    main()
