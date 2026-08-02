"""Live smoke — Agent Reach (WANd.INTEL.AGENT_REACH_SOCIAL.001).

真 smoke: real MCP service path + live HTTP to YouTube Data API host.
Writes evidence JSON under indonesia-intel/evidence/.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

EVIDENCE = ROOT / "evidence" / "agent-reach-live-smoke-20260802.json"


def main() -> int:
    from app import db as dbmod
    from app.config import settings
    from mcp_server import service
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.db import Base

    report: dict = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "contract": "WANd.INTEL.AGENT_REACH_SOCIAL.001",
        "steps": [],
    }

    # --- temp DB for inserts ---
    engine = create_engine(
        "sqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
    )
    dbmod.engine = engine
    dbmod.SessionLocal = sessionmaker(
        bind=engine, autoflush=False, autocommit=False, future=True
    )
    Base.metadata.create_all(engine)

    # 1) Flag OFF — real service path
    os.environ["INTEL_REACH_ENABLED"] = "0"
    out_off = service.intel_search_social("China Indonesia FDI", provider="youtube")
    report["steps"].append({"name": "flag_off", "out": out_off})
    assert out_off.get("ok") is False
    assert out_off.get("reason") == "reach_disabled"
    assert out_off.get("inserted", 0) == 0

    # 2) Flag ON — LinkedIn stub (real code, no cookie)
    os.environ["INTEL_REACH_ENABLED"] = "1"
    out_li = service.intel_search_social("China Indonesia", provider="linkedin")
    report["steps"].append({"name": "linkedin_stub", "out": out_li})
    assert out_li.get("ok") is False
    assert out_li.get("reason") == "linkedin_needs_credentials"

    # 3) Live HTTP to YouTube Data API (network 真)
    key = (settings.youtube_api_key or os.environ.get("YOUTUBE_API_KEY") or "").strip()
    params = {
        "part": "snippet",
        "type": "video",
        "q": "China Indonesia investment",
        "maxResults": 1,
        "key": key or "INVALID_LIVE_SMOKE_KEY",
    }
    with httpx.Client(timeout=30.0) as client:
        resp = client.get(
            "https://www.googleapis.com/youtube/v3/search",
            params=params,
        )
    live_http = {
        "status_code": resp.status_code,
        "ok_json": False,
        "items": 0,
    }
    try:
        body = resp.json()
        live_http["ok_json"] = True
        live_http["items"] = len(body.get("items") or [])
        live_http["error_reason"] = (
            (body.get("error") or {}).get("errors") or [{}]
        )[0].get("reason")
    except Exception as exc:  # noqa: BLE001
        live_http["parse_error"] = type(exc).__name__
    report["steps"].append({"name": "youtube_live_http", "result": live_http})
    # Must be a real response from Google (not transport failure)
    assert resp.status_code in {200, 400, 403}, f"unexpected status {resp.status_code}"

    # 4) Ingest path with real key (if any) or missing-key typed skip
    if key:
        out_yt = service.intel_search_social(
            "China Indonesia investment", provider="youtube", max_results=3
        )
        report["steps"].append({"name": "youtube_ingest", "out": out_yt})
        assert out_yt.get("reason") != "reach_disabled"
        # May be ok with inserts, or quota typed skip — both acceptable live outcomes
        assert out_yt.get("discovery_method") == "reach_youtube"
    else:
        out_yt = service.intel_search_social("q", provider="youtube")
        report["steps"].append({"name": "youtube_missing_key", "out": out_yt})
        assert out_yt.get("reason") == "youtube_missing_key"
        assert out_yt.get("inserted", 0) == 0

    report["pass"] = True
    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"pass": True, "evidence": str(EVIDENCE)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"pass": False, "error": str(exc)}, ensure_ascii=False))
        raise SystemExit(1)
