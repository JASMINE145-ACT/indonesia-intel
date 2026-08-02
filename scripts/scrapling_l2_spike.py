"""Live Scrapling L2 spike for kompas / iea / mofcom. Writes evidence JSON."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fetch.content import fetch_and_extract
from fetch.content_validity import assess_extracted_page
from fetch.scrapling_l2 import fetch_and_extract_scrapling, scrapling_available
from sources.store import load_merged


TARGETS = [
    ("kompas", "http"),
    ("iea_id", "stealthy"),
    ("mofcom_id_embassy", "dynamic"),
]


def _score(page) -> dict:
    verdict = assess_extracted_page(
        title=page.title,
        text=page.text,
        html=page.html,
        final_url=page.final_url,
    )
    return {
        "ok": verdict.ok,
        "title": (page.title or "")[:100],
        "text_len": len(page.text or ""),
        "error_type": verdict.error_type,
        "block_marker": verdict.block_marker,
        "final_url": page.final_url,
    }


def try_l1(url: str) -> dict:
    t0 = time.time()
    try:
        page = fetch_and_extract(url, resolve_dns=True, timeout=20.0)
        out = _score(page)
        out["elapsed_s"] = round(time.time() - t0, 2)
        out["error"] = None
        return out
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
            "elapsed_s": round(time.time() - t0, 2),
        }


def try_l2(url: str, mode: str, allowlist: list[str]) -> dict:
    t0 = time.time()
    try:
        page = fetch_and_extract_scrapling(
            url,
            mode=mode,  # type: ignore[arg-type]
            resolve_dns=True,
            timeout=45.0,
            allow_browser=mode in {"dynamic", "stealthy"},
            allowlist=allowlist,
        )
        out = _score(page)
        out["elapsed_s"] = round(time.time() - t0, 2)
        out["mode"] = mode
        out["error"] = None
        return out
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "mode": mode,
            "error": f"{type(exc).__name__}: {exc}",
            "elapsed_s": round(time.time() - t0, 2),
        }


def main() -> int:
    reg = load_merged()
    rows = []
    for sid, mode in TARGETS:
        src = reg.get(sid)
        if src is None:
            rows.append({"id": sid, "error": "missing source"})
            continue
        url = (src.home_url or "").strip() or f"https://{src.domain}/"
        allowlist = [src.domain]
        row = {
            "id": sid,
            "domain": src.domain,
            "url": url,
            "planned_mode": mode,
            "l1": try_l1(url),
        }
        if scrapling_available():
            row["l2"] = try_l2(url, mode, allowlist)
            # escalate ladder for kompas if http fails
            if sid == "kompas" and not row["l2"].get("ok"):
                row["l2_stealthy"] = try_l2(url, "stealthy", allowlist)
        else:
            row["l2"] = {"ok": False, "error": "scrapling not available"}
        improved = bool(row.get("l2", {}).get("ok")) and not bool(row["l1"].get("ok"))
        if sid == "kompas" and row.get("l2_stealthy", {}).get("ok"):
            improved = True
        row["improved_vs_l1"] = improved
        rows.append(row)

    summary = {
        "scrapling_available": scrapling_available(),
        "targets": len(rows),
        "l2_ok": sum(1 for r in rows if r.get("l2", {}).get("ok") or r.get("l2_stealthy", {}).get("ok")),
        "improved": sum(1 for r in rows if r.get("improved_vs_l1")),
    }
    out = {"summary": summary, "results": rows}
    path = ROOT / "evidence" / "scrapling-l2-spike.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2))
    print(f"Wrote {path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
