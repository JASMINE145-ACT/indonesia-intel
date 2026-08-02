"""Listing-page discovery — WANd.INTEL.LISTING_ADAPTER.001."""

from __future__ import annotations

from typing import Any
from urllib.parse import urljoin

import httpx
from lxml import html as lxml_html
from sqlalchemy.orm import Session

from fetch.ssrf import assert_safe_url
from jobs.adapters.common import (
    insert_discovered_hits,
    same_registrable_domain,
    url_path_allowed,
)
from jobs.adapters.sitemap import fetch_bytes
from sources.registry import SourceEntry


def extract_listing_urls(
    page_html: bytes | str,
    *,
    list_url: str,
    item_selector: str,
    url_selector: str,
    title_selector: str = "",
    domain: str,
    include_patterns: list[str] | None = None,
    exclude_patterns: list[str] | None = None,
) -> list[dict[str, str]]:
    doc = lxml_html.fromstring(
        page_html
        if isinstance(page_html, (bytes, bytearray))
        else page_html.encode("utf-8", errors="replace")
    )
    try:
        items = doc.cssselect(item_selector) if item_selector else []
    except Exception:  # noqa: BLE001 — bad selector
        return []
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in items:
        try:
            link_el = item.cssselect(url_selector) if url_selector else []
        except Exception:  # noqa: BLE001
            continue
        el = link_el[0] if link_el else (item if getattr(item, "tag", "") == "a" else None)
        if el is None:
            continue
        href = (el.get("href") or "").strip()
        if not href:
            continue
        abs_url = urljoin(list_url, href)
        if not abs_url.startswith("http"):
            continue
        if not same_registrable_domain(abs_url, domain):
            continue
        if not url_path_allowed(
            abs_url,
            include_patterns=include_patterns,
            exclude_patterns=exclude_patterns,
        ):
            continue
        if abs_url in seen:
            continue
        seen.add(abs_url)
        title = ""
        if title_selector:
            try:
                t_els = item.cssselect(title_selector)
            except Exception:  # noqa: BLE001
                t_els = []
            if t_els:
                title = (t_els[0].text_content() or "").strip()
        if not title:
            title = (el.text_content() or "").strip() or abs_url
        out.append({"url": abs_url, "title": title, "snippet": ""})
    return out


def poll_listing_source(
    session: Session,
    source: SourceEntry,
    *,
    limit: int = 50,
    client: httpx.Client | None = None,
    resolve_dns: bool = True,
    html_override: bytes | None = None,
) -> dict[str, Any]:
    list_url = (source.list_url or source.home_url or "").strip()
    item_sel = (source.item_selector or "").strip()
    url_sel = (source.url_selector or "a").strip()
    if not list_url or not item_sel:
        return {
            "source_id": source.id,
            "skipped": True,
            "reason": "listing not configured",
            "inserted": 0,
            "hits": 0,
        }
    includes = [p.strip() for p in (source.include_patterns or "").split("|") if p.strip()]
    excludes = [p.strip() for p in (source.exclude_patterns or "").split("|") if p.strip()]
    robots_note = "robots_skipped_override"
    if html_override is None:
        from jobs.adapters.robots_util import robots_allows

        allowed, robots_note = robots_allows(list_url, client=client, resolve_dns=resolve_dns)
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
        raw = html_override if html_override is not None else fetch_bytes(
            list_url, client=client, resolve_dns=resolve_dns
        )
        hits = extract_listing_urls(
            raw,
            list_url=list_url,
            item_selector=item_sel,
            url_selector=url_sel,
            title_selector=(source.title_selector or "").strip(),
            domain=source.domain,
            include_patterns=includes or None,
            exclude_patterns=excludes or None,
        )[:limit]
        for h in hits:
            assert_safe_url(h["url"], resolve_dns=resolve_dns)
    except Exception as exc:  # noqa: BLE001
        return {
            "source_id": source.id,
            "error": str(exc)[:300],
            "inserted": 0,
            "hits": 0,
        }
    summary = insert_discovered_hits(
        session,
        hits,
        source_id=source.id,
        provider="listing",
        discovery_method="listing",
        language=source.language or None,
        source_domain=source.domain,
        note=f"listing:{source.id}:{robots_note}",
    )
    summary["robots_note"] = robots_note
    return summary
