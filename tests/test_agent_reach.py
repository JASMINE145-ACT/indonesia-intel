"""Agent Reach social — WANd.INTEL.AGENT_REACH_SOCIAL.001."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import ReviewCandidate
from fetch.content_validity import is_social_host
from integrations.agent_reach.constants import (
    REASON_LINKEDIN_CREDS,
    REASON_REACH_DISABLED,
    REASON_YOUTUBE_MISSING_KEY,
    REASON_YOUTUBE_QUOTA,
)
from integrations.agent_reach.hosts import host_allowed
from integrations.agent_reach.search import search_social
from integrations.agent_reach.youtube import search_youtube
from jobs.ingest_reach import run_reach_ingest
from mcp_server import service
from mcp_server.server import mcp


def _wire(tmp_path, monkeypatch):
    from app import db as dbmod

    engine = create_engine(
        f"sqlite:///{tmp_path / 'reach.db'}",
        future=True,
        connect_args={"check_same_thread": False},
    )
    dbmod.engine = engine
    dbmod.SessionLocal = sessionmaker(
        bind=engine, autoflush=False, autocommit=False, future=True
    )
    Base.metadata.create_all(engine)
    monkeypatch.setenv("INTEL_REACH_ENABLED", "1")
    return dbmod.SessionLocal


def test_host_allowlist_discovery_side_only() -> None:
    assert host_allowed("https://www.youtube.com/watch?v=abc")
    assert host_allowed("https://m.youtube.com/watch?v=abc")
    assert host_allowed("https://youtu.be/abc")
    assert host_allowed("https://www.linkedin.com/posts/x")
    assert not host_allowed("https://example.com/a")
    # Must not change fetch social stub list
    assert is_social_host("https://www.instagram.com/p/x")
    assert not is_social_host("https://www.youtube.com/watch?v=abc")
    assert not is_social_host("https://www.linkedin.com/in/x")


def test_youtube_missing_key() -> None:
    out = search_youtube("China Indonesia", api_key="")
    assert out.ok is False
    assert out.reason == REASON_YOUTUBE_MISSING_KEY
    assert out.hits == []


def test_youtube_quota_typed(monkeypatch) -> None:
    def fake_get(url, params):
        assert params.get("key") == "secret-key-should-not-leak"
        return SimpleNamespace(
            status_code=403,
            text='{"error":{"errors":[{"reason":"quotaExceeded"}]}}',
            json=lambda: {},
        )

    out = search_youtube("q", api_key="secret-key-should-not-leak", http_get=fake_get)
    assert out.ok is False
    assert out.reason == REASON_YOUTUBE_QUOTA
    assert "secret-key" not in repr(out)
    assert "secret-key" not in str(out.reason)


def test_youtube_mock_hits_filtered() -> None:
    payload = {
        "items": [
            {
                "id": {"videoId": "vid1"},
                "snippet": {
                    "title": "FDI talk",
                    "description": "China Indonesia",
                    "channelTitle": "Ch",
                    "publishedAt": "2026-01-01T00:00:00Z",
                },
            }
        ]
    }

    def fake_get(url, params):
        assert "key" in params
        assert url.startswith("https://www.googleapis.com/")
        return SimpleNamespace(status_code=200, text="{}", json=lambda: payload)

    out = search_youtube("q", api_key="secret", http_get=fake_get)
    assert out.ok is True
    assert len(out.hits) == 1
    assert out.hits[0].url.startswith("https://www.youtube.com/watch")
    assert "secret" not in repr(out.hits[0].raw)
    assert out.discovery_method == "reach_youtube"


def test_linkedin_stub() -> None:
    out = search_social("anything", "linkedin")
    assert out.ok is False
    assert out.reason == REASON_LINKEDIN_CREDS
    assert out.hits == []


def test_flag_off_zero_insert(tmp_path, monkeypatch) -> None:
    SessionLocal = _wire(tmp_path, monkeypatch)
    monkeypatch.setenv("INTEL_REACH_ENABLED", "0")
    with SessionLocal() as session:
        out = run_reach_ingest(session, "q", provider="youtube", youtube_api_key="k")
    assert out["ok"] is False
    assert out["reason"] == REASON_REACH_DISABLED
    assert out["inserted"] == 0


def test_ingest_youtube_mock_inserts(tmp_path, monkeypatch) -> None:
    SessionLocal = _wire(tmp_path, monkeypatch)
    payload = {
        "items": [
            {
                "id": {"videoId": "abc123"},
                "snippet": {"title": "T", "description": "D"},
            }
        ]
    }

    def fake_get(url, params=None):
        return SimpleNamespace(status_code=200, text="{}", json=lambda: payload)

    with SessionLocal() as session:
        out = run_reach_ingest(
            session,
            "China Indonesia park",
            provider="youtube",
            youtube_api_key="SECRET_YT_KEY_XYZ",
            http_get=fake_get,
        )
        assert out["ok"] is True
        assert out["inserted"] == 1
        assert out["discovery_method"] == "reach_youtube"
        row = session.scalar(select(ReviewCandidate))
        assert row is not None
        assert row.status == "discovered"
        assert row.discovery_method == "reach_youtube"
        assert row.provider == "youtube"
        assert "SECRET_YT_KEY_XYZ" not in (row.raw_search_json or "")


def test_mcp_tool_registered() -> None:
    names = set(mcp._tool_manager._tools.keys())  # noqa: SLF001
    assert "intel_search_social" in names


def test_mcp_flag_off(tmp_path, monkeypatch) -> None:
    _wire(tmp_path, monkeypatch)
    monkeypatch.setenv("INTEL_REACH_ENABLED", "0")
    out = service.intel_search_social("q", provider="youtube")
    assert out["ok"] is False
    assert out["reason"] == REASON_REACH_DISABLED
    assert out["inserted"] == 0


def test_reach_module_has_no_confirm_symbols() -> None:
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "integrations" / "agent_reach"
    for path in root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "intel_confirm" not in text
        assert "confirm_candidate" not in text
