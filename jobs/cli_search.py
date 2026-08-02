"""CLI: run search ingest into review_candidates (discovered)."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from app.config import settings
from app.db import SessionLocal, init_db
from jobs.ingest_search import run_search_ingest_multi
from jobs.query_expand import expand_queries
from providers.factory import get_available_providers, get_default_provider, get_provider
from sources import SourceRegistry


DEFAULT_REGISTRY = Path(__file__).resolve().parent.parent / "sources" / "registry.yaml"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Search → discovered candidates")
    parser.add_argument("--query", "-q", required=True, help="Search query")
    parser.add_argument(
        "--registry",
        type=Path,
        default=DEFAULT_REGISTRY,
        help="Path to sources/registry.yaml",
    )
    parser.add_argument(
        "--source-id",
        default=None,
        help="Optional source id from registry (must be enabled)",
    )
    parser.add_argument(
        "--provider",
        "-p",
        default=None,
        choices=["exa", "tavily", "brave", "mock"],
        help="Search provider (default: union of configured Exa+Tavily, else mock)",
    )
    args = parser.parse_args(argv)

    registry = SourceRegistry.load(args.registry)
    source_id = args.source_id
    if source_id:
        registry.assert_fetch_allowed(source_id)

    init_db()
    common = dict(
        brave_enabled=settings.brave_enabled,
        brave_api_key=settings.brave_api_key,
        exa_api_key=settings.exa_api_key,
        tavily_api_key=settings.tavily_api_key,
    )
    with SessionLocal() as session:
        queries = expand_queries(
            args.query,
            session,
            enabled=bool(settings.query_expand_enabled),
            max_variants=4,
        )
        if args.provider:
            providers = [get_provider(args.provider, **common)]
        elif settings.search_union_enabled:
            providers = get_available_providers(**common)
        else:
            providers = [get_default_provider(**common)]
        summary = asyncio.run(
            run_search_ingest_multi(
                session,
                providers,
                queries,
                source_id=source_id,
                max_per_query=10,
                timeout_s=float(settings.search_provider_timeout_s),
            )
        )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
