"""Tick4: Caixin/Reuters L2 + optional PROXY_URL wiring note + remaining B sources."""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fetch.content import fetch_and_extract
from fetch.content_validity import classify_exception, page_is_invalid
from fetch.scrapling_l2 import fetch_and_extract_scrapling, scrapling_available

OUT = ROOT / "evidence" / "scrape-tick4.json"

TARGETS = [
    (
        "caixin",
        "https://www.caixinglobal.com/2025-12-09/indonesia-signals-peak-in-nickel-mining-investment-as-focus-shifts-to-batteries-evs-102391460.html",
        "caixinglobal.com",
        ["l1", "stealthy"],
    ),
    (
        "reuters",
        "https://www.reuters.com/markets/asia/danantara-chinas-gem-develop-nickel-processing-hub-indonesia-2025-08-26/",
        "reuters.com",
        ["l1", "stealthy"],
    ),
    (
        "yicai_article",
        "https://www.yicaiglobal.com/",
        "yicaiglobal.com",
        ["l1"],
    ),
    (
        "dealstreet_home",
        "https://www.dealstreetasia.com/",
        "dealstreetasia.com",
        ["l1"],
    ),
]


def fetch_one(url: str, domain: str, mode: str) -> dict:
    try:
        if mode == "l1":
            page = fetch_and_extract(url, timeout=35.0)
        else:
            if not scrapling_available():
                return {"ok": False, "error_type": "scrapling_unavailable"}
            page = fetch_and_extract_scrapling(
                url,
                mode=mode,  # type: ignore[arg-type]
                allow_browser=True,
                allowlist={domain},
            )
        v = page_is_invalid(page)
        usable = v.ok and len(page.text or "") >= 80
        return {
            "ok": usable,
            "mode": mode,
            "title": (page.title or "")[:100],
            "text_len": len(page.text or ""),
            "error_type": None if usable else (v.error_type or "short_text"),
            "preview": (page.text or "")[:120],
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "mode": mode,
            "error_type": classify_exception(exc),
            "detail": f"{type(exc).__name__}: {exc}"[:240],
        }


def main() -> int:
    rows = {}
    for sid, url, domain, modes in TARGETS:
        print(f"== {sid}", flush=True)
        attempts = []
        success = None
        for mode in modes:
            print(f"   try {mode}", flush=True)
            r = fetch_one(url, domain, mode)
            attempts.append(r)
            if r.get("ok"):
                success = r
                break
        rows[sid] = {"url": url, "success": success, "attempts": attempts}

    plateau = {
        "needs_id_proxy_not_code": ["bkpm", "kemenperin_intermittent", "kadin_timeout"],
        "needs_paywall_or_license": ["reuters"],
        "network_path_blocked_here": ["mofcom_id_embassy"],
        "proxy_env": {
            "HTTPS_PROXY": bool(os.environ.get("HTTPS_PROXY")),
            "HTTP_PROXY": bool(os.environ.get("HTTP_PROXY")),
            "PROXY_URL": bool(os.environ.get("PROXY_URL")),
            "note": "httpx already honors HTTP(S)_PROXY; set Indonesian SOCKS/HTTP proxy to unblock *.go.id",
        },
    }
    out = {
        "tested_at": datetime.now(timezone.utc).isoformat(),
        "rows": rows,
        "plateau": plateau,
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    summary = {
        k: bool((v.get("success") or {}).get("ok")) for k, v in rows.items()
    }
    print(json.dumps({"ok": summary, "plateau_keys": list(plateau.keys())}, indent=2))
    print(f"Wrote {OUT}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
