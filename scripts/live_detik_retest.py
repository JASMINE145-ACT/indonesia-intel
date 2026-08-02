"""Isolated Detik listing → fetch smoke (post selector fix)."""
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
            session, source_ids=["detik"], limit_per_source=5, resolve_gnews=False
        )
    print("DISCOVERY", json.dumps(disc, ensure_ascii=False, indent=2, default=str))
    rid = (disc.get("results") or [{}])[0].get("run_id")
    blob = LocalBlobStore(Path(settings.blob_root))
    with SessionLocal() as session:
        fetched = fetch_discovered_candidates(
            session, blob, limit=5, run_id=str(rid), enable_l2=True
        )
    print("FETCH", json.dumps(fetched, ensure_ascii=False, indent=2, default=str))
    samples = []
    with SessionLocal() as session:
        for r in session.scalars(select(ReviewCandidate)):
            samples.append(
                {
                    "title": (r.title or "")[:100],
                    "url": (r.original_url or "")[:120],
                    "text_len": len(r.extracted_text or ""),
                    "fetch_status": r.fetch_status,
                    "preview": (r.extracted_text or "")[:160].replace("\n", " "),
                }
            )
    print("SAMPLES", json.dumps(samples, ensure_ascii=False, indent=2))
    out = Path(r"d:\demo1\.agent-test\evidence\detik-listing-live-retest.json")
    out.write_text(
        json.dumps(
            {"discovery": disc, "fetch": fetched, "samples": samples},
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    article_ok = sum(
        1
        for s in samples
        if "/berita/d-" in s["url"] and s["fetch_status"] == "ok" and s["text_len"] > 400
    )
    print(f"article_ok={article_ok}/{len(samples)}")
    shutil.rmtree(TMP, ignore_errors=True)
    return 0 if article_ok >= 3 else 1


if __name__ == "__main__":
    raise SystemExit(main())
