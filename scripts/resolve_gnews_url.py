"""Try resolve Google News article wrapper to publisher URL."""
from __future__ import annotations

import httpx

URL = (
    "https://news.google.com/rss/articles/"
    "CBMiwwFBVV95cUxNdkxMeGhEaS1udzdJV2h5Q1BJRlNzTnNQUnJJSHJvUXF1WVNhQmlrdGtSZUdRT1dJbWExdWdSTnl3QzJzM1pnSE5CWmY5ZTBDanhhc3o2MTFXMS1BaXVEOGZNMkdrSUdxdXoxTmVCNFdocmxmVW5GeW8tZnlrRGVYZDR4QzlRZDREcjIyeU9ncTY4MmlyVVIwaXpGWHNpeEl2NkduNlhMWXdmMW41OGdrdXh0TFpvcmpNZEZidXJYbXJwQ3M"
)


def main() -> None:
    with httpx.Client(timeout=25.0, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0"}) as c:
        r = c.get(URL)
        print("status", r.status_code)
        print("final", str(r.url)[:200])
        print("history", [str(h.url)[:120] for h in r.history])


if __name__ == "__main__":
    main()
