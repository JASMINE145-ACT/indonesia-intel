"""Probe Detik listing HTML structure (live)."""
from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse

import httpx
from lxml import html as lxml_html

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

URL = "https://news.detik.com/berita"
UA = "Mozilla/5.0 (compatible; indonesia-intel-probe/0.1)"


def main() -> int:
    with httpx.Client(follow_redirects=True, timeout=30.0, headers={"User-Agent": UA}) as c:
        r = c.get(URL)
        r.raise_for_status()
        raw = r.content
    Path(r"d:\demo1\.agent-test\evidence\detik-berita-probe.html").write_bytes(raw)
    doc = lxml_html.fromstring(raw)

    selectors = [
        "article",
        "div.list-content__item",
        "li",
        "article.list-content__item",
        "div.media__image",
        "h3.media__title a",
        "h2.media__title a",
        "a[href*='/berita/']",
        "div.list-content article",
        "article a[dtr-sec]",
    ]
    report = {"status": r.status_code, "bytes": len(raw), "selectors": {}}
    for sel in selectors:
        try:
            els = doc.cssselect(sel)
        except Exception as exc:  # noqa: BLE001
            report["selectors"][sel] = {"error": str(exc)}
            continue
        hrefs = []
        for el in els[:30]:
            if el.tag == "a":
                hrefs.append(el.get("href") or "")
            else:
                for a in el.cssselect("a")[:3]:
                    hrefs.append(a.get("href") or "")
        report["selectors"][sel] = {"count": len(els), "sample_hrefs": hrefs[:8]}

    # All same-host links with /berita/ or numeric id pattern
    all_a = doc.cssselect("a[href]")
    paths = []
    for a in all_a:
        href = (a.get("href") or "").strip()
        if "detik.com" not in href and not href.startswith("/"):
            continue
        paths.append(href)
    # classify
    classes = Counter()
    articleish = []
    for href in paths:
        p = urlparse(href if href.startswith("http") else "https://news.detik.com" + href).path
        if re.search(r"/\d{5,}", p) or re.search(r"/berita/d-\d+", p):
            classes["article_id"] += 1
            articleish.append(href)
        elif "/berita" in p and p.rstrip("/") in {"/berita", "/berita/"}:
            classes["berita_index"] += 1
        elif any(x in p for x in ("/tag/", "/topic/", "/foto", "/video", "/20detik", "/connect")):
            classes["nav_channel"] += 1
        else:
            classes["other"] += 1
    report["link_classes"] = dict(classes)
    report["articleish_sample"] = articleish[:15]

    # media__title links specifically
    titles = []
    for a in doc.cssselect("h3.media__title a, h2.media__title a, .media__title a"):
        titles.append({"href": a.get("href"), "text": (a.text_content() or "").strip()[:80]})
    report["media_title_links"] = titles[:20]

    out = Path(r"d:\demo1\.agent-test\evidence\detik-listing-probe.json")
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print("wrote", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
