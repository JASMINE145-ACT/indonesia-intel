"""Prefer-source extension smoke: site-search → fetch → local usability.

Contract: WANd.INTEL.SOURCE_EXTEND.001
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ReviewCandidate
from dedup.url import normalize_url, url_hash
from fetch.content_validity import assess_extracted_page, classify_exception
from jobs.fetch_candidates import fetch_discovered_candidates
from providers.base import SearchProvider, SearchResult
from sources.registry import SourceRegistry
from storage.blob import LocalBlobStore


def classify_fetch_outcome(
    *,
    status: str,
    text_len: int,
    title: str,
    error_hint: str = "",
    fetch_status: str | None = None,
) -> str:
    """Map a candidate row to a stable extension failure class."""
    hint = (error_hint or "").lower()
    # Normalize content-validity / classifier aliases → documented set
    aliases = {
        "waf_blocked": "waf",
        "cloudflare_challenge": "waf",
        "javascript_shell": "empty",
        "certificate_failure": "cert",
        "dns_failure": "dns",
        "http_403": "waf",
        "http_401": "paywall",
        "empty_extraction": "empty",
        "insufficient_content": "empty",
    }
    for key, mapped in aliases.items():
        if key in hint:
            return mapped
    if "certificate" in hint or "ssl" in hint:
        return "cert"
    if "dns" in hint:
        return "dns"
    if "403" in hint or "waf" in hint or "blocked" in hint or "cloudflare" in hint:
        return "waf"
    if "401" in hint or "paywall" in hint or "login" in hint:
        return "paywall"
    if fetch_status == "failed":
        return "fetch_fail"
    if status == "pending_review" and text_len >= 80 and (title or "").strip():
        return "ok"
    if status == "pending_review":
        return "empty"
    if status == "fetch_failed":
        return "fetch_fail"
    return "other"


def _domain_match(url: str, domain: str) -> bool:
    host = (urlparse(url).netloc or "").lower().removeprefix("www.")
    d = domain.lower().removeprefix("www.")
    return host == d or host.endswith("." + d)


async def run_source_smoke(
    session: Session,
    blob: LocalBlobStore,
    *,
    registry: SourceRegistry,
    source_id: str,
    provider: SearchProvider,
    query: str,
    html_overrides: dict[str, bytes] | None = None,
    resolve_dns: bool = True,
    enable_l2: bool | None = None,
    limit: int = 5,
) -> dict[str, Any]:
    """Search site:{domain} + query → fetch → classify usable local articles."""
    src = registry.assert_fetch_allowed(source_id)
    q = f"site:{src.domain} {query}".strip()
    hits: list[SearchResult] = await provider.search(q)
    filtered = [h for h in hits if _domain_match(h.url, src.domain)][:limit]

    summary: dict[str, Any] = {
        "tested_at": datetime.now(timezone.utc).isoformat(),
        "source_id": src.id,
        "domain": src.domain,
        "fetch_mode": src.fetch_mode,
        "query": q,
        "provider": getattr(provider, "name", type(provider).__name__),
        "hits": len(filtered),
        "usable_n": 0,
        "pipeline": "no_hits",
        "outcomes": [],
        "samples": [],
    }
    if not filtered:
        summary["pipeline"] = "no_hits"
        return summary

    rid = f"smoke-{src.id}-{datetime.now(timezone.utc).strftime('%H%M%S')}"
    for h in filtered:
        session.add(
            ReviewCandidate(
                run_id=rid,
                provider=h.provider,
                query=q,
                original_url=h.url,
                canonical_url=normalize_url(h.url),
                url_hash=url_hash(h.url),
                title=h.title or "",
                snippet=h.snippet or "",
                source_domain=h.source_domain,
                source_id=src.id,
                status="discovered",
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
        )
    session.commit()

    fetch = fetch_discovered_candidates(
        session,
        blob,
        limit=limit,
        resolve_dns=resolve_dns,
        html_overrides=html_overrides,
        enable_l2=enable_l2,
        run_id=rid,
    )
    summary["fetch"] = {
        k: fetch[k] for k in ("fetched", "failed", "total", "l2_used") if k in fetch
    }

    usable = 0
    outcomes: list[str] = []
    samples: list[dict[str, Any]] = []
    rows = list(
        session.scalars(select(ReviewCandidate).where(ReviewCandidate.run_id == rid))
    )
    for row in rows:
        text_len = len(row.extracted_text or "")
        title = (row.title or "").strip()
        err = row.fetch_error_type or row.snippet or ""
        hint = err
        status = row.status
        if row.status == "pending_review" and row.object_key:
            try:
                raw = blob.get_bytes(row.object_key)[:20000]
            except FileNotFoundError:
                raw = b""
            v = assess_extracted_page(title=title, text=row.extracted_text, html=raw)
            if not v.ok:
                status = "fetch_failed"
                hint = v.error_type or v.detail or err
        cls = classify_fetch_outcome(
            status=status,
            text_len=text_len,
            title=title,
            error_hint=hint,
            fetch_status=getattr(row, "fetch_status", None),
        )
        outcomes.append(cls)
        if cls == "ok":
            usable += 1
            samples.append(
                {
                    "title": title[:120],
                    "url": row.canonical_url,
                    "text_len": text_len,
                    "blob": row.object_key,
                }
            )

    summary["usable_n"] = usable
    summary["outcomes"] = outcomes
    summary["samples"] = samples[:5]
    summary["pipeline"] = "ok" if usable else "fetch_fail"
    return summary


def summarize_exception(exc: BaseException) -> dict[str, str]:
    return {
        "error_type": classify_exception(exc),
        "detail": f"{type(exc).__name__}: {exc}"[:300],
    }


def dump_summary(summary: dict[str, Any]) -> str:
    return json.dumps(summary, ensure_ascii=False, indent=2)
