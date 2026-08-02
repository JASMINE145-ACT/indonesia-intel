"""Unfetched candidates must expose a full open_url for human self-service."""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import ReviewCandidate
from jobs.ops_dashboard import (
    UNFETCHED_USER_HINT,
    best_open_url,
    candidate_detail,
    is_unfetched,
    list_item_dict,
)


def _session(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'u.db'}",
        future=True,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)()


def test_best_open_url_prefers_resolved() -> None:
    row = ReviewCandidate(
        run_id="r",
        provider="mock",
        query="q",
        original_url="https://news.google.com/articles/ABC",
        canonical_url="https://news.google.com/articles/ABC",
        url_hash="h",
        title="T",
        resolved_url="https://www.esdm.go.id/full/path/article-123",
        status="pending_review",
        fetch_status="failed",
        fetch_error_type="http_403",
    )
    assert best_open_url(row) == "https://www.esdm.go.id/full/path/article-123"
    assert is_unfetched(row) is True


def test_list_item_dict_unfetched_exposes_full_url_and_hint(tmp_path) -> None:
    session = _session(tmp_path)
    full = "https://www.kemendag.go.id/berita/very-long-article-slug-that-must-not-be-cut"
    row = ReviewCandidate(
        run_id="r1",
        provider="listing",
        query="q",
        original_url=full,
        canonical_url=full,
        url_hash="h1",
        title="无法抓取的资讯",
        snippet="sn",
        status="pending_review",
        fetch_status="failed",
        fetch_error_type="waf_block",
        source_id="kemendag",
    )
    session.add(row)
    session.commit()

    item = list_item_dict(row)
    assert item["unfetched"] is True
    assert item["open_url"] == full
    assert item["url"] == full
    assert item["user_hint"] == UNFETCHED_USER_HINT
    assert item["body_available"] is False
    assert "截断" not in item["open_url"]


def test_candidate_detail_unfetched_open_url(tmp_path) -> None:
    session = _session(tmp_path)
    row = ReviewCandidate(
        run_id="r2",
        provider="mock",
        query="q",
        original_url="https://example.com/orig",
        canonical_url="https://example.com/canon",
        url_hash="h2",
        title="T2",
        status="fetch_failed",
        fetch_status="failed",
        fetch_error_type="timeout",
        resolved_url="https://example.com/resolved-full-path",
    )
    session.add(row)
    session.commit()
    detail = candidate_detail(session, row.id)
    assert detail["open_url"] == "https://example.com/resolved-full-path"
    assert detail["unfetched"] is True
    assert detail["user_hint"]


def test_intel_list_includes_open_url(tmp_path, monkeypatch) -> None:
    from app import db as dbmod
    from mcp_server import service

    engine = create_engine(
        f"sqlite:///{tmp_path / 'm.db'}",
        future=True,
        connect_args={"check_same_thread": False},
    )
    dbmod.engine = engine
    dbmod.SessionLocal = sessionmaker(
        bind=engine, autoflush=False, autocommit=False, future=True
    )
    Base.metadata.create_all(engine)
    full = "https://www.kemenperin.go.id/artikel/12345/full-title-here"
    with dbmod.SessionLocal() as session:
        session.add(
            ReviewCandidate(
                run_id="m1",
                provider="mock",
                query="q",
                original_url=full,
                canonical_url=full,
                url_hash="hm",
                title="T",
                snippet="s",
                status="pending_review",
                fetch_status="failed",
                fetch_error_type="empty_body",
            )
        )
        session.commit()

    out = service.intel_list(status="pending_review")
    assert out["count"] == 1
    item = out["items"][0]
    assert item["open_url"] == full
    assert item["unfetched"] is True
    assert item["user_hint"]
