"""Live smoke: prefer RSS + sample homepage/article HTML fetch. Not part of default CI."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fetch.content import fetch_and_extract
from fetch.content_validity import assess_extracted_page, classify_exception, find_block_marker
from jobs.poll_rss import parse_rss_items
from sources.store import load_merged


def smoke_rss(source_id: str, rss_url: str, client: httpx.Client) -> dict:
    try:
        resp = client.get(rss_url)
        body = resp.content[:8000]
        hit = find_block_marker(html_snippet=body)
        if hit:
            marker, err = hit
            return {
                "ok": False,
                "error_type": err,
                "block_marker": marker,
                "status_code": resp.status_code,
                "detail": f"block marker in RSS body: {marker}",
            }
        if resp.is_redirect:
            return {
                "ok": False,
                "error_type": "redirect",
                "status_code": resp.status_code,
                "detail": f"redirect {resp.status_code} (follow_redirects=False)",
            }
        if resp.status_code == 403:
            return {
                "ok": False,
                "error_type": "http_403",
                "status_code": 403,
                "detail": "HTTP 403",
            }
        if resp.status_code >= 400:
            return {
                "ok": False,
                "error_type": f"http_{resp.status_code}",
                "status_code": resp.status_code,
                "detail": f"HTTP {resp.status_code}",
            }
        items = parse_rss_items(resp.content, limit=10)
        if not items:
            return {
                "ok": False,
                "error_type": "empty_extraction",
                "status_code": resp.status_code,
                "detail": f"HTTP {resp.status_code} but 0 items parsed ({len(resp.content)} bytes)",
            }
        sample = items[0]
        return {
            "ok": True,
            "error_type": None,
            "block_marker": None,
            "status_code": resp.status_code,
            "detail": f"HTTP {resp.status_code}, items={len(items)}",
            "sample_title": (sample.get("title") or "")[:80],
            "sample_url": sample.get("url"),
        }
    except Exception as exc:  # noqa: BLE001 — smoke report
        return {
            "ok": False,
            "error_type": classify_exception(exc),
            "detail": f"{type(exc).__name__}: {exc}",
        }


def smoke_html(label: str, url: str, client: httpx.Client) -> dict:
    try:
        page = fetch_and_extract(url, client=client, resolve_dns=True)
        verdict = assess_extracted_page(
            title=page.title,
            text=page.text,
            html=page.html,
            final_url=page.final_url,
        )
        base = {
            "title": (page.title or "")[:80],
            "text_len": len(page.text or ""),
            "final_url": page.final_url,
            "error_type": verdict.error_type,
            "block_marker": verdict.block_marker,
            "detail": verdict.detail,
        }
        if not verdict.ok:
            return {"ok": False, **base}
        return {"ok": True, **base}
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "error_type": classify_exception(exc),
            "detail": f"{type(exc).__name__}: {exc}",
        }


def main() -> int:
    reg = load_merged()
    results: dict = {"rss": [], "html": [], "article_from_rss": []}
    tested_at = datetime.now(timezone.utc).isoformat()

    with httpx.Client(
        follow_redirects=False,
        timeout=20.0,
        headers={"User-Agent": "indonesia-intel-live-smoke/1.0"},
    ) as client:
        rss_sources = [s for s in reg.enabled() if s.fetch_mode == "rss" and s.rss_url]
        for src in rss_sources:
            row = {
                "id": src.id,
                "domain": src.domain,
                "priority": src.priority,
                "rss_url": src.rss_url,
                "tested_at": tested_at,
                "level": "l1",
            }
            row.update(smoke_rss(src.id, src.rss_url, client))
            results["rss"].append(row)

            if row.get("ok") and row.get("sample_url"):
                art = {
                    "from_source": src.id,
                    "url": row["sample_url"],
                    "tested_at": tested_at,
                    "level": "l1",
                }
                art.update(smoke_html(f"{src.id}:article", row["sample_url"], client))
                results["article_from_rss"].append(art)

        sample_ids = [
            "bkpm",
            "kemenperin",
            "esdm",
            "idx",
            "kadin",
            "imip",
            "mofcom_id_embassy",
            "worldbank_id",
            "iea_id",
            "antara",
            "kompas",
        ]
        for sid in sample_ids:
            src = reg.get(sid)
            if src is None or not src.enabled:
                results["html"].append(
                    {
                        "id": sid,
                        "ok": False,
                        "error_type": "missing_or_disabled",
                        "detail": "missing/disabled",
                        "tested_at": tested_at,
                    }
                )
                continue
            url = (src.home_url or "").strip() or f"https://{src.domain}/"
            row = {
                "id": src.id,
                "domain": src.domain,
                "fetch_mode": src.fetch_mode,
                "url": url,
                "tested_at": tested_at,
                "level": "l1",
            }
            row.update(smoke_html(sid, url, client))
            results["html"].append(row)

    def tally(rows: list[dict]) -> dict:
        ok = sum(1 for r in rows if r.get("ok"))
        by_err: dict[str, int] = {}
        for r in rows:
            if not r.get("ok"):
                et = r.get("error_type") or "unknown"
                by_err[et] = by_err.get(et, 0) + 1
        return {"ok": ok, "fail": len(rows) - ok, "total": len(rows), "by_error_type": by_err}

    summary = {
        "tested_at": tested_at,
        "rss": tally(results["rss"]),
        "html_home": tally(results["html"]),
        "article_from_rss": tally(results["article_from_rss"]),
    }
    out = {"summary": summary, "results": results}
    out_path = ROOT / "evidence" / "live-fetch-smoke.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2))
    print(f"\nWrote {out_path}", file=sys.stderr)
    fails = summary["rss"]["fail"] + summary["html_home"]["fail"] + summary["article_from_rss"]["fail"]
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
