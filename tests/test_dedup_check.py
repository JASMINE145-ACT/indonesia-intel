from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import FormalEvent, ReviewCandidate
from jobs.dedup_check import dedup_check


def _session(tmp_path):
    db = tmp_path / "dedup.db"
    engine = create_engine(f"sqlite:///{db}", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)()


def _candidate(**overrides) -> ReviewCandidate:
    defaults = dict(
        run_id="r1",
        provider="mock",
        query="q",
        original_url="https://example.com/a",
        canonical_url="https://example.com/a",
        url_hash="hash-a",
        title="比亚迪印尼工厂进入生产准备阶段",
        snippet="",
        status="pending_review",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    defaults.update(overrides)
    return ReviewCandidate(**defaults)


def test_dedup_check_missing_candidate_raises(tmp_path) -> None:
    session = _session(tmp_path)
    with pytest.raises(KeyError):
        dedup_check(session, 999)


def test_dedup_check_flags_similar_formal_event(tmp_path) -> None:
    session = _session(tmp_path)
    cand = _candidate()
    session.add(cand)
    session.add(
        FormalEvent(
            candidate_id=9999,
            title="比亚迪印尼工厂进入生产准备阶段（更新）",
            canonical_url="https://example.com/other",
            provider="mock",
        )
    )
    session.commit()

    result = dedup_check(session, cand.id)
    assert result["likely_duplicate_events"]
    assert result["likely_duplicate_events"][0]["similarity"] > 0.55


def test_dedup_check_flags_similar_pending_candidate(tmp_path) -> None:
    session = _session(tmp_path)
    cand = _candidate()
    other = _candidate(
        url_hash="hash-b",
        original_url="https://example.com/b",
        canonical_url="https://example.com/b",
        title="比亚迪印尼工厂进入生产准备阶段啦",
        status="discovered",
    )
    session.add(cand)
    session.add(other)
    session.commit()

    result = dedup_check(session, cand.id)
    assert any(m["candidate_id"] == other.id for m in result["likely_duplicate_pending"])


def test_dedup_check_ignores_unrelated_titles(tmp_path) -> None:
    session = _session(tmp_path)
    cand = _candidate()
    session.add(cand)
    session.add(
        FormalEvent(
            candidate_id=8888,
            title="宁德时代宣布在印尼设立电池材料基金",
            canonical_url="https://example.com/unrelated",
            provider="mock",
        )
    )
    session.commit()

    result = dedup_check(session, cand.id)
    assert result["likely_duplicate_events"] == []
