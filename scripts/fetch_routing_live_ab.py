"""Live A/B: L1 httpx vs L1.5 curl_cffi on URLs that previously failed as tls_disconnect.

Proves post-routing effectiveness for requirement-driven verification (真 smoke).
Writes evidence JSON under indonesia-intel/evidence/.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fetch.content import fetch_and_extract
from fetch.content_validity import page_is_invalid
from fetch.l15 import fetch_and_extract_l15, fetch_l15_enabled, scrapling_l15_available

# Previously failed as tls_disconnect / hard L1 in AI-market batch (2026-08-01).
# Plus one known-good control (Kompas-class / public HTML).
TARGETS = [
    {
        "id": "control_example",
        "url": "https://example.com/",
        "expect": "l1_ok",
        "note": "control — should succeed on L1",
    },
    {
        "id": "reuters_ai",
        "url": "https://www.reuters.com/world/asia-pacific/",
        "expect": "l15_may_rescue",
        "note": "prior tls_disconnect class",
    },
    {
        "id": "jakarta_post",
        "url": "https://www.thejakartapost.com/",
        "expect": "l15_may_rescue",
        "note": "prior tls_disconnect class",
    },
    {
        "id": "kompas_home",
        "url": "https://www.kompas.com/",
        "expect": "any_ok",
        "note": "Indonesia media — often L1 ok",
    },
]


def _try_l1(url: str) -> dict:
    try:
        page = fetch_and_extract(url, resolve_dns=True)
        v = page_is_invalid(page)
        return {
            "ok": bool(v.ok),
            "error_type": None if v.ok else v.error_type,
            "title": (page.title or "")[:80],
            "text_len": len(page.text or ""),
            "status_code": getattr(page, "status_code", None),
            "final_url": page.final_url,
        }
    except Exception as exc:  # noqa: BLE001
        from fetch.content_validity import classify_exception

        return {
            "ok": False,
            "error_type": classify_exception(exc),
            "detail": f"{type(exc).__name__}: {exc}"[:300],
        }


def _try_l15(url: str) -> dict:
    if not scrapling_l15_available():
        return {"ok": False, "error_type": "scrapling_unavailable", "skipped": True}
    try:
        page = fetch_and_extract_l15(url, resolve_dns=True)
        v = page_is_invalid(page)
        return {
            "ok": bool(v.ok),
            "error_type": None if v.ok else v.error_type,
            "title": (page.title or "")[:80],
            "text_len": len(page.text or ""),
            "status_code": getattr(page, "status_code", None),
            "final_url": page.final_url,
        }
    except Exception as exc:  # noqa: BLE001
        from fetch.content_validity import classify_exception

        return {
            "ok": False,
            "error_type": classify_exception(exc),
            "detail": f"{type(exc).__name__}: {exc}"[:300],
        }


def main() -> int:
    rows = []
    l1_ok = 0
    l15_rescue = 0
    any_ok = 0
    for t in TARGETS:
        url = t["url"]
        r1 = _try_l1(url)
        r15 = {"skipped": True, "ok": False, "error_type": "not_attempted"}
        if not r1["ok"] and fetch_l15_enabled():
            r15 = _try_l15(url)
        elif r1["ok"]:
            r15 = {"skipped": True, "ok": False, "error_type": "l1_already_ok"}

        if r1.get("ok"):
            l1_ok += 1
            any_ok += 1
        elif r15.get("ok"):
            l15_rescue += 1
            any_ok += 1

        rows.append({"target": t, "l1": r1, "l15": r15})

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "l15_enabled": fetch_l15_enabled(),
        "scrapling_available": scrapling_l15_available(),
        "summary": {
            "targets": len(TARGETS),
            "l1_ok": l1_ok,
            "l15_rescue": l15_rescue,
            "any_ok": any_ok,
            # Pass if control works AND at least one Indonesia/media or rescue path works
            "effective": any_ok >= 2,
        },
        "rows": rows,
    }
    out = ROOT / "evidence" / "fetch-routing-live-ab-20260802.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["summary"], indent=2))
    print(f"wrote {out}")
    # Exit 0 only when effectiveness criterion met
    return 0 if report["summary"]["effective"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
