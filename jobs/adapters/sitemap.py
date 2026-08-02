"""Sitemap discovery via project-owned httpx — WANd.INTEL.SITEMAP_ADAPTER.001."""

from __future__ import annotations

import time
import xml.etree.ElementTree as ET
from typing import Any
from urllib.parse import urlparse

import httpx
from sqlalchemy.orm import Session

from fetch.ssrf import assert_safe_url
from jobs.adapters.common import insert_discovered_hits, same_registrable_domain
from jobs.poll_rss import DEFAULT_MAX_RSS_BYTES, _RSS_HEADERS
from sources.registry import SourceEntry

_DEFAULT_INCLUDE = ("/news/", "/berita/", "/article/", "/read/", "/press", "/ekonomi/")
_DEFAULT_EXCLUDE = ("/tag/", "/author/", "/video/", "/login", "/search")


def _local(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[-1]
    return tag


def _match_patterns(url: str, includes: list[str], excludes: list[str]) -> bool:
    path = urlparse(url).path or "/"
    for ex in excludes:
        if ex and ex in path:
            return False
    if not includes:
        return True
    return any(inc and inc in path for inc in includes)


def parse_sitemap_xml(xml_bytes: bytes) -> tuple[list[str], list[str]]:
    """Return (page_urls, child_sitemap_urls)."""
    root = ET.fromstring(xml_bytes)
    pages: list[str] = []
    children: list[str] = []
    for el in root:
        tag = _local(el.tag)
        if tag == "sitemap":
            for child in el:
                if _local(child.tag) == "loc" and child.text:
                    children.append(child.text.strip())
        elif tag == "url":
            for child in el:
                if _local(child.tag) == "loc" and child.text:
                    pages.append(child.text.strip())
    if not pages and not children:
        for el in root.iter():
            if _local(el.tag) == "loc" and el.text:
                pages.append(el.text.strip())
    return pages, children


def fetch_bytes(
    url: str,
    *,
    client: httpx.Client | None = None,
    resolve_dns: bool = True,
) -> bytes:
    assert_safe_url(url, resolve_dns=resolve_dns)
    http = client or httpx.Client(timeout=30.0, follow_redirects=False, headers=_RSS_HEADERS)
    close = client is None
    try:
        current = url
        resp = http.get(current)
        hops = 0
        while (
            resp.status_code in {301, 302, 303, 307, 308}
            and resp.headers.get("location")
            and hops < 5
        ):
            loc = resp.headers["location"]
            current = str(httpx.URL(current).join(loc))
            assert_safe_url(current, resolve_dns=resolve_dns)
            resp = http.get(current)
            hops += 1
        if resp.status_code in {301, 302, 303, 307, 308}:
            raise RuntimeError(f"too many redirects fetching sitemap: {url}")
        resp.raise_for_status()
        return resp.content[:DEFAULT_MAX_RSS_BYTES]
    finally:
        if close:
            http.close()


def collect_sitemap_urls(
    start_url: str,
    *,
    domain: str,
    include_patterns: list[str] | None = None,
    exclude_patterns: list[str] | None = None,
    max_urls: int = 50,
    max_sitemaps: int = 5,
    client: httpx.Client | None = None,
    resolve_dns: bool = True,
    xml_override: bytes | None = None,
) -> list[str]:
    includes = list(include_patterns) if include_patterns else list(_DEFAULT_INCLUDE)
    excludes = list(exclude_patterns) if exclude_patterns else list(_DEFAULT_EXCLUDE)
    out: list[str] = []
    seen_sm: set[str] = set()
    queue = [start_url]
    first = True
    while queue and len(seen_sm) < max_sitemaps and len(out) < max_urls:
        sm = queue.pop(0)
        if sm in seen_sm:
            continue
        seen_sm.add(sm)
        if first and xml_override is not None:
            raw = xml_override
            first = False
        else:
            raw = fetch_bytes(sm, client=client, resolve_dns=resolve_dns)
            first = False
        pages, children = parse_sitemap_xml(raw)
        for ch in children:
            if same_registrable_domain(ch, domain):
                assert_safe_url(ch, resolve_dns=resolve_dns)
                queue.append(ch)
        for page in pages:
            if not same_registrable_domain(page, domain):
                continue
            assert_safe_url(page, resolve_dns=resolve_dns)
            if not _match_patterns(page, includes, excludes):
                continue
            if page not in out:
                out.append(page)
            if len(out) >= max_urls:
                break
        time.sleep(0.05)
    return out[:max_urls]


def poll_sitemap_source(
    session: Session,
    source: SourceEntry,
    *,
    limit: int = 50,
    client: httpx.Client | None = None,
    resolve_dns: bool = True,
    xml_override: bytes | None = None,
) -> dict[str, Any]:
    start = (source.sitemap_url or source.home_url or "").strip()
    if not start:
        return {
            "source_id": source.id,
            "skipped": True,
            "reason": "sitemap not configured",
            "inserted": 0,
            "hits": 0,
        }
    includes = [p.strip() for p in (source.include_patterns or "").split("|") if p.strip()]
    excludes = [p.strip() for p in (source.exclude_patterns or "").split("|") if p.strip()]
    robots_note = "robots_skipped_override"
    if xml_override is None:
        from jobs.adapters.robots_util import robots_allows

        allowed, robots_note = robots_allows(start, client=client, resolve_dns=resolve_dns)
        if not allowed:
            return {
                "source_id": source.id,
                "skipped": True,
                "reason": robots_note,
                "robots_note": robots_note,
                "inserted": 0,
                "hits": 0,
            }
    try:
        urls = collect_sitemap_urls(
            start,
            domain=source.domain,
            include_patterns=includes or None,
            exclude_patterns=excludes or None,
            max_urls=limit,
            client=client,
            resolve_dns=resolve_dns,
            xml_override=xml_override,
        )
    except Exception as exc:  # noqa: BLE001
        return {
            "source_id": source.id,
            "error": str(exc)[:300],
            "inserted": 0,
            "hits": 0,
        }
    hits = [{"url": u, "title": u, "snippet": ""} for u in urls]
    if not hits and (source.list_url or "").strip() and (source.item_selector or "").strip():
        from jobs.adapters.listing import poll_listing_source

        return poll_listing_source(
            session, source, limit=limit, client=client, resolve_dns=resolve_dns
        )
    summary = insert_discovered_hits(
        session,
        hits,
        source_id=source.id,
        provider="sitemap",
        discovery_method="sitemap",
        language=source.language or None,
        source_domain=source.domain,
        note=f"sitemap:{source.id}:{robots_note}",
    )
    summary["robots_note"] = robots_note
    return summary
