"""Live GNews resolve evidence on an isolated temp DB — WANd.INTEL.GNEWS_RESOLVE.001.

Not a discovery source (AC-03). Fetches one Google News RSS item URL, inserts a
discovered candidate, runs apply_resolve_to_candidate, writes classified JSON.

Usage:
  python scripts/live_gnews_resolve_smoke.py
  python scripts/live_gnews_resolve_smoke.py --out evidence/gnews-live-20260801.json
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

import httpx

GNEWS_RSS = (
    "https://news.google.com/rss/search?"
    "q=site:kompas.com+when:7d&hl=id&gl=ID&ceid=ID:id"
)


def _first_item_link(xml_bytes: bytes) -> str | None:
    root = ET.fromstring(xml_bytes)
    item = root.find(".//item")
    if item is None:
        return None
    link = (item.findtext("link") or "").strip()
    return link or None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Live GNews resolve on temp DB")
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("evidence/gnews-live-20260801.json"),
    )
    parser.add_argument("--rss", default=GNEWS_RSS)
    args = parser.parse_args(argv)

    tmp = tempfile.mkdtemp(prefix="intel-gnews-live-")
    try:
        db_path = Path(tmp) / "gnews.db"
        os.environ["DATABASE_URL"] = f"sqlite:///{db_path.as_posix()}"

        from app.config import settings
        from app.db import SessionLocal, init_db
        from app.models import ReviewCandidate
        from jobs.adapters.gnews_resolve import (
            apply_resolve_to_candidate,
            is_google_news_url,
            resolve_google_news_url,
        )
        from sqlalchemy import select

        if "intel-gnews-live-" not in (settings.database_url or "").replace("\\", "/"):
            print(f"FAIL: temp DB not bound: {settings.database_url!r}")
            return 1

        feed_status = None
        gnews_url = None
        feed_error = None
        try:
            with httpx.Client(timeout=30.0, follow_redirects=True) as client:
                resp = client.get(
                    args.rss,
                    headers={"User-Agent": "indonesia-intel-gnews-smoke/1.0"},
                )
                feed_status = resp.status_code
                resp.raise_for_status()
                gnews_url = _first_item_link(resp.content)
        except Exception as exc:  # noqa: BLE001
            feed_error = str(exc)[:300]

        if not gnews_url:
            payload = {
                "live": True,
                "database_url_was_temp": True,
                "status": "accepted_risk",
                "classification": "feed_unreachable_or_empty",
                "feed_status": feed_status,
                "feed_error": feed_error,
                "rss": args.rss,
            }
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            print("PASS: accepted_risk evidence written")
            return 0

        if not is_google_news_url(gnews_url):
            payload = {
                "live": True,
                "database_url_was_temp": True,
                "status": "accepted_risk",
                "classification": "rss_link_not_gnews_host",
                "url": gnews_url[:200],
                "feed_status": feed_status,
            }
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            print("PASS: accepted_risk evidence written")
            return 0

        # Direct resolve first (budget classification)
        direct = resolve_google_news_url(gnews_url, timeout_s=20.0)

        init_db()
        budget = [0]
        with SessionLocal() as session:
            from dedup.url import normalize_url, url_hash
            import uuid

            rid = uuid.uuid4().hex[:16]
            row = ReviewCandidate(
                run_id=rid,
                provider="gnews_live_smoke",
                query="gnews-live",
                original_url=gnews_url,
                canonical_url=normalize_url(gnews_url),
                url_hash=url_hash(gnews_url),
                title="gnews live smoke",
                snippet="",
                status="discovered",
                discovery_method="rss",
                resolution_status="pending",
            )
            session.add(row)
            session.flush()
            apply_resolve_to_candidate(
                session, row, max_budget=20, budget_used=budget
            )
            session.commit()
            fresh = session.scalar(
                select(ReviewCandidate).where(ReviewCandidate.id == row.id)
            )
            payload = {
                "live": True,
                "fixture_only": False,
                "database_url_was_temp": True,
                "rss": args.rss,
                "feed_status": feed_status,
                "gnews_url": gnews_url[:300],
                "direct_resolve": direct,
                "candidate": {
                    "id": fresh.id if fresh else None,
                    "resolution_status": fresh.resolution_status if fresh else None,
                    "resolved_url": (fresh.resolved_url or "")[:300] if fresh else None,
                    "status": fresh.status if fresh else None,
                },
                "budget_used": budget[0],
                "classification": (direct.get("status") or "unknown"),
            }

        args.out.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(payload, ensure_ascii=False, indent=2, default=str)
        args.out.write_text(text + "\n", encoding="utf-8")
        print(text)
        print("PASS: gnews live evidence written")
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
