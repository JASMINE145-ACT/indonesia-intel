"""RSS poll + MCP search/fetch — Phase 2."""

from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import ReviewCandidate
from jobs.poll_rss import parse_rss_items, poll_rss_source
from mcp_server import service
from mcp_server.server import mcp
from sources.registry import SourceEntry


FIXTURE_RSS = b"""<?xml version="1.0"?>
<rss version="2.0"><channel>
<title>Test</title>
<item>
  <title>Chinese EV plant in Indonesia</title>
  <link>https://example.com/rss/ev-plant</link>
  <description>Investment news</description>
  <pubDate>Mon, 01 Jan 2026 12:00:00 GMT</pubDate>
</item>
<item>
  <title>Duplicate URL</title>
  <link>https://example.com/rss/ev-plant</link>
</item>
</channel></rss>
"""


def _session(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'rss.db'}",
        future=True,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)()


def test_parse_rss_items() -> None:
    items = parse_rss_items(FIXTURE_RSS)
    assert len(items) == 2
    assert items[0]["url"].startswith("https://")
    assert "EV" in items[0]["title"]


def test_poll_rss_inserts_discovered(tmp_path) -> None:
    session = _session(tmp_path)
    src = SourceEntry(
        id="fixture_rss",
        name="Fixture",
        domain="example.com",
        fetch_mode="rss",
        rss_url="https://example.com/feed.xml",
        enabled=True,
        region="ID",
    )
    summary = poll_rss_source(session, src, xml_override=FIXTURE_RSS)
    assert summary["hits"] == 2
    assert summary["inserted"] == 1  # dup URL skipped
    assert summary["provider"] == "rss"
    rows = list(session.scalars(select(ReviewCandidate)))
    assert len(rows) == 1
    assert rows[0].provider == "rss"
    assert rows[0].source_id == "fixture_rss"
    assert rows[0].status == "discovered"
    assert rows[0].fetch_status == "not_attempted"
    assert rows[0].discovery_method == "rss"
    assert rows[0].resolution_status == "not_required"
    assert rows[0].published_at is not None


def test_mcp_phase2_tools_registered() -> None:
    names = set(mcp._tool_manager._tools.keys())  # noqa: SLF001
    assert "intel_poll_sources" in names
    assert "intel_search" in names
    assert "intel_fetch" in names
    for name in ("intel_poll_sources", "intel_search", "intel_fetch"):
        tool = mcp._tool_manager._tools[name]  # noqa: SLF001
        params = set((tool.parameters or {}).get("properties", {}).keys())
        assert not (params & service.FORBIDDEN_TOOL_PARAM_NAMES)


def test_intel_search_mock(tmp_path, monkeypatch) -> None:
    from app import db as dbmod

    engine = create_engine(
        f"sqlite:///{tmp_path / 's.db'}",
        future=True,
        connect_args={"check_same_thread": False},
    )
    dbmod.engine = engine
    dbmod.SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    Base.metadata.create_all(engine)
    monkeypatch.setattr("app.config.settings.exa_api_key", "")
    monkeypatch.setattr("app.config.settings.tavily_api_key", "")

    out = service.intel_search("China Indonesia", provider="mock")
    assert out["provider"] == "brave_mock"
    assert out["inserted"] >= 1
    assert "L2" in out["cascade"]


@pytest.mark.asyncio
async def test_intel_search_from_running_event_loop(tmp_path, monkeypatch) -> None:
    """D6: FastMCP owns a loop — intel_search must not raise RuntimeError via asyncio.run."""
    from app import db as dbmod

    engine = create_engine(
        f"sqlite:///{tmp_path / 'loop.db'}",
        future=True,
        connect_args={"check_same_thread": False},
    )
    dbmod.engine = engine
    dbmod.SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    Base.metadata.create_all(engine)
    monkeypatch.setattr("app.config.settings.exa_api_key", "")
    monkeypatch.setattr("app.config.settings.tavily_api_key", "")
    monkeypatch.setattr("app.config.settings.query_expand_enabled", False)

    out = service.intel_search("China Indonesia", provider="mock")
    assert out["inserted"] >= 1
    assert out["run_id"]


def test_intel_fetch_after_search(tmp_path, monkeypatch) -> None:
    from app import db as dbmod
    import jobs.fetch_candidates as fc

    engine = create_engine(
        f"sqlite:///{tmp_path / 'f.db'}",
        future=True,
        connect_args={"check_same_thread": False},
    )
    dbmod.engine = engine
    dbmod.SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    Base.metadata.create_all(engine)
    monkeypatch.setattr("app.config.settings.blob_root", str(tmp_path / "blobs"))

    with dbmod.SessionLocal() as session:
        session.add(
            ReviewCandidate(
                run_id="f1",
                provider="mock",
                query="q",
                original_url="https://example.com/f",
                canonical_url="https://example.com/f",
                url_hash="fh1",
                title="T",
                snippet="",
                status="discovered",
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
        )
        session.commit()

    html = b"<html><body><article><p>Factory in Indonesia</p></article></body></html>"

    class Page:
        def __init__(self):
            self.html = html
            self.text = "Factory in Indonesia"
            self.title = "Plant"
            self.final_url = "https://example.com/f"

    monkeypatch.setattr(fc, "fetch_and_extract", lambda *a, **k: Page())
    out = service.intel_fetch(limit=10)
    assert out["fetched"] == 1


def test_cascade_mentioned_in_tool_docs() -> None:
    poll = mcp._tool_manager._tools["intel_poll_sources"]  # noqa: SLF001
    search = mcp._tool_manager._tools["intel_search"]  # noqa: SLF001
    assert "L1" in (poll.description or "")
    assert "L2" in (search.description or "")
