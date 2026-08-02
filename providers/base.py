from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class SearchResult(BaseModel):
    """Unified search hit — WANd.INTEL.SEARCH_PROVIDER.001"""

    provider: str
    query: str
    title: str
    url: str
    snippet: str = ""
    published_at: datetime | None = None
    source_domain: str | None = None
    language: str | None = None
    provider_rank: int | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class SearchProvider(ABC):
    name: str

    @abstractmethod
    async def search(
        self,
        query: str,
        *,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        language: str | None = None,
        country: str | None = None,
    ) -> list[SearchResult]:
        raise NotImplementedError
