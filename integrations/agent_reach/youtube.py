"""YouTube Data API v3 search — optional key; no Exa/Tavily."""

from __future__ import annotations

from typing import Any, Callable

import httpx

from integrations.agent_reach.constants import (
    DISCOVERY_METHOD,
    REASON_HOST_NOT_ALLOWED,
    REASON_YOUTUBE_HTTP,
    REASON_YOUTUBE_MISSING_KEY,
    REASON_YOUTUBE_QUOTA,
)
from integrations.agent_reach.hosts import host_allowed
from integrations.agent_reach.types import SocialHit, SocialSearchOutcome

YOUTUBE_SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"

# (url, params) — params may include key; callers must not log params
HttpGet = Callable[[str, dict[str, Any]], Any]


def _sanitize_raw(item: dict[str, Any]) -> dict[str, Any]:
    """Drop secrets; keep only public snippet/id fields for audit JSON."""
    snippet = item.get("snippet") or {}
    vid = (item.get("id") or {}).get("videoId")
    return {
        "videoId": vid,
        "title": snippet.get("title"),
        "description": (snippet.get("description") or "")[:500],
        "channelTitle": snippet.get("channelTitle"),
        "publishedAt": snippet.get("publishedAt"),
    }


def search_youtube(
    query: str,
    *,
    api_key: str,
    max_results: int = 10,
    http_get: HttpGet | None = None,
) -> SocialSearchOutcome:
    provider = "youtube"
    method = DISCOVERY_METHOD[provider]
    key = (api_key or "").strip()
    if not key:
        return SocialSearchOutcome(
            ok=False,
            reason=REASON_YOUTUBE_MISSING_KEY,
            provider=provider,
            discovery_method=method,
        )

    params = {
        "part": "snippet",
        "type": "video",
        "q": query,
        "maxResults": max(1, min(int(max_results), 25)),
        "key": key,
    }

    try:
        if http_get is not None:
            resp = http_get(YOUTUBE_SEARCH_URL, params)
        else:
            with httpx.Client(timeout=30.0) as client:
                resp = client.get(YOUTUBE_SEARCH_URL, params=params)
        status = int(getattr(resp, "status_code", 0) or 0)
        if status == 403:
            body = ""
            try:
                body = (resp.text or "").lower()
            except Exception:  # noqa: BLE001
                body = ""
            reason = REASON_YOUTUBE_QUOTA if "quota" in body else REASON_YOUTUBE_HTTP
            return SocialSearchOutcome(
                ok=False,
                reason=reason,
                provider=provider,
                discovery_method=method,
            )
        if status == 429:
            return SocialSearchOutcome(
                ok=False,
                reason=REASON_YOUTUBE_QUOTA,
                provider=provider,
                discovery_method=method,
            )
        if status >= 400 or status == 0:
            return SocialSearchOutcome(
                ok=False,
                reason=REASON_YOUTUBE_HTTP,
                provider=provider,
                discovery_method=method,
            )
        data = resp.json()
    except Exception:  # noqa: BLE001
        return SocialSearchOutcome(
            ok=False,
            reason=REASON_YOUTUBE_HTTP,
            provider=provider,
            discovery_method=method,
        )

    hits: list[SocialHit] = []
    rejected_host = 0
    for item in data.get("items") or []:
        vid = (item.get("id") or {}).get("videoId")
        if not vid:
            continue
        watch = f"https://www.youtube.com/watch?v={vid}"
        if not host_allowed(watch):
            rejected_host += 1
            continue
        sn = item.get("snippet") or {}
        hits.append(
            SocialHit(
                url=watch,
                title=(sn.get("title") or watch)[:1024],
                snippet=(sn.get("description") or "")[:2000],
                query=query,
                raw=_sanitize_raw(item),
            )
        )

    if not hits and rejected_host:
        return SocialSearchOutcome(
            ok=False,
            reason=REASON_HOST_NOT_ALLOWED,
            provider=provider,
            discovery_method=method,
            hits=[],
        )

    return SocialSearchOutcome(
        ok=True,
        reason=None,
        provider=provider,
        discovery_method=method,
        hits=hits,
    )
