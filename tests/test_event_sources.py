import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import FormalEvent
from jobs.event_sources import event_add_source, event_list_sources


def _session(tmp_path):
    db = tmp_path / "sources.db"
    engine = create_engine(f"sqlite:///{db}", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)()


def _event(session) -> FormalEvent:
    event = FormalEvent(
        candidate_id=1, title="某事件", canonical_url="https://example.com/a", provider="mock"
    )
    session.add(event)
    session.commit()
    return event


def test_add_source_missing_event_raises(tmp_path) -> None:
    session = _session(tmp_path)
    with pytest.raises(KeyError):
        event_add_source(session, 999, "https://example.com/b")


def test_add_source_requires_url(tmp_path) -> None:
    session = _session(tmp_path)
    event = _event(session)
    with pytest.raises(ValueError):
        event_add_source(session, event.id, "   ")


def test_add_and_list_sources(tmp_path) -> None:
    session = _session(tmp_path)
    event = _event(session)

    event_add_source(session, event.id, "https://gov.example.id/press", label="政府声明")
    event_add_source(session, event.id, "https://media.example.cn/repost", label="中国媒体转载")

    rows = event_list_sources(session, event.id)
    assert [r.label for r in rows] == ["政府声明", "中国媒体转载"]
    assert rows[0].source_domain == "gov.example.id"


def test_add_source_dedupes_same_url(tmp_path) -> None:
    session = _session(tmp_path)
    event = _event(session)

    first = event_add_source(session, event.id, "https://example.com/dup")
    second = event_add_source(session, event.id, "https://example.com/dup")
    assert first.id == second.id
    assert len(event_list_sources(session, event.id)) == 1


def test_list_sources_missing_event_raises(tmp_path) -> None:
    session = _session(tmp_path)
    with pytest.raises(KeyError):
        event_list_sources(session, 999)
