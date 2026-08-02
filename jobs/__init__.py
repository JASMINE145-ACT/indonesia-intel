"""indonesia-intel jobs package.

Keep this module import-light: eager imports of ingest/app.config bind
DATABASE_URL from .env before live CLIs can point at an isolated sqlite.
"""

from __future__ import annotations

from typing import Any

__all__ = ["normalize_url", "url_hash", "run_search_ingest"]


def __getattr__(name: str) -> Any:
    if name in ("normalize_url", "url_hash"):
        from dedup.url import normalize_url, url_hash

        return {"normalize_url": normalize_url, "url_hash": url_hash}[name]
    if name == "run_search_ingest":
        from jobs.ingest_search import run_search_ingest

        return run_search_ingest
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
