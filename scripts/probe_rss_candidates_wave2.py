"""Second-wave RSS probe: more media + Google News site: proxies."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from urllib.parse import quote_plus

import httpx

from jobs.poll_rss import parse_rss_items

CANDIDATES: list[tuple[str, str]] = [
    ("jakartapost", "https://www.thejakartapost.com/news.xml"),
    ("jakartapost2", "https://www.thejakartapost.com/rss"),
    ("tempo", "https://rss.tempo.co/"),
    ("tempo_en", "https://www.tempo.co/rss"),
    ("cnbc_id", "https://www.cnbcindonesia.com/rss"),
    ("cnn_id", "https://www.cnnindonesia.com/rss"),
    ("bbc_id", "https://feeds.bbci.co.uk/indonesia/rss.xml"),
    ("guardian_world", "https://www.theguardian.com/world/rss"),
    ("scmp", "https://www.scmp.com/rss/91/feed"),
    ("nikkei_asia", "https://asia.nikkei.com/rss/feed/nar"),
    ("ft_world", "https://www.ft.com/world?format=rss"),
    ("wb_atom", "https://blogs.worldbank.org/en/feeds/blogs/recent-content?lang=en"),
    ("wb_news", "https://www.worldbank.org/en/news/rss"),
    ("iea2", "https://www.iea.org/news.rss"),
    ("iea3", "https://www.iea.org/rss.xml"),
    ("argus", "https://www.argusmedia.com/en/news/rss"),
    ("benchmark", "https://www.benchmarkminerals.com/feed/"),
    ("mofcom", "http://id.mofcom.gov.cn/rss.xml"),
    ("kadin", "https://kadin.id/feed"),
    ("apindo", "https://apindo.or.id/feed"),
    # Google News site proxies for blocked prefer domains
    ("gnews_kompas", "https://news.google.com/rss/search?q=site:kompas.com+when:30d&hl=id&gl=ID&ceid=ID:id"),
    ("gnews_detik", "https://news.google.com/rss/search?q=site:detik.com+when:30d&hl=id&gl=ID&ceid=ID:id"),
    ("gnews_bisnis", "https://news.google.com/rss/search?q=site:bisnis.com+when:30d&hl=id&gl=ID&ceid=ID:id"),
    ("gnews_reuters_id", "https://news.google.com/rss/search?q=Indonesia+investment+OR+factory+when:30d+site:reuters.com&hl=en&gl=US&ceid=US:en"),
    ("gnews_china_id", "https://news.google.com/rss/search?q=China+Indonesia+investment+OR+pabrik+OR+investasi+when:30d&hl=en&gl=US&ceid=US:en"),
]


def main() -> int:
    out: list[dict] = []
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; indonesia-intel-rss-probe/1.0)",
        "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*",
    }
    with httpx.Client(timeout=25.0, follow_redirects=True, headers=headers) as client:
        for sid, url in CANDIDATES:
            row: dict = {"id": sid, "url": url, "ok": False}
            try:
                r = client.get(url)
                row["status"] = r.status_code
                row["ctype"] = (r.headers.get("content-type") or "")[:80]
                body = r.content[:2_000_000]
                if r.status_code >= 400:
                    row["error"] = f"http_{r.status_code}"
                else:
                    items = parse_rss_items(body, limit=5)
                    row["ok"] = len(items) > 0
                    row["n"] = len(items)
                    if items:
                        row["sample"] = items[0].get("title", "")[:120]
                        row["sample_url"] = (items[0].get("url") or "")[:160]
                    else:
                        row["error"] = "parse_empty"
            except Exception as exc:  # noqa: BLE001
                row["error"] = f"{type(exc).__name__}: {exc}"[:200]
            out.append(row)
            print(json.dumps(row, ensure_ascii=False))

    path = Path(__file__).resolve().parents[1] / "evidence" / "rss-probe-20260731-wave2.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"OK={sum(1 for x in out if x.get('ok'))}/{len(out)} -> {path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
