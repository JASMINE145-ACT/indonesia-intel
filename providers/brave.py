from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import urlparse

from providers.base import SearchProvider, SearchResult


class MockBraveProvider(SearchProvider):
    """Deterministic stand-in when no live search keys are configured."""

    name = "brave_mock"

    def __init__(self, fixtures: list[dict] | None = None) -> None:
        self._fixtures = fixtures or [
            {
                "title": "Chinese EV maker expands plant in West Java",
                "url": "https://example.com/news/chinese-ev-west-java",
                "snippet": "A Chinese automaker advances Indonesia assembly plans.",
                "language": "en",
            },
            {
                "title": "Investasi China di Indonesia meningkat",
                "url": "https://example.co.id/berita/investasi-china",
                "snippet": "Proyek manufaktur dan energi menjadi fokus.",
                "language": "id",
            },
        ]

    async def search(
        self,
        query: str,
        *,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        language: str | None = None,
        country: str | None = None,
    ) -> list[SearchResult]:
        results: list[SearchResult] = []
        for i, item in enumerate(self._fixtures, start=1):
            if language and item.get("language") and item["language"] != language:
                continue
            url = item["url"]
            results.append(
                SearchResult(
                    provider=self.name,
                    query=query,
                    title=item["title"],
                    url=url,
                    snippet=item.get("snippet", ""),
                    published_at=datetime.now(timezone.utc),
                    source_domain=urlparse(url).netloc,
                    language=item.get("language"),
                    provider_rank=i,
                    raw=dict(item),
                )
            )
        return results


class BraveNewsProvider(SearchProvider):
    """Live Brave News — optional; not required when Exa/Tavily are configured."""

    name = "brave_news"

    def __init__(self, api_key: str) -> None:
        if not api_key:
            raise ValueError("BRAVE_API_KEY required for live BraveNewsProvider")
        self.api_key = api_key

    async def search(
        self,
        query: str,
        *,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        language: str | None = None,
        country: str | None = None,
    ) -> list[SearchResult]:
        raise NotImplementedError(
            "Live Brave search not available; use provider=exa or provider=tavily"
        )
