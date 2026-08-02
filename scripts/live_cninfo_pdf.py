"""Live: fetch one cninfo PDF via L1 after PDF support."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fetch.content import fetch_and_extract

URL = "http://static.cninfo.com.cn/finalpage/2026-01-31/1224959614.PDF"
OUT = ROOT / "evidence" / "cninfo-pdf-l1.json"


def main() -> int:
    try:
        page = fetch_and_extract(URL, timeout=30.0)
        out = {
            "ok": True,
            "tested_at": datetime.now(timezone.utc).isoformat(),
            "url": URL,
            "content_kind": page.content_kind,
            "title": (page.title or "")[:120],
            "text_len": len(page.text or ""),
            "text_preview": (page.text or "")[:300],
            "blob_suffix": page.blob_suffix,
            "final_url": page.final_url,
            "bytes": len(page.html),
        }
    except Exception as exc:  # noqa: BLE001
        out = {
            "ok": False,
            "tested_at": datetime.now(timezone.utc).isoformat(),
            "url": URL,
            "error": f"{type(exc).__name__}: {exc}"[:400],
        }
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    sys.stdout.buffer.write(
        (json.dumps({k: out[k] for k in out if k != "text_preview"}, ensure_ascii=False, indent=2) + "\n").encode(
            "utf-8", errors="replace"
        )
    )
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
