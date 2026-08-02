from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

from providers.base import SearchProvider, SearchResult


def map_exa_results(query: str, response: Any, *, language: str | None = None) -> list[SearchResult]:
    """Map Exa SDK response → unified SearchResult list (WANd.INTEL.EXA.001)."""
    results: list[SearchResult] = []
    for i, item in enumerate(getattr(response, "results", []) or [], start=1):
        pub = None
        published = getattr(item, "published_date", None)
        if published:
            try:
                pub = datetime.fromisoformat(str(published).replace("Z", "+00:00"))
            except (ValueError, TypeError):
                pass
        url = getattr(item, "url", "") or ""
        if not url:
            continue
        text = getattr(item, "text", None) or getattr(item, "snippet", "") or ""
        results.append(
            SearchResult(
                provider="exa",
                query=query,
                title=getattr(item, "title", None) or url,
                url=url,
                snippet=str(text)[:500],
                published_at=pub,
                source_domain=urlparse(url).netloc,
                language=language,
                provider_rank=i,
                raw={
                    "id": getattr(item, "id", None),
                    "score": getattr(item, "score", None),
                },
            )
        )
    return results


class ExaSearchProvider(SearchProvider):
    """Exa.ai search — primary path when EXA_API_KEY is set."""

    name = "exa"

    def __init__(self, api_key: str, *, client: Any | None = None) -> None:
        if not api_key and client is None:
            raise ValueError("EXA_API_KEY required for ExaSearchProvider")
        self.api_key = api_key
        self._client = client

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        from exa_py import Exa

        return Exa(api_key=self.api_key)

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
            "num_results": 20,
            "type": "auto",
            "text": True,
        }
        if date_from:
            kwargs["start_published_date"] = date_from.strftime("%Y-%m-%d")
        if date_to:
            kwargs["end_published_date"] = date_to.strftime("%Y-%m-%d")

        def _call() -> Any:
            return client.search_and_contents(query, **kwargs)

        response = await asyncio.to_thread(_call)
        return map_exa_results(query, response, language=language)
