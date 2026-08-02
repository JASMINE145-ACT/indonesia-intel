"""Inspect one Google News RSS item fields for URL unwrapping."""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET

import httpx

URL = "https://news.google.com/rss/search?q=site:kompas.com+when:30d&hl=id&gl=ID&ceid=ID:id"


def main() -> None:
    r = httpx.get(
        URL,
        timeout=25.0,
        follow_redirects=True,
        headers={"User-Agent": "Mozilla/5.0"},
    )
    root = ET.fromstring(r.content)
    item = root.find(".//item")
    assert item is not None
    for child in item:
        tag = child.tag
        text = (child.text or "")[:300]
        href = child.get("href")
        print(f"TAG={tag} href={href} text={text!r}")
    desc = item.findtext("description") or ""
    hrefs = re.findall(r'href="(https?://[^"]+)"', desc)
    print("DESC_HREFS", hrefs[:5])
    # source tag
    source = item.find("source")
    if source is not None:
        print("SOURCE", source.get("url"), source.text)


if __name__ == "__main__":
    main()
