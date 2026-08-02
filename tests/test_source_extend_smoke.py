"""RED/GREEN tests for prefer-source extension smoke (WANd.INTEL.SOURCE_EXTEND.001)."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from jobs.source_smoke import classify_fetch_outcome, run_source_smoke
from providers.brave import MockBraveProvider
from sources.registry import SourceEntry, SourceRegistry
from storage.blob import LocalBlobStore

FIXTURE_HTML = b"""<!doctype html><html><head><title>CN EV Plant Indonesia</title></head>
<body><article><h1>CN EV Plant Indonesia</h1>
<p>A Chinese automaker expands manufacturing capacity in West Java with new investment.</p>
<p>More body text for extraction length requirements in smoke usability checks.</p>
</article></body></html>"""


@pytest.fixture()
def session_blob(tmp_path):
    engine = create_engine(
        f"sqlite:///{(tmp_path / 't.db').as_posix()}",
        future=True,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    blob = LocalBlobStore(tmp_path / "blobs")
    return Session, blob


def test_classify_fetch_outcome_ok() -> None:
    assert classify_fetch_outcome(status="pending_review", text_len=200, title="x") == "ok"


def test_classify_fetch_outcome_empty() -> None:
    assert classify_fetch_outcome(status="pending_review", text_len=5, title="x") == "empty"


def test_source_smoke_mock_search_and_html_override(session_blob) -> None:
    Session, blob = session_blob
    reg = SourceRegistry(
        [
            SourceEntry(
                id="fixture_media",
                name="Fixture",
                domain="example.com",
                fetch_mode="search",
                enabled=True,
                home_url="https://example.com/",
            )
        ]
    )
    provider = MockBraveProvider(
        fixtures=[
            {
                "title": "CN EV Plant Indonesia",
                "url": "https://example.com/news/ev",
                "snippet": "West Java plant",
                "language": "en",
            }
        ]
    )
    with Session() as session:
        summary = asyncio.run(
            run_source_smoke(
                session,
                blob,
                registry=reg,
                source_id="fixture_media",
                provider=provider,
                query="Indonesia investment",
                html_overrides={"https://example.com/news/ev": FIXTURE_HTML},
                resolve_dns=False,
                enable_l2=False,
                limit=3,
            )
        )
    assert summary["source_id"] == "fixture_media"
    assert summary["pipeline"] == "ok"
    assert summary["usable_n"] >= 1
    assert summary["domain"] == "example.com"


def test_source_template_file_exists() -> None:
    path = Path(__file__).resolve().parents[1] / "sources" / "SOURCE_TEMPLATE.yaml"
    assert path.is_file()
    text = path.read_text(encoding="utf-8")
    assert "id:" in text
    assert "domain:" in text
    assert "fetch_mode:" in text
