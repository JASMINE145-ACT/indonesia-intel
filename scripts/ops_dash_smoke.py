"""One-shot local smoke for ops dashboard APIs (temp notes)."""
from __future__ import annotations

import json
from pathlib import Path

import httpx

BASE = "http://127.0.0.1:8765"
OUT = Path(__file__).resolve().parents[1] / "evidence" / "ops-dash-smoke-20260801.md"


def main() -> int:
    lines = ["# Ops dashboard smoke — 2026-08-01", ""]
    with httpx.Client(timeout=20.0) as c:
        h = c.get(f"{BASE}/health")
        lines.append(f"- health: {h.status_code} ok={h.json().get('status')}")
        # Discover key from settings via a tiny import after health
        from app.config import settings

        key = settings.api_key
        headers = {"X-API-Key": key}
        p = c.get(f"{BASE}/pipeline/summary", headers=headers)
        lines.append(f"- pipeline/summary: {p.status_code} total={p.json().get('total') if p.status_code==200 else p.text[:80]}")
        s = c.get(f"{BASE}/stats", headers=headers)
        lines.append(f"- stats: {s.status_code} keys={list(s.json().keys())[:6] if s.status_code==200 else 'err'}")
        app = c.get(f"{BASE}/app/")
        text = app.text
        markers = ('data-tab="feed"', 'data-tab="stats"', 'data-tab="review"')
        tabs_ok = all(m in text for m in markers)
        lines.append(f"- /app/: {app.status_code} tabs={tabs_ok}")
        # detail if any candidate
        listed = c.get(f"{BASE}/candidates?status=discovered", headers=headers)
        items = listed.json().get("items") if listed.status_code == 200 else []
        if items:
            did = items[0]["id"]
            d = c.get(f"{BASE}/candidates/{did}", headers=headers)
            body = d.json() if d.status_code == 200 else {}
            lines.append(
                f"- candidates/{did}: {d.status_code} title={str(body.get('title',''))[:40]!r} truncated={body.get('extracted_text_truncated')}"
            )
        else:
            lines.append("- candidates detail: skipped (no discovered items in operator DB)")
    lines.append("")
    lines.append("Manual: open http://127.0.0.1:8765/app/#feed")
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    print("wrote", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
