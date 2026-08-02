from __future__ import annotations

import asyncio
import json
import time
import uuid
from datetime import datetime, timezone
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import IngestRun, ReviewCandidate
from dedup.url import normalize_url, url_hash
from providers.base import SearchProvider, SearchResult


def search_result_to_candidate(
    hit: SearchResult,
    *,
    run_id: str,
    source_id: str | None = None,
) -> ReviewCandidate:
    canon = normalize_url(hit.url)
    return ReviewCandidate(
        run_id=run_id,
        provider=hit.provider,
        query=hit.query,
        original_url=hit.url,
        canonical_url=canon,
        url_hash=url_hash(hit.url),
        title=hit.title,
        snippet=hit.snippet or "",
        language=hit.language,
        source_domain=hit.source_domain or urlparse(hit.url).netloc,
        source_id=source_id,
        status="discovered",
        fetch_status="not_attempted",
        raw_search_json=json.dumps(hit.raw, ensure_ascii=False),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


async def run_search_ingest(
    session: Session,
    provider: SearchProvider,
    query: str,
    *,
    source_id: str | None = None,
    run_id: str | None = None,
    create_run: bool = True,
    seen: set[str] | None = None,
    max_results: int | None = None,
) -> dict:
    """Search → insert review_candidates with status=discovered."""
    rid = run_id or uuid.uuid4().hex[:16]
    if create_run:
        session.add(IngestRun(run_id=rid, note=f"query={query}"))
    hits = await provider.search(query)
    if max_results is not None:
        hits = hits[: max(0, int(max_results))]
    inserted = 0
    skipped = 0
    local_seen = seen if seen is not None else set()
    for hit in hits:
        h = url_hash(hit.url)
        if h in local_seen:
            skipped += 1
            continue
        exists = session.scalar(
            select(ReviewCandidate).where(ReviewCandidate.url_hash == h)
        )
        if exists:
            local_seen.add(h)
            skipped += 1
            continue
        local_seen.add(h)
        session.add(search_result_to_candidate(hit, run_id=rid, source_id=source_id))
        inserted += 1
    session.commit()
    return {
        "run_id": rid,
        "query": query,
        "provider": provider.name,
        "hits": len(hits),
        "inserted": inserted,
        "skipped": skipped,
    }


async def run_search_ingest_multi(
    session: Session,
    providers: list[SearchProvider],
    queries: list[str],
    *,
    source_id: str | None = None,
    max_per_query: int = 10,
    timeout_s: float = 30.0,
) -> dict:
    """Union search across providers × query variants; one IngestRun / run_id."""
    if not providers:
        raise ValueError("no search providers")
    qs = [q.strip() for q in queries if (q or "").strip()]
    if not qs:
        raise ValueError("no queries")

    rid = uuid.uuid4().hex[:16]
    note = f"queries={len(qs)};providers={[p.name for p in providers]}"
    session.add(IngestRun(run_id=rid, note=note))
    session.commit()

    seen: set[str] = set()
    errors: list[str] = []
    provider_counts: dict[str, dict[str, int]] = {
        p.name: {"hits": 0, "inserted": 0, "skipped": 0, "errors": 0} for p in providers
    }
    total_hits = 0
    total_inserted = 0
    total_skipped = 0
    t0 = time.perf_counter()

    async def _one(prov: SearchProvider, query: str) -> tuple[str, str, list[SearchResult] | None, str | None]:
        try:
            hits = await asyncio.wait_for(prov.search(query), timeout=timeout_s)
            if max_per_query is not None:
                hits = hits[: max(0, int(max_per_query))]
            return prov.name, query, hits, None
        except Exception as exc:  # noqa: BLE001
            return prov.name, query, None, f"{prov.name}:{type(exc).__name__}: {exc}"[:300]

    tasks = [_one(p, q) for p in providers for q in qs]
    results = await asyncio.gather(*tasks)

    any_success = False
    for pname, query, hits, err in results:
        if err is not None:
            errors.append(err)
            provider_counts[pname]["errors"] += 1
            continue
        any_success = True
        assert hits is not None
        total_hits += len(hits)
        provider_counts[pname]["hits"] += len(hits)
        for hit in hits:
            h = url_hash(hit.url)
            if h in seen:
                total_skipped += 1
                provider_counts[pname]["skipped"] += 1
                continue
            exists = session.scalar(
                select(ReviewCandidate).where(ReviewCandidate.url_hash == h)
            )
            if exists:
                seen.add(h)
                total_skipped += 1
                provider_counts[pname]["skipped"] += 1
                continue
            seen.add(h)
            session.add(search_result_to_candidate(hit, run_id=rid, source_id=source_id))
            total_inserted += 1
            provider_counts[pname]["inserted"] += 1

    session.commit()
    elapsed_ms = int((time.perf_counter() - t0) * 1000)

    if not any_success:
        raise RuntimeError("all search providers failed: " + "; ".join(errors[:5]))

    names = [p.name for p in providers]
    return {
        "run_id": rid,
        "query": qs[0],
        "queries": qs,
        "provider": "+".join(names),
        "providers": provider_counts,
        "hits": total_hits,
        "inserted": total_inserted,
        "skipped": total_skipped,
        "errors": errors,
        "elapsed_ms": elapsed_ms,
    }
