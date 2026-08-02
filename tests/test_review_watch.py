from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import FormalEvent, ReviewCandidate, ReviewDecision
from jobs.review_actions import confirm_candidate, ignore_candidate, watch_candidate


def _session(tmp_path):
    db = tmp_path / "watch.db"
    engine = create_engine(f"sqlite:///{db}", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)()


def _pending(session, **overrides) -> ReviewCandidate:
    defaults = dict(
        run_id="r1",
        provider="mock",
        query="q",
        original_url="https://example.com/w",
        canonical_url="https://example.com/w",
        url_hash="hash-w",
        title="观察候选",
        snippet="",
        status="pending_review",
        object_key="blob-watch",
        extracted_text="fixture body for confirm gate",
        fetch_status="ok",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    defaults.update(overrides)
    row = ReviewCandidate(**defaults)
    session.add(row)
    session.commit()
    return row


def test_watch_from_pending(tmp_path) -> None:
    session = _session(tmp_path)
    cand = _pending(session)
    out = watch_candidate(session, cand.id)
    assert out["status"] == "watching"
    row = session.get(ReviewCandidate, cand.id)
    assert row.status == "watching"
    decisions = list(session.scalars(select(ReviewDecision).where(ReviewDecision.candidate_id == cand.id)))
    assert any(d.action == "watch" for d in decisions)


def test_list_default_excludes_watching_via_status_filter(tmp_path) -> None:
    session = _session(tmp_path)
    pending = _pending(session, url_hash="h1", canonical_url="https://example.com/1", original_url="https://example.com/1")
    watching = _pending(
        session,
        url_hash="h2",
        canonical_url="https://example.com/2",
        original_url="https://example.com/2",
        title="已观察",
    )
    watch_candidate(session, watching.id)
    pending_rows = list(
        session.scalars(select(ReviewCandidate).where(ReviewCandidate.status == "pending_review"))
    )
    watching_rows = list(
        session.scalars(select(ReviewCandidate).where(ReviewCandidate.status == "watching"))
    )
    assert {r.id for r in pending_rows} == {pending.id}
    assert {r.id for r in watching_rows} == {watching.id}


def test_confirm_from_watching(tmp_path) -> None:
    session = _session(tmp_path)
    cand = _pending(session)
    watch_candidate(session, cand.id)
    out = confirm_candidate(session, cand.id)
    assert out["status"] == "confirmed"
    assert out["formal_event_id"]


def test_ignore_from_watching(tmp_path) -> None:
    session = _session(tmp_path)
    cand = _pending(session)
    watch_candidate(session, cand.id)
    out = ignore_candidate(session, cand.id, reason="不相关")
    assert out["status"] == "ignored"


def test_watch_rejects_non_pending(tmp_path) -> None:
    session = _session(tmp_path)
    cand = _pending(session, status="discovered")
    with pytest.raises(ValueError):
        watch_candidate(session, cand.id)
