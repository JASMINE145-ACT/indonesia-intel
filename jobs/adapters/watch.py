"""Page-change watch discovery — WANd.INTEL.WATCH_ADAPTER.001.

Opt-in via INTEL_DISCOVERY_WATCH (default off). On content-hash change, inserts
one discovered candidate for the watched URL (same url_hash dedupe as listing).
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

import httpx
from lxml import html as lxml_html
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import SourceWatchState
from fetch.ssrf import assert_safe_url
from jobs.adapters.common import insert_discovered_hits
from jobs.adapters.sitemap import fetch_bytes
from sources.registry import SourceEntry


def source_has_watch_config(source: SourceEntry) -> bool:
    return bool((source.watch_url or "").strip())


def content_fingerprint(raw: bytes | str, *, selector: str = "") -> str:
    """Hash scoped text (or full body) for change detection."""
    if isinstance(raw, str):
        raw_b = raw.encode("utf-8", errors="replace")
    else:
        raw_b = raw
    sel = (selector or "").strip()
    if not sel:
        return hashlib.sha256(raw_b).hexdigest()
    try:
        doc = lxml_html.fromstring(raw_b)
        nodes = doc.cssselect(sel)
    except Exception:  # noqa: BLE001 — bad selector / parse
        return hashlib.sha256(raw_b).hexdigest()
    if not nodes:
        return hashlib.sha256(raw_b).hexdigest()
    text = "\n".join((n.text_content() or "").strip() for n in nodes)
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def poll_watch_source(
    session: Session,
    source: SourceEntry,
    *,
    client: httpx.Client | None = None,
    resolve_dns: bool = True,
    html_override: bytes | None = None,
) -> dict[str, Any]:
    watch_url = (source.watch_url or "").strip()
    if not watch_url:
        return {
            "source_id": source.id,
            "skipped": True,
            "reason": "watch not configured",
            "discovery_method": "watch",
            "provider": "watch",
            "inserted": 0,
            "hits": 0,
        }
    if html_override is None:
        assert_safe_url(watch_url, resolve_dns=resolve_dns)
    try:
        raw = (
            html_override
            if html_override is not None
            else fetch_bytes(watch_url, client=client, resolve_dns=resolve_dns)
        )
        new_hash = content_fingerprint(raw, selector=(source.watch_selector or "").strip())
    except Exception as exc:  # noqa: BLE001
        return {
            "source_id": source.id,
            "error": str(exc)[:300],
            "discovery_method": "watch",
            "provider": "watch",
            "inserted": 0,
            "hits": 0,
        }

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    state = session.scalar(
        select(SourceWatchState).where(SourceWatchState.source_id == source.id)
    )
    changed = False
    if state is None:
        state = SourceWatchState(
            source_id=source.id,
            watch_url=watch_url,
            content_hash=new_hash,
            last_checked_at=now,
            last_changed_at=None,
            updated_at=now,
        )
        session.add(state)
        # First observe establishes baseline — no candidate insert.
        session.commit()
        return {
            "source_id": source.id,
            "discovery_method": "watch",
            "provider": "watch",
            "inserted": 0,
            "hits": 0,
            "changed": False,
            "baseline": True,
        }

    state.last_checked_at = now
    state.watch_url = watch_url
    state.updated_at = now
    if state.content_hash != new_hash:
        changed = True
        state.content_hash = new_hash
        state.last_changed_at = now
    if not changed:
        session.commit()
        return {
            "source_id": source.id,
            "discovery_method": "watch",
            "provider": "watch",
            "inserted": 0,
            "hits": 0,
            "changed": False,
        }

    title = f"Watch change: {source.name or source.id}"
    hits = [
        {
            "url": watch_url,
            "title": title[:1024],
            "snippet": f"content_hash={new_hash[:16]}",
            "query": f"watch:{source.id}",
        }
    ]
    summary = insert_discovered_hits(
        session,
        hits,
        source_id=source.id,
        provider="watch",
        discovery_method="watch",
        language=source.language or None,
        source_domain=source.domain,
        note=f"watch:{source.id}",
    )
    summary["changed"] = True
    summary["baseline"] = False
    return summary
