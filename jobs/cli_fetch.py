from __future__ import annotations

import argparse
import json

from app.config import settings
from app.db import SessionLocal, init_db
from jobs.fetch_candidates import fetch_discovered_candidates
from storage.blob import LocalBlobStore


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fetch discovered → pending_review")
    parser.add_argument("--limit", type=int, default=50)
    args = parser.parse_args(argv)
    init_db()
    blob = LocalBlobStore(settings.blob_path)
    with SessionLocal() as session:
        summary = fetch_discovered_candidates(session, blob, limit=args.limit)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
