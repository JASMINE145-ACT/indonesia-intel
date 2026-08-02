"""WANd.INTEL.FETCH_CIRCUIT_BREAKER.001"""

from datetime import datetime, timezone

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import ReviewCandidate
from fetch.circuit_breaker import HostCircuitBreaker
from jobs import fetch_candidates as fc
from storage.blob import LocalBlobStore


def _wire(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'c.db'}",
        future=True,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def test_breaker_unit() -> None:
    b = HostCircuitBreaker(threshold=2)
    assert not b.is_open("a.com")
    b.record_escalation_failure("a.com")
    assert not b.is_open("a.com")
    b.record_escalation_failure("a.com")
    assert b.is_open("a.com")
    b.record_success("a.com")
    assert not b.is_open("a.com")


def test_breaker_opens_in_batch(tmp_path, monkeypatch) -> None:
    SessionLocal = _wire(tmp_path)
    monkeypatch.setenv("INTEL_FETCH_CIRCUIT_BREAKER", "1")
    monkeypatch.setenv("INTEL_FETCH_L15", "1")

    def boom(*a, **k):
        raise RuntimeError("Server disconnected without sending a response.")

    monkeypatch.setattr(fc, "fetch_and_extract", boom)
    monkeypatch.setattr(fc, "scrapling_l15_available", lambda: True)
    monkeypatch.setattr(fc, "fetch_and_extract_l15", boom)
    monkeypatch.setattr(fc, "HostCircuitBreaker", lambda threshold=3: HostCircuitBreaker(threshold=2))

    with SessionLocal() as session:
        for i in range(3):
            session.add(
                ReviewCandidate(
                    run_id="r",
                    provider="mock",
                    query="q",
                    original_url=f"https://www.reuters.com/a{i}",
                    canonical_url=f"https://www.reuters.com/a{i}",
                    url_hash=f"h{i}",
                    title="t",
                    snippet="",
                    status="discovered",
                    created_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc),
                )
            )
        session.commit()
        out = fc.fetch_discovered_candidates(
            session,
            LocalBlobStore(tmp_path / "b"),
            resolve_dns=False,
            enable_l2=False,
            enable_l15=True,
        )
        assert out["failed"] == 3
        rows = list(session.scalars(select(ReviewCandidate)))
        assert any(r.fetch_error_type == "circuit_open" for r in rows)


def test_breaker_flag_off(tmp_path, monkeypatch) -> None:
    SessionLocal = _wire(tmp_path)
    monkeypatch.setenv("INTEL_FETCH_CIRCUIT_BREAKER", "0")

    def boom(*a, **k):
        raise RuntimeError("Server disconnected without sending a response.")

    monkeypatch.setattr(fc, "fetch_and_extract", boom)
    with SessionLocal() as session:
        for i in range(3):
            session.add(
                ReviewCandidate(
                    run_id="r",
                    provider="mock",
                    query="q",
                    original_url=f"https://www.reuters.com/b{i}",
                    canonical_url=f"https://www.reuters.com/b{i}",
                    url_hash=f"hb{i}",
                    title="t",
                    snippet="",
                    status="discovered",
                    created_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc),
                )
            )
        session.commit()
        out = fc.fetch_discovered_candidates(
            session,
            LocalBlobStore(tmp_path / "b"),
            resolve_dns=False,
            enable_l2=False,
            enable_l15=False,
        )
        assert out["failed"] == 3
        rows = list(session.scalars(select(ReviewCandidate)))
        assert not any(r.fetch_error_type == "circuit_open" for r in rows)
