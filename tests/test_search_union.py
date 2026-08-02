"""WANd.INTEL.SEARCH_UNION.001 / SEARCH_RUN_ID.001"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import IngestRun, ReviewCandidate
from jobs.ingest_search import run_search_ingest_multi
from providers.base import SearchProvider, SearchResult


def _session(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'u.db'}",
        future=True,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)()


class _Prov(SearchProvider):
    def __init__(self, name: str, hits: list[tuple[str, str]], *, fail: bool = False):
        self.name = name
        self._hits = hits
        self._fail = fail

    async def search(self, query: str, **kwargs) -> list[SearchResult]:
        if self._fail:
            raise RuntimeError(f"{self.name} down")
        return [
            SearchResult(
                provider=self.name,
                query=query,
                title=title,
                url=url,
                snippet="s",
                published_at=datetime.now(timezone.utc),
                source_domain="example.com",
            )
            for title, url in self._hits
        ]


@pytest.mark.asyncio
async def test_union_dedupes_same_url_no_integrity_error(tmp_path) -> None:
    session = _session(tmp_path)
    a = _Prov("exa", [("T1", "https://example.com/a")])
    b = _Prov("tavily", [("T1b", "https://example.com/a"), ("T2", "https://example.com/b")])
    summary = await run_search_ingest_multi(
        session,
        [a, b],
        ["q1"],
        max_per_query=10,
    )
    assert summary["inserted"] == 2
    assert summary["skipped"] >= 1
    assert session.scalar(select(func.count()).select_from(ReviewCandidate)) == 2
    assert session.scalar(select(func.count()).select_from(IngestRun)) == 1
    assert summary["run_id"]
    assert "exa" in summary["providers"]
    assert "tavily" in summary["providers"]
    assert summary["provider"] == "exa+tavily"
    assert "run_id" in summary and "hits" in summary and "query" in summary


@pytest.mark.asyncio
async def test_partial_provider_failure_still_inserts(tmp_path) -> None:
    session = _session(tmp_path)
    ok = _Prov("exa", [("Ok", "https://example.com/ok")])
    bad = _Prov("tavily", [], fail=True)
    summary = await run_search_ingest_multi(session, [ok, bad], ["q"], max_per_query=5)
    assert summary["inserted"] == 1
    assert summary["errors"]
    assert any("tavily" in e for e in summary["errors"])


@pytest.mark.asyncio
async def test_all_providers_fail_raises(tmp_path) -> None:
    session = _session(tmp_path)
    a = _Prov("exa", [], fail=True)
    b = _Prov("tavily", [], fail=True)
    with pytest.raises(RuntimeError, match="all search providers failed"):
        await run_search_ingest_multi(session, [a, b], ["q"], max_per_query=5)


@pytest.mark.asyncio
async def test_one_run_id_across_query_variants(tmp_path) -> None:
    session = _session(tmp_path)
    p = _Prov(
        "exa",
        [
            ("A", "https://example.com/1"),
            ("B", "https://example.com/2"),
        ],
    )
    summary = await run_search_ingest_multi(
        session, [p], ["比亚迪", "BYD Indonesia"], max_per_query=10
    )
    runs = list(session.scalars(select(IngestRun)))
    assert len(runs) == 1
    rows = list(session.scalars(select(ReviewCandidate)))
    assert rows
    assert all(r.run_id == summary["run_id"] for r in rows)
    assert summary["queries"] == ["比亚迪", "BYD Indonesia"]
