"""CLI: Agent Reach social search → discovered.

  set INTEL_REACH_ENABLED=1
  python -m jobs.cli_reach_search --query "China Indonesia FDI" --provider youtube
"""

from __future__ import annotations

import argparse
import json
import sys

from app import db as dbmod
from app.config import settings
from jobs.ingest_reach import run_reach_ingest


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Agent Reach social → discovered")
    p.add_argument("--query", required=True)
    p.add_argument("--provider", default="youtube", choices=["youtube", "linkedin"])
    p.add_argument("--max-results", type=int, default=10)
    args = p.parse_args(argv)

    dbmod.init_db()
    with dbmod.SessionLocal() as session:
        out = run_reach_ingest(
            session,
            args.query,
            provider=args.provider,
            youtube_api_key=settings.youtube_api_key,
            max_results=args.max_results,
        )
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if out.get("ok") or out.get("reason") else 1


if __name__ == "__main__":
    sys.exit(main())
