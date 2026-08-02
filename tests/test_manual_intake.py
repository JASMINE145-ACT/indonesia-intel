import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from jobs.manual_intake import manual_add_candidate


def _session(tmp_path):
    db = tmp_path / "manual.db"
    engine = create_engine(f"sqlite:///{db}", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)()


def test_manual_add_with_url(tmp_path) -> None:
    session = _session(tmp_path)
    row = manual_add_candidate(session, title="某活动现场观察", url="https://example.com/note")
    assert row.status == "pending_review"
    assert row.provider == "manual"
    assert row.canonical_url == "https://example.com/note"
    assert row.source_attribution == "待验证"
    assert row.is_public_source is True


def test_manual_add_without_url_gets_synthetic_canonical_url(tmp_path) -> None:
    session = _session(tmp_path)
    row = manual_add_candidate(
        session,
        title="内部交流纪要",
        text="某企业负责人在闭门会上透露的计划。",
        source_attribution="商务交流",
        is_public_source=False,
    )
    assert row.canonical_url.startswith("manual://")
    assert row.extracted_text == "某企业负责人在闭门会上透露的计划。"
    assert row.is_public_source is False


def test_manual_add_requires_title(tmp_path) -> None:
    session = _session(tmp_path)
    with pytest.raises(ValueError):
        manual_add_candidate(session, title="  ", url="https://example.com/x")


def test_manual_add_requires_url_or_text(tmp_path) -> None:
    session = _session(tmp_path)
    with pytest.raises(ValueError):
        manual_add_candidate(session, title="标题")


def test_manual_add_rejects_unknown_source_attribution(tmp_path) -> None:
    session = _session(tmp_path)
    with pytest.raises(ValueError):
        manual_add_candidate(
            session, title="标题", url="https://example.com/x", source_attribution="乱写"
        )


def test_manual_add_same_url_twice_returns_existing(tmp_path) -> None:
    session = _session(tmp_path)
    first = manual_add_candidate(session, title="标题A", url="https://example.com/dup")
    second = manual_add_candidate(session, title="标题B（同一链接）", url="https://example.com/dup")
    assert first.id == second.id
