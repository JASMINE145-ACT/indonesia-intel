from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import Company, EventSource, FormalEvent, ReviewCandidate
from jobs.review_actions import confirm_candidate


def _session(tmp_path):
    db = tmp_path / "review.db"
    engine = create_engine(f"sqlite:///{db}", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)()


def _pending_candidate(session, **overrides) -> ReviewCandidate:
    defaults = dict(
        run_id="r1",
        provider="mock",
        query="q",
        original_url="https://example.com/a",
        canonical_url="https://example.com/a",
        url_hash="hash-a",
        title="比亚迪印尼工厂开工建设",
        snippet="",
        status="pending_review",
        object_key="blob-fixture",
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


def test_confirm_bare_still_works(tmp_path) -> None:
    session = _session(tmp_path)
    cand = _pending_candidate(session)
    result = confirm_candidate(session, cand.id)
    assert result["status"] == "confirmed"
    assert result["company_id"] is None


def test_confirm_auto_creates_primary_source(tmp_path) -> None:
    session = _session(tmp_path)
    cand = _pending_candidate(session)
    result = confirm_candidate(session, cand.id)

    sources = session.query(EventSource).filter_by(event_id=result["formal_event_id"]).all()
    assert len(sources) == 1
    assert sources[0].url == cand.canonical_url
    assert sources[0].label == "confirm_source"


def test_confirm_with_structured_fields_writes_formal_event(tmp_path) -> None:
    session = _session(tmp_path)
    cand = _pending_candidate(session)
    result = confirm_candidate(
        session,
        cand.id,
        company_name="比亚迪",
        industry="汽车、工程机械与交通装备",
        event_type="开工建设",
        project_stage="开工",
        occurred_date="2026-06-01",
        location="西爪哇 Subang",
        investment_amount="11.2万亿印尼盾",
        summary="比亚迪印尼工厂进入开工建设阶段。",
    )
    assert result["company_id"] is not None

    event = session.scalar(select(FormalEvent).where(FormalEvent.candidate_id == cand.id))
    assert event.industry == "汽车、工程机械与交通装备"
    assert event.event_type == "开工建设"
    assert event.project_stage == "开工"
    assert event.location == "西爪哇 Subang"

    company = session.get(Company, result["company_id"])
    assert company.name_cn == "比亚迪"
    assert company.industry == "汽车、工程机械与交通装备"


def test_confirm_rejects_unknown_industry(tmp_path) -> None:
    session = _session(tmp_path)
    cand = _pending_candidate(session)
    with pytest.raises(ValueError):
        confirm_candidate(session, cand.id, industry="乱写行业")


def test_confirm_rejects_unknown_event_type(tmp_path) -> None:
    session = _session(tmp_path)
    cand = _pending_candidate(session)
    with pytest.raises(ValueError):
        confirm_candidate(session, cand.id, event_type="乱写类型")


def test_confirm_rejects_unknown_project_stage(tmp_path) -> None:
    session = _session(tmp_path)
    cand = _pending_candidate(session)
    with pytest.raises(ValueError):
        confirm_candidate(session, cand.id, project_stage="乱写阶段")


def test_confirm_inherits_is_public_source_when_not_overridden(tmp_path) -> None:
    session = _session(tmp_path)
    cand = _pending_candidate(session, is_public_source=False, source_attribution="商务交流")
    result = confirm_candidate(session, cand.id)

    event = session.get(FormalEvent, result["formal_event_id"])
    assert event.is_public is False


def test_confirm_explicit_is_public_overrides_intake_flag(tmp_path) -> None:
    session = _session(tmp_path)
    cand = _pending_candidate(session, is_public_source=False)
    result = confirm_candidate(session, cand.id, is_public=True)

    event = session.get(FormalEvent, result["formal_event_id"])
    assert event.is_public is True


def test_confirm_with_explicit_company_id_skips_upsert(tmp_path) -> None:
    session = _session(tmp_path)
    existing = Company(name_cn="比亚迪")
    session.add(existing)
    session.commit()

    cand = _pending_candidate(session)
    result = confirm_candidate(session, cand.id, company_id=existing.id)
    assert result["company_id"] == existing.id
    assert session.query(Company).count() == 1
