"""Parse cookies from the a.sh curl command for use with Playwright."""

import re
from pathlib import Path


def parse_cookies(sh_file: str = "a.sh") -> list[dict]:
    """Extract cookies from curl -b '...' in a.sh and return Playwright cookie dicts."""
    content = Path(sh_file).read_text()

    # Extract the cookie string from -b '...'
    match = re.search(r"-b '([^']+)'", content)
    if not match:
        raise ValueError(f"No -b cookie string found in {sh_file}")

    cookie_string = match.group(1)

    cookies = []
    for pair in cookie_string.split("; "):
        if "=" not in pair:
            continue
        name, _, value = pair.partition("=")
        name = name.strip()
        value = value.strip()
        if name:
            cookies.append({
                "name": name,
                "value": value,
                "domain": ".stockanalysis.com",
                "path": "/",
            })

    return cookies


def get_user_agent(sh_file: str = "a.sh") -> str:
    """Extract the User-Agent header from a.sh."""
    content = Path(sh_file).read_text()
    match = re.search(r"-H 'user-agent: ([^']+)'", content)
    if match:
        return match.group(1)
    return "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36"


if __name__ == "__main__":
    cookies = parse_cookies()
    print(f"Parsed {len(cookies)} cookies:")
    for c in cookies:
        print(f"  {c['name']} = {c['value'][:40]}...")
    print(f"\nUser-Agent: {get_user_agent()}")
