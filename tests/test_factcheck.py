import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import FormalEvent
from jobs.factcheck import factcheck_event


def _session(tmp_path):
    db = tmp_path / "factcheck.db"
    engine = create_engine(f"sqlite:///{db}", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)()


def test_factcheck_missing_event_raises(tmp_path) -> None:
    session = _session(tmp_path)
    with pytest.raises(KeyError):
        factcheck_event(session, 999)


def test_factcheck_ok_when_clean(tmp_path) -> None:
    session = _session(tmp_path)
    event = FormalEvent(
        candidate_id=1,
        title="比亚迪印尼工厂开工建设",
        canonical_url="https://example.com/a",
        provider="mock",
        industry="汽车、工程机械与交通装备",
        event_type="开工建设",
        project_stage="开工",
    )
    session.add(event)
    session.commit()

    result = factcheck_event(session, event.id)
    assert result["ok"] is True
    assert result["issues"] == []


def test_factcheck_flags_missing_source(tmp_path) -> None:
    session = _session(tmp_path)
    event = FormalEvent(candidate_id=1, title="无来源事件", canonical_url="", provider="mock")
    session.add(event)
    session.commit()

    result = factcheck_event(session, event.id)
    assert result["ok"] is False
    assert any("来源" in issue for issue in result["issues"])


def test_factcheck_flags_out_of_taxonomy_values(tmp_path) -> None:
    session = _session(tmp_path)
    event = FormalEvent(
        candidate_id=1,
        title="某事件",
        canonical_url="https://example.com/a",
        provider="mock",
        industry="乱写行业",
        event_type="乱写类型",
        project_stage="乱写阶段",
    )
    session.add(event)
    session.commit()

    result = factcheck_event(session, event.id)
    assert result["ok"] is False
    assert len(result["issues"]) == 3


def test_factcheck_flags_dangling_company_and_project(tmp_path) -> None:
    session = _session(tmp_path)
    event = FormalEvent(
        candidate_id=1,
        title="某事件",
        canonical_url="https://example.com/a",
        provider="mock",
        company_id=999,
        project_id=888,
    )
    session.add(event)
    session.commit()

    result = factcheck_event(session, event.id)
    assert any("company_id" in issue for issue in result["issues"])
    assert any("project_id" in issue for issue in result["issues"])


def test_factcheck_flags_stage_word_confusion(tmp_path) -> None:
    session = _session(tmp_path)
    event = FormalEvent(
        candidate_id=1,
        title="某企业中标印尼电站项目",
        canonical_url="https://example.com/a",
        provider="mock",
        event_type="市场表现",
    )
    session.add(event)
    session.commit()

    result = factcheck_event(session, event.id)
    assert any("中标" in issue for issue in result["issues"])
