from __future__ import annotations

import json
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urlparse

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import IngestRun, ReviewCandidate
from dedup.url import normalize_url, url_hash
from fetch.ssrf import assert_safe_url
from sources.registry import SourceEntry
from sources.store import load_merged

DEFAULT_MAX_RSS_BYTES = 2_000_000

_RSS_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; indonesia-intel/1.0; +local-research; RSS poll)"
    ),
    "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*",
}


def _text(el: ET.Element | None) -> str:
    if el is None or el.text is None:
        return ""
    return el.text.strip()


def parse_rss_items(xml_bytes: bytes, *, limit: int = 50) -> list[dict[str, Any]]:
    """Parse RSS 2.0 / Atom-ish item/entry list into dicts with title/url/snippet/published."""
    root = ET.fromstring(xml_bytes)
    # RSS channel/item
    items = root.findall(".//item")
    if not items:
        # Atom
        ns = {"a": "http://www.w3.org/2005/Atom"}
        items = root.findall(".//{http://www.w3.org/2005/Atom}entry") or root.findall(
            ".//a:entry", ns
        )

    out: list[dict[str, Any]] = []
    for item in items[:limit]:
        title = _text(item.find("title")) or _text(
            item.find("{http://www.w3.org/2005/Atom}title")
        )
        link_el = item.find("link")
        url = ""
        if link_el is not None:
            url = (link_el.get("href") or _text(link_el) or "").strip()
        if not url:
            atom_link = item.find("{http://www.w3.org/2005/Atom}link")
            if atom_link is not None:
                url = (atom_link.get("href") or "").strip()
        if not url:
            continue
        desc = _text(item.find("description")) or _text(
            item.find("{http://www.w3.org/2005/Atom}summary")
        )
        pub_raw = _text(item.find("pubDate")) or _text(
            item.find("{http://www.w3.org/2005/Atom}updated")
        )
        published = None
        if pub_raw:
            try:
                published = parsedate_to_datetime(pub_raw)
            except (TypeError, ValueError, IndexError):
                try:
                    published = datetime.fromisoformat(pub_raw.replace("Z", "+00:00"))
                except ValueError:
                    published = None
        out.append(
            {
                "title": title or url,
                "url": url,
                "snippet": desc[:500],
                "published_at": published.isoformat() if published else None,
            }
        )
    return out


def poll_rss_source(
    session: Session,
    source: SourceEntry,
    *,
    xml_override: bytes | None = None,
    limit: int = 50,
    run_id: str | None = None,
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    """Fetch one RSS source → discovered candidates. provider=rss."""
    if source.fetch_mode != "rss" or not (source.rss_url or "").strip():
        return {
            "source_id": source.id,
            "skipped": True,
            "reason": "not rss-ready",
            "inserted": 0,
            "hits": 0,
        }

    rid = run_id or uuid.uuid4().hex[:16]
    session.add(IngestRun(run_id=rid, note=f"rss:{source.id}"))

    if xml_override is not None:
        xml_bytes = xml_override
    else:
        assert_safe_url(source.rss_url, resolve_dns=True)
        http = client or httpx.Client(
            timeout=30.0, follow_redirects=False, headers=_RSS_HEADERS
        )
        close = client is None
        try:
            current = source.rss_url
            resp = http.get(current)
            hops = 0
            while (
                resp.status_code in {301, 302, 303, 307, 308}
                and resp.headers.get("location")
                and hops < 5
            ):
                loc = resp.headers["location"]
                current = str(httpx.URL(current).join(loc))
                assert_safe_url(current, resolve_dns=True)
                resp = http.get(current)
                hops += 1
            if resp.status_code in {301, 302, 303, 307, 308}:
                raise RuntimeError(f"too many redirects polling rss:{source.id}")
            resp.raise_for_status()
            xml_bytes = resp.content[:DEFAULT_MAX_RSS_BYTES]
        finally:
            if close:
                http.close()

    hits = parse_rss_items(xml_bytes, limit=limit)
    inserted = 0
    skipped = 0
    seen: set[str] = set()
    for hit in hits:
        h = url_hash(hit["url"])
        if h in seen:
            skipped += 1
            continue
        exists = session.scalar(select(ReviewCandidate).where(ReviewCandidate.url_hash == h))
        if exists:
            skipped += 1
            continue
        seen.add(h)
        canon = normalize_url(hit["url"])
        pub = None
        pub_raw = hit.get("published_at")
        if isinstance(pub_raw, str) and pub_raw:
            try:
                pub = datetime.fromisoformat(pub_raw.replace("Z", "+00:00"))
            except ValueError:
                pub = None
        elif isinstance(pub_raw, datetime):
            pub = pub_raw
        session.add(
            ReviewCandidate(
                run_id=rid,
                provider="rss",
                query=f"rss:{source.id}",
                original_url=hit["url"],
                canonical_url=canon,
                url_hash=h,
                title=hit["title"][:1024],
                snippet=hit.get("snippet") or "",
                language=source.language or None,
                source_domain=urlparse(hit["url"]).netloc or source.domain,
                source_id=source.id,
                status="discovered",
                fetch_status="not_attempted",
                discovery_method="rss",
                resolution_status="not_required",
                published_at=pub,
                raw_search_json=json.dumps(hit, ensure_ascii=False),
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
        )
        inserted += 1
    session.commit()
    return {
        "source_id": source.id,
        "run_id": rid,
        "provider": "rss",
        "discovery_method": "rss",
        "hits": len(hits),
        "inserted": inserted,
        "skipped": skipped,
        "skipped_source": False,
    }


def poll_rss_sources(
    session: Session,
    *,
    source_ids: list[str] | None = None,
    limit_per_source: int = 30,
    xml_overrides: dict[str, bytes] | None = None,
) -> dict[str, Any]:
    """Poll all rss-ready prefer sources (or given ids)."""
    reg = load_merged()
    if source_ids:
        targets = []
        for sid in source_ids:
            src = reg.get(sid)
            if src is None:
                continue
            targets.append(src)
    else:
        targets = reg.rss_ready()

    results = []
    total_inserted = 0
    for src in targets:
        try:
            r = poll_rss_source(
                session,
                src,
                xml_override=(xml_overrides or {}).get(src.id),
                limit=limit_per_source,
            )
        except Exception as exc:  # noqa: BLE001
            session.rollback()
            r = {
                "source_id": src.id,
                "error": str(exc),
                "inserted": 0,
                "hits": 0,
            }
        results.append(r)
        total_inserted += int(r.get("inserted") or 0)
    return {
        "sources": len(results),
        "inserted": total_inserted,
        "results": results,
        "cascade": "L1 prefer/RSS",
    }
