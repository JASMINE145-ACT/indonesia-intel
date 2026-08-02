"""Prefer-source poll dispatcher — WANd.INTEL.POLL_DISPATCH.001."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from jobs.adapters.gnews_resolve import apply_resolve_to_candidate, is_google_news_url
from jobs.adapters.listing import poll_listing_source
from jobs.adapters.sitemap import poll_sitemap_source
from jobs.adapters.watch import poll_watch_source, source_has_watch_config
from jobs.discovery_flags import (
    discovery_gnews_resolve_enabled,
    discovery_listing_enabled,
    discovery_sitemap_enabled,
    discovery_watch_enabled,
)
from jobs.poll_rss import poll_rss_source
from sources.registry import SourceEntry, SourceRegistry
from sources.store import load_merged


def source_has_sitemap_config(source: SourceEntry) -> bool:
    return bool((source.sitemap_url or "").strip()) or (
        (source.fetch_mode or "").lower() == "sitemap"
        and bool((source.home_url or "").strip())
    )


def source_has_listing_config(source: SourceEntry) -> bool:
    return bool((source.list_url or source.home_url or "").strip()) and bool(
        (source.item_selector or "").strip()
    )


def discovery_targets(reg: SourceRegistry | None = None) -> list[SourceEntry]:
    """rss_ready ∪ configured sitemap/listing/watch (respect flags + discovery_enabled)."""
    registry = reg or load_merged()
    by_id: dict[str, SourceEntry] = {}
    for src in registry.rss_ready():
        if src.discovery_enabled:
            by_id[src.id] = src
    sitemap_on = discovery_sitemap_enabled()
    listing_on = discovery_listing_enabled()
    watch_on = discovery_watch_enabled()
    for src in registry.enabled():
        if not src.discovery_enabled:
            continue
        if sitemap_on and source_has_sitemap_config(src):
            by_id[src.id] = src
        elif listing_on and source_has_listing_config(src):
            by_id[src.id] = src
        elif watch_on and source_has_watch_config(src):
            by_id[src.id] = src
    return list(by_id.values())


def _dispatch_one(
    session: Session,
    source: SourceEntry,
    *,
    limit: int,
    xml_overrides: dict[str, bytes] | None,
    html_overrides: dict[str, bytes] | None,
) -> dict[str, Any]:
    if not source.discovery_enabled:
        return {
            "source_id": source.id,
            "skipped": True,
            "reason": "discovery_enabled=false",
            "inserted": 0,
            "hits": 0,
        }

    mode = (source.fetch_mode or "").lower()
    xml_ov = (xml_overrides or {}).get(source.id)
    html_ov = (html_overrides or {}).get(source.id)

    # Prefer explicit sitemap config even if mode is list
    if discovery_sitemap_enabled() and (
        mode == "sitemap" or source_has_sitemap_config(source)
    ):
        if source_has_sitemap_config(source) or mode == "sitemap":
            return poll_sitemap_source(
                session,
                source,
                limit=limit,
                resolve_dns=True,
                xml_override=xml_ov,
            )

    if discovery_listing_enabled() and source_has_listing_config(source):
        return poll_listing_source(
            session,
            source,
            limit=limit,
            resolve_dns=True,
            html_override=html_ov,
        )

    if discovery_watch_enabled() and source_has_watch_config(source):
        return poll_watch_source(
            session,
            source,
            resolve_dns=True,
            html_override=html_ov,
        )

    if mode == "rss" or (source.rss_url or "").strip():
        return poll_rss_source(
            session,
            source,
            xml_override=xml_ov,
            limit=limit,
        )

    return {
        "source_id": source.id,
        "skipped": True,
        "reason": "no adapter config",
        "inserted": 0,
        "hits": 0,
    }


def poll_prefer_sources(
    session: Session,
    *,
    source_ids: list[str] | None = None,
    limit_per_source: int = 30,
    xml_overrides: dict[str, bytes] | None = None,
    html_overrides: dict[str, bytes] | None = None,
    resolve_gnews: bool | None = None,
) -> dict[str, Any]:
    """Poll prefer sources via rss|sitemap|listing|watch. Isolates per-source failures."""
    reg = load_merged()
    if source_ids:
        targets = [s for sid in source_ids if (s := reg.get(sid)) is not None]
    else:
        targets = discovery_targets(reg)

    results: list[dict[str, Any]] = []
    total_inserted = 0
    for src in targets:
        try:
            r = _dispatch_one(
                session,
                src,
                limit=limit_per_source,
                xml_overrides=xml_overrides,
                html_overrides=html_overrides,
            )
        except Exception as exc:  # noqa: BLE001
            session.rollback()
            r = {
                "source_id": src.id,
                "error": str(exc)[:300],
                "inserted": 0,
                "hits": 0,
            }
        results.append(r)
        total_inserted += int(r.get("inserted") or 0)

    do_resolve = (
        discovery_gnews_resolve_enabled() if resolve_gnews is None else resolve_gnews
    )
    resolved_n = 0
    if do_resolve:
        from sqlalchemy import select

        from app.models import ReviewCandidate

        budget = [0]
        rows = list(
            session.scalars(
                select(ReviewCandidate).where(
                    ReviewCandidate.status == "discovered",
                    ReviewCandidate.resolution_status.in_(["pending", "not_required"]),
                ).limit(200)
            )
        )
        for row in rows:
            if not is_google_news_url(row.original_url or ""):
                continue
            if row.resolution_status == "not_required":
                row.resolution_status = "pending"
            before = row.resolution_status
            apply_resolve_to_candidate(session, row, max_budget=20, budget_used=budget)
            if row.resolution_status == "resolved":
                resolved_n += 1
            elif before != row.resolution_status:
                pass
        session.commit()

    return {
        "sources": len(results),
        "inserted": total_inserted,
        "results": results,
        "gnews_resolved": resolved_n,
        "cascade": "L1 prefer/rss|sitemap|listing|watch",
    }


# Back-compat alias used by older call sites / docs
poll_sources = poll_prefer_sources
