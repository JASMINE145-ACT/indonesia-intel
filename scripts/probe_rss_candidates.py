"""Probe candidate RSS URLs for prefer sources. Writes JSON report."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx

from jobs.poll_rss import parse_rss_items

CANDIDATES: list[tuple[str, str]] = [
    # ID media
    ("antara", "https://en.antaranews.com/rss/news.xml"),
    ("antara_id", "https://www.antaranews.com/rss/terkini.xml"),
    ("kompas", "https://rss.kompas.com/api/feed/social/kompascom"),
    ("kompas_news", "https://www.kompas.com/rss"),
    ("detik", "https://rss.detik.com/index.php/detikcom"),
    ("detik_finance", "https://rss.detik.com/index.php/finance"),
    ("bisnis", "https://www.bisnis.com/rss"),
    ("bisnis_market", "https://market.bisnis.com/rss"),
    ("kontan", "https://industri.kontan.co.id/rss"),
    ("kontan_en", "https://english.kontan.co.id/rss"),
    # CN / outbound
    ("kr36", "https://36kr.com/feed"),
    ("krasia", "https://kr-asia.com/feed"),
    ("caixin", "https://www.caixinglobal.com/feed"),
    ("yicai", "https://www.yicaiglobal.com/rss"),
    # INT
    ("reuters", "https://www.reutersagency.com/feed/"),
    ("reuters_biz", "https://www.reuters.com/business/rss"),
    ("worldbank", "https://www.worldbank.org/en/news/all?view=rss"),
    ("worldbank_id", "https://www.worldbank.org/en/country/indonesia/rss"),
    ("imf", "https://www.imf.org/en/News/RSS"),
    ("imf_all", "https://www.imf.org/en/News/RSS?language=eng"),
    ("unctad", "https://unctad.org/rss.xml"),
    ("iea", "https://www.iea.org/feeds/news.rss"),
    ("dealstreet", "https://www.dealstreetasia.com/feed"),
    ("dealstreet_alt", "https://www.dealstreetasia.com/stories/feed"),
    # CN disclosure often no public RSS — probe anyway
    ("cninfo", "http://www.cninfo.com.cn/new/commonUrl/rss"),
]


def main() -> int:
    out: list[dict] = []
    headers = {
        "User-Agent": "indonesia-intel-rss-probe/1.0 (+local research)",
        "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*",
    }
    with httpx.Client(timeout=20.0, follow_redirects=True, headers=headers) as client:
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
                    else:
                        row["error"] = "parse_empty"
                        row["head"] = body[:120].decode("utf-8", errors="replace")
            except Exception as exc:  # noqa: BLE001
                row["error"] = f"{type(exc).__name__}: {exc}"[:200]
            out.append(row)
            print(json.dumps(row, ensure_ascii=False))

    path = Path(__file__).resolve().parents[1] / "evidence" / "rss-probe-20260731.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    ok_n = sum(1 for x in out if x.get("ok"))
    print(f"OK={ok_n}/{len(out)} -> {path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
