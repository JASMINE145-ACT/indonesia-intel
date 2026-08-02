"""Prove Tavily-discovered articles for previously Exa-flaky domains + Kadin L2."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fetch.content import fetch_and_extract
from fetch.content_validity import page_is_invalid
from fetch.scrapling_l2 import fetch_and_extract_scrapling

OUT = ROOT / "evidence" / "scrape-tick3-tavily-fetch.json"

TARGETS = [
    (
        "reuters",
        "https://www.reuters.com/markets/commodities/china-built-indonesias-nickel-boom-could-yet-bust-it-2025-12-01",
        "l1",
    ),
    (
        "caixin_global",
        "https://www.caixinglobal.com/2025-12-09/indonesia-signals-peak-in-nickel-mining-investment-as-focus-shifts-to-batteries-evs-102391460.html",
        "l1",
    ),
    (
        "worldbank_pdf",
        "https://documents1.worldbank.org/curated/en/099457511102525232/pdf/IDU-dd5457e6-f5fe-419c-b0ef-ae05bd244854.pdf",
        "l1",
    ),
    (
        "kadin",
        "https://kadin.id/en/kabar/kadin-indonesia-ingin-jawab-keluhan-pengusaha-china-di-tanah-air",
        "l2_stealthy",
    ),
]


def main() -> int:
    rows = {}
    for sid, url, how in TARGETS:
        print(f"== {sid} {how}", flush=True)
        try:
            if how == "l1":
                page = fetch_and_extract(url, timeout=40.0)
            else:
                page = fetch_and_extract_scrapling(
                    url,
                    mode="stealthy",
                    allow_browser=True,
                    allowlist={"kadin.id"},
                )
            v = page_is_invalid(page)
            rows[sid] = {
                "ok": v.ok and len(page.text or "") >= 80,
                "how": how,
                "title": (page.title or "")[:100],
                "text_len": len(page.text or ""),
                "kind": getattr(page, "content_kind", "html"),
                "error_type": None if v.ok else v.error_type,
            }
        except Exception as exc:  # noqa: BLE001
            rows[sid] = {"ok": False, "how": how, "error": f"{type(exc).__name__}: {exc}"[:240]}
        print(f"   ok={rows[sid].get('ok')} text={rows[sid].get('text_len')}", flush=True)

    out = {"tested_at": datetime.now(timezone.utc).isoformat(), "rows": rows}
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: {"ok": v.get("ok"), "text_len": v.get("text_len")} for k, v in rows.items()}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
