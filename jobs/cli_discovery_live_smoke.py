"""Live smoke: prefer-source discovery poll against the public internet.

WANd.INTEL.POLL_DISPATCH — not fixture-only. Exit 0 when at least one source
completes a real adapter path (discovery_method/provider + hits present) without
error, or when rows were inserted. Soft skips (skipped=True / reason-only) do
not count as success.

Usage:
  python -m jobs.cli_discovery_live_smoke
  python -m jobs.cli_discovery_live_smoke --source-id antara --source-id kompas --limit 3
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any


def _is_source_skip(row: dict[str, Any]) -> bool:
    """True for pre-network / config soft skips (not hit-count `skipped: int`)."""
    if row.get("skipped_source") is True:
        return True
    if row.get("skipped") is True:
        return True
    return False


def _is_live_complete(row: dict[str, Any]) -> bool:
    """Completed rss|sitemap|listing path (HTTP/parse), not a soft skip."""
    if row.get("error") or _is_source_skip(row):
        return False
    if not (row.get("discovery_method") or row.get("provider")):
        return False
    return "hits" in row


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Live discovery poll smoke (rss|sitemap|listing)")
    parser.add_argument(
        "--source-id",
        action="append",
        default=[],
        help="Repeatable. Default: antara (RSS) + kompas + detik if configured",
    )
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Optional JSON evidence path",
    )
    parser.add_argument(
        "--require-inserted",
        action="store_true",
        help="Fail unless total inserted > 0 (stricter)",
    )
    args = parser.parse_args(argv)

    # Isolate DB so live smoke never pollutes the operator's intel.db.
    # Must set env BEFORE importing app.config/app.db (jobs/__init__ is import-light).
    tmp = tempfile.mkdtemp(prefix="intel-live-smoke-")
    try:
        db_path = Path(tmp) / "live.db"
        os.environ["DATABASE_URL"] = f"sqlite:///{db_path.as_posix()}"

        from app.config import settings
        from app.db import SessionLocal, init_db
        from jobs.poll_sources import poll_prefer_sources
        from sources.store import load_merged

        if "intel-live-smoke-" not in (settings.database_url or "").replace("\\", "/"):
            print(
                "FAIL: live smoke DATABASE_URL not bound to temp db; "
                f"got {settings.database_url!r} (jobs package may have imported settings too early)"
            )
            return 1

        reg = load_merged()
        source_ids = list(args.source_id)
        if not source_ids:
            for sid in ("antara", "kompas", "detik"):
                if reg.get(sid) is not None:
                    source_ids.append(sid)
        if not source_ids:
            print("FAIL: no default sources found in registry")
            return 1

        init_db()
        with SessionLocal() as session:
            summary = poll_prefer_sources(
                session,
                source_ids=source_ids,
                limit_per_source=max(1, min(int(args.limit), 20)),
                resolve_gnews=False,
            )
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    results = summary.get("results") or []
    inserted = int(summary.get("inserted") or 0)
    errors = [r for r in results if r.get("error")]
    soft_skips = [r for r in results if _is_source_skip(r) and not r.get("error")]
    live_ok = [r for r in results if _is_live_complete(r)]

    payload = {
        "live": True,
        "fixture_only": False,
        "database_url_was_temp": True,
        "source_ids": source_ids,
        "summary": summary,
        "counts": {
            "sources": len(results),
            "inserted": inserted,
            "errors": len(errors),
            "soft_skips": len(soft_skips),
            "live_ok": len(live_ok),
        },
    }
    text = json.dumps(payload, ensure_ascii=False, indent=2, default=str)
    print(text)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n", encoding="utf-8")

    if not results:
        print("FAIL: no results")
        return 1
    if len(errors) == len(results):
        print("FAIL: every source errored (network/SSRF/remote)")
        return 1
    if args.require_inserted and inserted <= 0:
        print("FAIL: --require-inserted but inserted==0")
        return 1
    # Soft skips alone never PASS; need a completed adapter path and/or inserts.
    if inserted > 0 or live_ok:
        print("PASS: live discovery smoke")
        return 0
    print("FAIL: no successful live poll path (only soft skips and/or errors)")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
