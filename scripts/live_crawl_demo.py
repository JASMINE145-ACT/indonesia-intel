"""Isolated live crawl demo (discovery → fetch). Run as script, not -m jobs.*."""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

TMP = Path(tempfile.mkdtemp(prefix="intel-live-crawl-"))
DB = TMP / "crawl.db"
BLOB = TMP / "blobs"
BLOB.mkdir(parents=True, exist_ok=True)
os.environ["DATABASE_URL"] = f"sqlite:///{DB.as_posix()}"
os.environ["BLOB_ROOT"] = str(BLOB)

from app.config import settings  # noqa: E402

print("bound_db=", settings.database_url)
assert "intel-live-crawl-" in settings.database_url.replace("\\", "/")

from app.db import SessionLocal, init_db  # noqa: E402
from app.models import ReviewCandidate  # noqa: E402
from jobs.fetch_candidates import fetch_discovered_candidates  # noqa: E402
from jobs.poll_sources import poll_prefer_sources  # noqa: E402
from sqlalchemy import select  # noqa: E402
from storage.blob import LocalBlobStore  # noqa: E402


def main() -> int:
    init_db()
    with SessionLocal() as session:
        disc = poll_prefer_sources(
            session,
            source_ids=["antara", "kompas", "detik"],
            limit_per_source=5,
            resolve_gnews=False,
        )
    print("=== DISCOVERY ===")
    print(json.dumps(disc, ensure_ascii=False, indent=2, default=str))

    run_ids = [r.get("run_id") for r in (disc.get("results") or []) if r.get("run_id")]
    blob = LocalBlobStore(Path(settings.blob_root))
    fetch_summaries = []
    with SessionLocal() as session:
        for rid in run_ids:
            fetch_summaries.append(
                fetch_discovered_candidates(
                    session, blob, limit=10, run_id=str(rid), enable_l2=True
                )
            )
    print("=== FETCH ===")
    print(json.dumps(fetch_summaries, ensure_ascii=False, indent=2, default=str))

    samples = []
    with SessionLocal() as session:
        rows = list(session.scalars(select(ReviewCandidate).order_by(ReviewCandidate.id)))
        for r in rows:
            text = (r.extracted_text or "")[:280].replace("\n", " ").strip()
            samples.append(
                {
                    "source_id": r.source_id,
                    "discovery_method": r.discovery_method,
                    "status": r.status,
                    "fetch_status": r.fetch_status,
                    "title": (r.title or "")[:140],
                    "url": (r.resolved_url or r.original_url or "")[:160],
                    "text_len": len(r.extracted_text or ""),
                    "text_preview": text,
                }
            )
    print("=== SAMPLES ===")
    print(json.dumps(samples, ensure_ascii=False, indent=2, default=str))

    out = Path(r"d:\demo1\.agent-test\evidence\manual-live-crawl-e2e.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(
            {"discovery": disc, "fetch": fetch_summaries, "samples": samples},
            ensure_ascii=False,
            indent=2,
            default=str,
        )
        + "\n",
        encoding="utf-8",
    )
    print("wrote", out)

    by_src: dict[str, int] = {}
    ok_fetch = 0
    for s in samples:
        by_src[s["source_id"]] = by_src.get(s["source_id"], 0) + 1
        if s["fetch_status"] == "ok" and s["text_len"] > 100:
            ok_fetch += 1
    print("by_source=", by_src, "fetch_ok_with_text=", ok_fetch, "/", len(samples))
    shutil.rmtree(TMP, ignore_errors=True)
    return 0 if int(disc.get("inserted") or 0) > 0 and ok_fetch > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
