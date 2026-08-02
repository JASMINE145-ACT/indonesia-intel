from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from providers.base import SearchProvider, SearchResult


def map_tavily_results(
    query: str, response: dict[str, Any], *, language: str | None = None
) -> list[SearchResult]:
    """Map Tavily SDK response → unified SearchResult list (WANd.INTEL.TAVILY.001)."""
    results: list[SearchResult] = []
    for i, item in enumerate(response.get("results", []) or [], start=1):
        url = item.get("url") or ""
        if not url:
            continue
        pub = None
        if item.get("published_date"):
            try:
                pub = datetime.fromisoformat(str(item["published_date"]).replace("Z", "+00:00"))
            except (ValueError, TypeError):
                pass
        results.append(
            SearchResult(
                provider="tavily",
                query=query,
                title=item.get("title") or url,
                url=url,
                snippet=(item.get("content") or "")[:500],
                published_at=pub,
                source_domain=urlparse(url).netloc,
                language=language,
                provider_rank=i,
                raw={"score": item.get("score")},
            )
        )
    return results


class TavilySearchProvider(SearchProvider):
    """Tavily search — primary path when TAVILY_API_KEY is set (and no Exa default)."""

    name = "tavily"

    def __init__(self, api_key: str, *, client: Any | None = None) -> None:
        if not api_key and client is None:
            raise ValueError("TAVILY_API_KEY required for TavilySearchProvider")
        self.api_key = api_key
        self._client = client

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        from tavily import TavilyClient

        return TavilyClient(api_key=self.api_key)

    async def search(
        self,
        query: str,
        *,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        language: str | None = None,
        country: str | None = None,
    ) -> list[SearchResult]:
        client = self._get_client()
        kwargs: dict = {
            "max_results": 20,
            "search_depth": "advanced",
            "include_raw_content": False,
        }
        if date_from:
            now = datetime.now(timezone.utc)
            if date_from.tzinfo is None:
                start = date_from.replace(tzinfo=timezone.utc)
            else:
                start = date_from
            kwargs["days"] = max(1, (now - start).days)

        def _call() -> dict:
            return client.search(query, **kwargs)

        response = await asyncio.to_thread(_call)
        return map_tavily_results(query, response, language=language)
