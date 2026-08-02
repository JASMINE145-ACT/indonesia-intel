"""WANd.INTEL.FETCH_SOFT_PENDING.001 / FETCH_RETRY.001"""

from datetime import datetime, timezone

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import ReviewCandidate
from jobs import fetch_candidates as fc
from storage.blob import LocalBlobStore


def _wire(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 's.db'}",
        future=True,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def _row(**kw) -> ReviewCandidate:
    base = dict(
        run_id="r",
        provider="mock",
        query="q",
        original_url="https://example.com/x",
        canonical_url="https://example.com/x",
        url_hash="hx",
        title="Title from search",
        snippet="search snippet keep me",
        status="discovered",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    base.update(kw)
    return ReviewCandidate(**base)


def test_soft_pending_on_recoverable_fail(tmp_path, monkeypatch) -> None:
    SessionLocal = _wire(tmp_path)
    monkeypatch.setattr(
        "app.config.settings.fetch_soft_pending_enabled", True
    )
    monkeypatch.setattr(
        fc,
        "fetch_and_extract",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("403 Forbidden")),
    )
    with SessionLocal() as session:
        session.add(_row())
        session.commit()
        out = fc.fetch_discovered_candidates(
            session, LocalBlobStore(tmp_path / "b"), resolve_dns=False, enable_l2=False
        )
        assert out["failed"] == 1
        assert "unfetched_for_user" in out
        assert len(out["unfetched_for_user"]) == 1
        uf = out["unfetched_for_user"][0]
        assert uf["open_url"] == "https://example.com/x"
        assert uf["user_hint"]
        assert uf["fetch_error_type"] == "http_403"
        row = session.scalar(select(ReviewCandidate))
        assert row.status == "pending_review"
        assert row.fetch_status == "failed"
        assert row.fetch_error_type == "http_403"
        assert row.snippet == "search snippet keep me"
        assert not (row.snippet or "").startswith("fetch_error:")


def test_hard_fail_still_fetch_failed(tmp_path, monkeypatch) -> None:
    SessionLocal = _wire(tmp_path)
    monkeypatch.setattr("app.config.settings.fetch_soft_pending_enabled", True)

    from fetch.ssrf import UnsafeURLError

    monkeypatch.setattr(
        fc,
        "fetch_and_extract",
        lambda *a, **k: (_ for _ in ()).throw(UnsafeURLError("blocked private")),
    )
    with SessionLocal() as session:
        session.add(_row(original_url="http://127.0.0.1/x", canonical_url="http://127.0.0.1/x", url_hash="hpriv"))
        session.commit()
        out = fc.fetch_discovered_candidates(
            session, LocalBlobStore(tmp_path / "b"), resolve_dns=False, enable_l2=False
        )
        assert out["failed"] == 1
        row = session.scalar(select(ReviewCandidate))
        assert row.status == "fetch_failed"
        assert row.fetch_status == "failed"


def test_success_sets_fetch_status_ok(tmp_path, monkeypatch) -> None:
    SessionLocal = _wire(tmp_path)
    html = b"<html><body><article><p>Factory in Indonesia Subang with enough words.</p></article></body></html>"
    with SessionLocal() as session:
        session.add(_row(url_hash="hok", original_url="https://example.com/ok", canonical_url="https://example.com/ok"))
        session.commit()
        out = fc.fetch_discovered_candidates(
            session,
            LocalBlobStore(tmp_path / "b"),
            resolve_dns=False,
            html_overrides={"https://example.com/ok": html},
            enable_l2=False,
        )
        assert out["fetched"] == 1
        row = session.scalar(select(ReviewCandidate))
        assert row.status == "pending_review"
        assert row.fetch_status == "ok"
        assert row.object_key


def test_retry_failed_refetch(tmp_path, monkeypatch) -> None:
    SessionLocal = _wire(tmp_path)
    html = b"<html><body><article><p>Retry body text long enough for validity check here.</p></article></body></html>"
    with SessionLocal() as session:
        session.add(
            _row(
                status="pending_review",
                fetch_status="failed",
                fetch_error_type="http_403",
                url_hash="hr",
                original_url="https://example.com/retry",
                canonical_url="https://example.com/retry",
            )
        )
        session.commit()
        out = fc.fetch_discovered_candidates(
            session,
            LocalBlobStore(tmp_path / "b"),
            resolve_dns=False,
            html_overrides={"https://example.com/retry": html},
            enable_l2=False,
            retry_failed=True,
        )
        assert out["fetched"] == 1
        row = session.scalar(select(ReviewCandidate))
        assert row.fetch_status == "ok"
        assert row.object_key


def test_switch_off_keeps_fetch_failed(tmp_path, monkeypatch) -> None:
    SessionLocal = _wire(tmp_path)
    monkeypatch.setattr("app.config.settings.fetch_soft_pending_enabled", False)
    monkeypatch.setattr(
        fc,
        "fetch_and_extract",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("403")),
    )
    with SessionLocal() as session:
        session.add(_row(url_hash="hoff"))
        session.commit()
        fc.fetch_discovered_candidates(
            session, LocalBlobStore(tmp_path / "b"), resolve_dns=False, enable_l2=False
        )
        row = session.scalar(select(ReviewCandidate))
        assert row.status == "fetch_failed"
