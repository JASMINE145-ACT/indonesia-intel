"""Tick3: diagnose hard sources + Tavily fallback for Exa-flaky domains."""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import settings
from fetch.content import fetch_and_extract
from fetch.content_validity import classify_exception, page_is_invalid
from fetch.scrapling_l2 import fetch_and_extract_scrapling, scrapling_available
from sources.store import load_merged

OUT = ROOT / "evidence" / "scrape-tick3-hard-sources.json"

# Direct article/home URLs to classify blockers (no search dependency)
DIRECT = {
    "bkpm": "https://www.bkpm.go.id/",
    "kadin": "https://www.kadin.id/",
    "mofcom_id_embassy": "http://id.mofcom.gov.cn/",
    "kemenperin": "https://www.kemenperin.go.id/",
    "esdm": "https://www.esdm.go.id/",
}


def try_l1(url: str) -> dict:
    try:
        page = fetch_and_extract(url, timeout=25.0)
        v = page_is_invalid(page)
        return {
            "ok": v.ok,
            "title": (page.title or "")[:80],
            "text_len": len(page.text or ""),
            "error_type": None if v.ok else v.error_type,
            "detail": v.detail if not v.ok else None,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "error_type": classify_exception(exc),
            "detail": f"{type(exc).__name__}: {exc}"[:240],
        }


def try_l2(url: str, mode: str, domain: str) -> dict:
    if not scrapling_available():
        return {"ok": False, "error_type": "scrapling_unavailable"}
    try:
        page = fetch_and_extract_scrapling(
            url,
            mode=mode,
            resolve_dns=True,
            allow_browser=mode in {"dynamic", "stealthy"},
            allowlist={domain},
        )
        v = page_is_invalid(page)
        return {
            "ok": v.ok,
            "mode": mode,
            "title": (page.title or "")[:80],
            "text_len": len(page.text or ""),
            "error_type": None if v.ok else v.error_type,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "mode": mode,
            "error_type": classify_exception(exc),
            "detail": f"{type(exc).__name__}: {exc}"[:240],
        }


def tavily_site(domain: str) -> dict:
    if not settings.tavily_api_key:
        return {"ok": False, "error": "no_tavily_key"}
    import asyncio
    from providers.factory import get_provider

    async def _run():
        p = get_provider("tavily", tavily_api_key=settings.tavily_api_key)
        return await p.search(f"site:{domain} Indonesia China investment nickel")

    try:
        hits = asyncio.run(_run())
        return {
            "ok": True,
            "hits": len(hits),
            "sample": [{"title": h.title[:80], "url": h.url} for h in hits[:3]],
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:200]}


def main() -> int:
    reg = load_merged()
    rows = {}
    for sid, url in DIRECT.items():
        src = reg.get(sid)
        print(f"== {sid} L1", flush=True)
        l1 = try_l1(url)
        l2 = None
        if not l1.get("ok"):
            mode = "stealthy"
            if src and getattr(src, "fetch_l2_mode", None):
                mode = src.fetch_l2_mode or mode
            domain = (src.domain if src else "") or ""
            print(f"   L2 {mode}", flush=True)
            l2 = try_l2(url, mode, domain)
        rows[sid] = {"url": url, "l1": l1, "l2": l2}

    print("== tavily fallbacks", flush=True)
    tavily = {}
    for domain in ("reuters.com", "worldbank.org", "caixinglobal.com", "kadin.id"):
        print(f"   site:{domain}", flush=True)
        tavily[domain] = tavily_site(domain)

    github_clarification = {
        "bkpm_go_id_family": (
            "GitHub indonesia-civic-stack: many *.go.id portals restrict non-ID IPs "
            "and/or have brittle TLS. Recommended fix is PROXY_URL via Indonesian "
            "SOCKS/HTTP proxy — not verify=False. We will NOT disable TLS verify."
        ),
        "proxy_env_present": bool(
            os.environ.get("HTTPS_PROXY")
            or os.environ.get("HTTP_PROXY")
            or os.environ.get("PROXY_URL")
        ),
        "ref": "https://github.com/suryast/indonesia-civic-stack",
    }

    out = {
        "tested_at": datetime.now(timezone.utc).isoformat(),
        "direct_fetch": rows,
        "tavily_site_search": tavily,
        "github_clarification": github_clarification,
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    # compact stdout
    compact = {
        sid: {
            "l1": r["l1"].get("ok"),
            "l1_err": r["l1"].get("error_type"),
            "l2": (r["l2"] or {}).get("ok"),
            "l2_err": (r["l2"] or {}).get("error_type"),
        }
        for sid, r in rows.items()
    }
    print(json.dumps({"direct": compact, "proxy": github_clarification["proxy_env_present"]}, indent=2))
    print(f"Wrote {OUT}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
