"""GNews resolve — WANd.INTEL.GNEWS_RESOLVE.001."""

from datetime import datetime, timezone

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import ReviewCandidate
from dedup.url import normalize_url, url_hash
from jobs.adapters.gnews_resolve import (
    apply_resolve_to_candidate,
    is_google_news_url,
    resolve_google_news_url,
)


def _session(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'gn.db'}",
        future=True,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)()


def _row(**kwargs) -> ReviewCandidate:
    url = kwargs.get("original_url", "https://news.google.com/articles/ABC")
    return ReviewCandidate(
        run_id=kwargs.get("run_id", "r1"),
        provider="search",
        query="q",
        original_url=url,
        canonical_url=normalize_url(url),
        url_hash=url_hash(url),
        title="t",
        snippet="",
        status="discovered",
        fetch_status="not_attempted",
        discovery_method="search",
        resolution_status=kwargs.get("resolution_status", "pending"),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


def test_is_google_news_url() -> None:
    assert is_google_news_url("https://news.google.com/articles/x")
    assert not is_google_news_url("https://www.kompas.com/read/1")


def test_resolve_success(monkeypatch) -> None:
    monkeypatch.setenv("INTEL_DISCOVERY_GNEWS", "1")
    monkeypatch.setattr(
        "jobs.adapters.gnews_resolve.assert_safe_url",
        lambda url, resolve_dns=True: None,
    )

    class FakeMod:
        @staticmethod
        def gnewsdecoder(url, interval=1):
            return {"status": True, "decoded_url": "https://www.example.com/read/1"}

    import sys

    monkeypatch.setitem(sys.modules, "googlenewsdecoder", FakeMod())
    out = resolve_google_news_url("https://news.google.com/articles/ABC")
    assert out["status"] == "resolved"
    assert out["resolved_url"] == "https://www.example.com/read/1"


def test_resolve_failure_keeps_row(tmp_path, monkeypatch) -> None:
    session = _session(tmp_path)
    row = _row()
    session.add(row)
    session.commit()

    monkeypatch.setattr(
        "jobs.adapters.gnews_resolve.resolve_google_news_url",
        lambda url, timeout_s=15.0: {
            "status": "unresolved",
            "resolved_url": None,
            "error": "decode failed",
        },
    )
    apply_resolve_to_candidate(session, row)
    session.commit()
    assert row.status == "discovered"
    assert row.resolution_status == "unresolved"
    assert row.resolved_url is None


def test_resolve_dedupe_against_existing(tmp_path, monkeypatch) -> None:
    session = _session(tmp_path)
    resolved = "https://www.example.com/article/1"
    existing = ReviewCandidate(
        run_id="r0",
        provider="sitemap",
        query="q",
        original_url=resolved,
        canonical_url=normalize_url(resolved),
        url_hash=url_hash(resolved),
        title="existing",
        snippet="",
        status="discovered",
        fetch_status="not_attempted",
        discovery_method="sitemap",
        resolution_status="not_required",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    gnews = _row(original_url="https://news.google.com/articles/XYZ")
    session.add_all([existing, gnews])
    session.commit()

    monkeypatch.setattr(
        "jobs.adapters.gnews_resolve.resolve_google_news_url",
        lambda url, timeout_s=15.0: {
            "status": "resolved",
            "resolved_url": resolved,
            "error": None,
        },
    )
    apply_resolve_to_candidate(session, gnews)
    session.commit()
    assert gnews.status == "ignored"
    assert gnews.resolution_status == "resolved"
    assert gnews.resolved_url == resolved
    assert session.scalar(select(ReviewCandidate).where(ReviewCandidate.id == existing.id))


def test_resolve_dedupe_against_peer_resolved_url(tmp_path, monkeypatch) -> None:
    """AC-04: peer already has same resolved_url (different original wrapper)."""
    session = _session(tmp_path)
    resolved = "https://www.example.com/article/shared"
    peer = _row(original_url="https://news.google.com/articles/PEER1")
    peer.resolved_url = resolved
    peer.resolution_status = "resolved"
    peer.url_hash = url_hash(peer.original_url)
    newbie = _row(original_url="https://news.google.com/articles/PEER2")
    session.add_all([peer, newbie])
    session.commit()

    monkeypatch.setattr(
        "jobs.adapters.gnews_resolve.resolve_google_news_url",
        lambda url, timeout_s=15.0: {
            "status": "resolved",
            "resolved_url": resolved,
            "error": None,
        },
    )
    apply_resolve_to_candidate(session, newbie)
    session.commit()
    assert newbie.status == "ignored"
    assert newbie.resolved_url == resolved
