"""Probe Bisnis.com for sitemap/listing discovery candidates."""
from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx
from lxml import html as lxml_html

UA = {"User-Agent": "Mozilla/5.0 (compatible; indonesia-intel-probe/0.1)"}
OUT = Path(__file__).resolve().parents[1] / "evidence" / "bisnis-probe-20260801.json"


def main() -> int:
    report: dict = {"candidates": {}, "errors": []}
    with httpx.Client(follow_redirects=True, timeout=30.0, headers=UA) as c:
        for label, url in [
            ("home", "https://www.bisnis.com/"),
            ("sitemap", "https://www.bisnis.com/sitemap.xml"),
            ("sitemap_index", "https://www.bisnis.com/sitemap_index.xml"),
            ("robots", "https://www.bisnis.com/robots.txt"),
        ]:
            try:
                r = c.get(url)
                report["candidates"][label] = {
                    "url": url,
                    "status": r.status_code,
                    "ctype": r.headers.get("content-type", ""),
                    "bytes": len(r.content),
                    "snippet": r.text[:400].replace("\n", " "),
                }
            except Exception as exc:  # noqa: BLE001
                report["errors"].append(f"{label}: {exc}")

        # Try common listing pages
        for path in ("/", "/market", "/ekonomi", "/industri", "/finansial"):
            url = urljoin("https://www.bisnis.com/", path)
            try:
                r = c.get(url)
                if r.status_code != 200:
                    report["candidates"][f"list:{path}"] = {"status": r.status_code}
                    continue
                doc = lxml_html.fromstring(r.content)
                sels = {
                    "article": len(doc.cssselect("article")),
                    "h3 a": len(doc.cssselect("h3 a")),
                    "a[href*='/read/']": len(doc.cssselect("a[href*='/read/']")),
                    "a[href*='/ekonomi/']": len(doc.cssselect("a[href*='/ekonomi/']")),
                }
                sample = []
                for a in doc.cssselect("a[href]")[:200]:
                    href = (a.get("href") or "").strip()
                    if not href:
                        continue
                    absu = urljoin(url, href)
                    if "bisnis.com" not in absu:
                        continue
                    p = urlparse(absu).path
                    if re.search(r"/\d{5,}", p) or "/read/" in p:
                        sample.append(absu)
                        if len(sample) >= 8:
                            break
                report["candidates"][f"list:{path}"] = {
                    "status": 200,
                    "selectors": sels,
                    "articleish_sample": sample,
                }
            except Exception as exc:  # noqa: BLE001
                report["errors"].append(f"list:{path}: {exc}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print("wrote", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
