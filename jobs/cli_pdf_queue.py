"""CLI: process / revert PDF queue — WANd.INTEL.FETCH_PDF_QUEUE.001."""

from __future__ import annotations

import argparse
import json

from app.config import settings
from app.db import SessionLocal, init_db
from jobs.pdf_queue import process_pdf_queue, revert_queued_to_failed
from storage.blob import LocalBlobStore


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="PDF document queue worker")
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument(
        "--revert-queued",
        action="store_true",
        help="Move pdf_queued → fetch_failed (rollback)",
    )
    parser.add_argument("--resolve-dns", action="store_true", default=False)
    args = parser.parse_args(argv)
    init_db()
    with SessionLocal() as session:
        if args.revert_queued:
            n = revert_queued_to_failed(session)
            session.commit()
            print(json.dumps({"reverted": n}, ensure_ascii=False))
            return 0
        blob = LocalBlobStore(settings.blob_path)
        out = process_pdf_queue(
            session, blob, limit=args.limit, resolve_dns=args.resolve_dns
        )
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if out.get("failed", 0) == 0 or out.get("ok", 0) > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
