"""Shared discovery insert helpers."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import IngestRun, ReviewCandidate
from dedup.url import normalize_url, url_hash


def same_registrable_domain(url: str, domain: str) -> bool:
    host = (urlparse(url).hostname or "").lower().removeprefix("www.")
    d = (domain or "").lower().removeprefix("www.")
    if not host or not d:
        return False
    return host == d or host.endswith("." + d)


def url_path_allowed(
    url: str,
    *,
    include_patterns: list[str] | None = None,
    exclude_patterns: list[str] | None = None,
) -> bool:
    """Path substring filters (exclude-then-include; empty includes ⇒ allow).

    Same rule as sitemap `_match_patterns` for an explicit pattern list.
    Listing does not inject sitemap default patterns when omitted.
    """
    path = urlparse(url).path or "/"
    for ex in exclude_patterns or []:
        if ex and ex in path:
            return False
    includes = [p for p in (include_patterns or []) if p]
    if not includes:
        return True
    return any(inc in path for inc in includes)


def insert_discovered_hits(
    session: Session,
    hits: list[dict[str, Any]],
    *,
    source_id: str,
    provider: str,
    discovery_method: str,
    language: str | None = None,
    source_domain: str | None = None,
    run_id: str | None = None,
    note: str | None = None,
    resolution_status: str = "not_required",
    resolved_url: str | None = None,
) -> dict[str, Any]:
    """Insert unique hits as discovered candidates. Caller commits or we commit."""
    rid = run_id or uuid.uuid4().hex[:16]
    if run_id is None:
        session.add(IngestRun(run_id=rid, note=note or f"{discovery_method}:{source_id}"))
    inserted = 0
    skipped = 0
    seen: set[str] = set()
    for hit in hits:
        url = (hit.get("url") or "").strip()
        if not url:
            skipped += 1
            continue
        h = url_hash(url)
        if h in seen:
            skipped += 1
            continue
        exists = session.scalar(select(ReviewCandidate).where(ReviewCandidate.url_hash == h))
        if exists:
            skipped += 1
            continue
        seen.add(h)
        pub = hit.get("published_at")
        if isinstance(pub, str):
            try:
                pub = datetime.fromisoformat(pub.replace("Z", "+00:00"))
            except ValueError:
                pub = None
        session.add(
            ReviewCandidate(
                run_id=rid,
                provider=provider,
                query=hit.get("query") or f"{discovery_method}:{source_id}",
                original_url=url,
                canonical_url=normalize_url(url),
                url_hash=h,
                title=(hit.get("title") or url)[:1024],
                snippet=(hit.get("snippet") or "")[:2000],
                language=language,
                source_domain=urlparse(url).netloc or source_domain,
                source_id=source_id,
                status="discovered",
                fetch_status="not_attempted",
                discovery_method=discovery_method,
                resolution_status=hit.get("resolution_status") or resolution_status,
                resolved_url=hit.get("resolved_url") or resolved_url,
                published_at=pub,
                raw_search_json=json.dumps(hit, ensure_ascii=False, default=str),
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
        )
        inserted += 1
    session.commit()
    return {
        "source_id": source_id,
        "run_id": rid,
        "provider": provider,
        "discovery_method": discovery_method,
        "hits": len(hits),
        "inserted": inserted,
        "skipped": skipped,
        "skipped_source": False,
    }
