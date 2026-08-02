"""CLI: prefer-source extension smoke (search → fetch → local usability)."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from app.config import settings
from app.db import SessionLocal, init_db
from jobs.source_smoke import dump_summary, run_source_smoke, summarize_exception
from providers.factory import get_default_provider, get_provider
from sources.store import load_merged
from storage.blob import LocalBlobStore

DEFAULT_THEME = "Indonesia China investment OR nickel OR EV OR factory"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Smoke one prefer source: site:domain search → fetch → local"
    )
    parser.add_argument("--source-id", "-s", required=True)
    parser.add_argument("--query", "-q", default=DEFAULT_THEME)
    parser.add_argument(
        "--provider",
        "-p",
        default=None,
        choices=["exa", "tavily", "mock", "brave"],
        help="Search provider (default: Exa→Tavily→mock)",
    )
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--no-l2", action="store_true")
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Optional JSON evidence path under evidence/",
    )
    args = parser.parse_args(argv)

    common = dict(
        brave_enabled=settings.brave_enabled,
        brave_api_key=settings.brave_api_key,
        exa_api_key=settings.exa_api_key,
        tavily_api_key=settings.tavily_api_key,
    )
    if args.provider:
        provider = get_provider(args.provider, **common)
    else:
        provider = get_default_provider(**common)

    registry = load_merged()
    init_db()
    blob = LocalBlobStore(settings.blob_path)

    try:
        with SessionLocal() as session:
            summary = asyncio.run(
                run_source_smoke(
                    session,
                    blob,
                    registry=registry,
                    source_id=args.source_id,
                    provider=provider,
                    query=args.query,
                    enable_l2=False if args.no_l2 else None,
                    limit=args.limit,
                )
            )
    except Exception as exc:  # noqa: BLE001
        summary = {
            "source_id": args.source_id,
            "pipeline": "error",
            **summarize_exception(exc),
        }

    text = dump_summary(summary)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
    print(text)
    return 0 if summary.get("pipeline") == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(main())
