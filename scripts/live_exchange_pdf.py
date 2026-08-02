"""Live PDF L1 for szse + hkexnews (post PDF support)."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fetch.content import fetch_and_extract

URLS = {
    "szse": "https://disc.static.szse.cn/disc/disk03/finalpage/2023-12-21/b36f0666-4b85-4789-8a76-f6fa68399108.PDF",
    "hkexnews": "https://www1.hkexnews.hk/listedco/listconews/sehk/2025/1020/2025102001378.pdf",
}
OUT = ROOT / "evidence" / "exchange-pdf-l1.json"


def main() -> int:
    rows = {}
    for sid, url in URLS.items():
        try:
            page = fetch_and_extract(url, timeout=45.0)
            rows[sid] = {
                "ok": True,
                "url": url,
                "content_kind": page.content_kind,
                "title": (page.title or "")[:100],
                "text_len": len(page.text or ""),
                "bytes": len(page.html),
            }
        except Exception as exc:  # noqa: BLE001
            rows[sid] = {"ok": False, "url": url, "error": f"{type(exc).__name__}: {exc}"[:300]}
    out = {"tested_at": datetime.now(timezone.utc).isoformat(), "rows": rows}
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    summary = {k: {"ok": v.get("ok"), "text_len": v.get("text_len"), "error": v.get("error")} for k, v in rows.items()}
    sys.stdout.buffer.write((json.dumps(summary, ensure_ascii=False, indent=2) + "\n").encode("utf-8", errors="replace"))
    return 0 if all(r.get("ok") for r in rows.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
