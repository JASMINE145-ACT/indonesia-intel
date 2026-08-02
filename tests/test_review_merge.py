from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import EventSource, FormalEvent, ReviewCandidate
from jobs.review_actions import confirm_candidate, merge_candidate, watch_candidate


def _session(tmp_path):
    db = tmp_path / "merge.db"
    engine = create_engine(f"sqlite:///{db}", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)()


def _pending(session, *, suffix: str, title: str = "候选") -> ReviewCandidate:
    url = f"https://example.com/{suffix}"
    row = ReviewCandidate(
        run_id="r1",
        provider="mock",
        query="q",
        original_url=url,
        canonical_url=url,
        url_hash=f"hash-{suffix}",
        title=title,
        snippet="",
        status="pending_review",
        object_key=f"blob-{suffix}",
        extracted_text="fixture body for confirm gate",
        fetch_status="ok",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    session.add(row)
    session.commit()
    return row


def test_merge_into_formal_event_adds_source(tmp_path) -> None:
    session = _session(tmp_path)
    primary = _pending(session, suffix="a", title="比亚迪工厂开工")
    dup = _pending(session, suffix="b", title="比亚迪工厂开工（转载）")
    confirmed = confirm_candidate(session, primary.id)
    event_id = confirmed["formal_event_id"]

    out = merge_candidate(session, dup.id, target_formal_event_id=event_id)
    assert out["status"] == "merged"
    assert out["duplicate_of_event_id"] == event_id
    assert out["formal_event_id"] == event_id

    row = session.get(ReviewCandidate, dup.id)
    assert row.status == "merged"
    assert row.duplicate_of_event_id == event_id

    sources = list(session.scalars(select(EventSource).where(EventSource.event_id == event_id)))
    urls = {s.url for s in sources}
    assert primary.canonical_url in urls
    assert dup.canonical_url in urls
    assert any(s.label == "merge_source" for s in sources if s.url == dup.canonical_url)


def test_merge_from_watching(tmp_path) -> None:
    session = _session(tmp_path)
    primary = _pending(session, suffix="p")
    dup = _pending(session, suffix="d")
    event_id = confirm_candidate(session, primary.id)["formal_event_id"]
    watch_candidate(session, dup.id)
    out = merge_candidate(session, dup.id, target_formal_event_id=event_id)
    assert out["status"] == "merged"


def test_merge_rejects_missing_event(tmp_path) -> None:
    session = _session(tmp_path)
    dup = _pending(session, suffix="x")
    with pytest.raises(KeyError):
        merge_candidate(session, dup.id, target_formal_event_id=99999)


def test_merge_rejects_confirmed_candidate(tmp_path) -> None:
    session = _session(tmp_path)
    a = _pending(session, suffix="c1")
    b = _pending(session, suffix="c2")
    event_id = confirm_candidate(session, a.id)["formal_event_id"]
    confirm_candidate(session, b.id)
    with pytest.raises(ValueError):
        merge_candidate(session, b.id, target_formal_event_id=event_id)


def test_merged_does_not_create_second_formal_event(tmp_path) -> None:
    session = _session(tmp_path)
    primary = _pending(session, suffix="m1")
    dup = _pending(session, suffix="m2")
    event_id = confirm_candidate(session, primary.id)["formal_event_id"]
    merge_candidate(session, dup.id, target_formal_event_id=event_id)
    events = list(session.scalars(select(FormalEvent)))
    assert len(events) == 1
    assert events[0].id == event_id
