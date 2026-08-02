"""Quick L2 spike for IDX (and optional kompas RSS). Writes evidence JSON."""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fetch.content import fetch_and_extract
from fetch.content_validity import assess_extracted_page, classify_exception
from fetch.scrapling_l2 import fetch_and_extract_scrapling, scrapling_available


def _score(page) -> dict:
    v = assess_extracted_page(
        title=page.title, text=page.text, html=page.html, final_url=page.final_url
    )
    return {
        "ok": v.ok,
        "title": (page.title or "")[:100],
        "text_len": len(page.text or ""),
        "error_type": v.error_type,
        "block_marker": v.block_marker,
        "final_url": page.final_url,
    }


def try_level(url: str, level: str, mode: str | None = None) -> dict:
    t0 = time.time()
    allow = ["idx.co.id", "kompas.com"]
    try:
        if level == "l1":
            page = fetch_and_extract(url, resolve_dns=True, timeout=20.0)
        else:
            page = fetch_and_extract_scrapling(
                url,
                mode=mode or "stealthy",  # type: ignore[arg-type]
                resolve_dns=True,
                timeout=60.0,
                allow_browser=(mode or "stealthy") in {"dynamic", "stealthy"},
                allowlist=allow,
            )
        out = _score(page)
        out["elapsed_s"] = round(time.time() - t0, 2)
        out["level"] = level
        out["mode"] = mode
        return out
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "level": level,
            "mode": mode,
            "error_type": classify_exception(exc),
            "detail": f"{type(exc).__name__}: {exc}",
            "elapsed_s": round(time.time() - t0, 2),
        }


def main() -> int:
    rows = []
    # IDX home
    idx_url = "https://www.idx.co.id/"
    rows.append(
        {
            "id": "idx",
            "url": idx_url,
            "l1": try_level(idx_url, "l1"),
            "l2_http": try_level(idx_url, "l2", "http") if scrapling_available() else None,
            "l2_stealthy": try_level(idx_url, "l2", "stealthy") if scrapling_available() else None,
        }
    )
    # Kompas RSS via L2 http/stealthy (raw fetch path still goes through extract — note)
    rss = "https://rss.kompas.com/api/feed/social?channel=nasional"
    rows.append(
        {
            "id": "kompas_rss",
            "url": rss,
            "l1": try_level(rss, "l1"),
            "l2_http": try_level(rss, "l2", "http") if scrapling_available() else None,
            "l2_stealthy": try_level(rss, "l2", "stealthy") if scrapling_available() else None,
        }
    )
    out = {
        "tested_at": datetime.now(timezone.utc).isoformat(),
        "scrapling_available": scrapling_available(),
        "results": rows,
    }
    path = ROOT / "evidence" / "diagnostics-idx-kompas-rss-spike.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2))
    print(f"Wrote {path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
