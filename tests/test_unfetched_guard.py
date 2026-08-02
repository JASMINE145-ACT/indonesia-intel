"""WANd.INTEL.UNFETCHED_GUARD.001"""

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import FormalEvent, ReviewCandidate
from jobs.factcheck import factcheck_event
from jobs.review_actions import confirm_candidate


def _session(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'g.db'}", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)()


def _pending(*, fetch_status="failed", object_key=None, text=None) -> ReviewCandidate:
    return ReviewCandidate(
        run_id="r",
        provider="mock",
        query="q",
        original_url="https://example.com/u",
        canonical_url="https://example.com/u",
        url_hash="hu",
        title="T",
        snippet="s",
        status="pending_review",
        fetch_status=fetch_status,
        fetch_error_type="http_403" if fetch_status == "failed" else None,
        object_key=object_key,
        extracted_text=text,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


def test_confirm_rejects_unfetched_by_default(tmp_path) -> None:
    session = _session(tmp_path)
    session.add(_pending())
    session.commit()
    cid = session.scalar(select(ReviewCandidate)).id
    with pytest.raises(ValueError, match="unfetched|no body|fetch_status"):
        confirm_candidate(session, cid)


def test_confirm_allow_unfetched_then_factcheck_fails(tmp_path) -> None:
    session = _session(tmp_path)
    session.add(_pending())
    session.commit()
    cid = session.scalar(select(ReviewCandidate)).id
    out = confirm_candidate(session, cid, allow_unfetched=True)
    assert out["formal_event_id"]
    fc = factcheck_event(session, out["formal_event_id"])
    assert fc["ok"] is False
    assert any("正文" in i or "object_key" in i or "抓取" in i for i in fc["issues"])


def test_confirm_with_body_ok(tmp_path) -> None:
    session = _session(tmp_path)
    session.add(_pending(fetch_status="ok", object_key="blob1", text="enough body"))
    session.commit()
    cid = session.scalar(select(ReviewCandidate)).id
    out = confirm_candidate(session, cid)
    assert out["formal_event_id"]
    ev = session.get(FormalEvent, out["formal_event_id"])
    assert ev.object_key == "blob1"
    fc = factcheck_event(session, out["formal_event_id"])
    assert fc["ok"] is True
