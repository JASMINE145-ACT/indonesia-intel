"""fetch_candidates L1→L1.5→L2 escalation tests."""

from datetime import datetime, timezone

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import ReviewCandidate
from jobs import fetch_candidates as fc
from storage.blob import LocalBlobStore


def _wire(tmp_path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'f.db'}",
        future=True,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def test_l1_success_no_l2(tmp_path, monkeypatch) -> None:
    SessionLocal = _wire(tmp_path, monkeypatch)
    html = b"<html><body><article><p>Factory in Indonesia Subang.</p></article></body></html>"
    with SessionLocal() as session:
        session.add(
            ReviewCandidate(
                run_id="r",
                provider="mock",
                query="q",
                original_url="https://example.com/ok",
                canonical_url="https://example.com/ok",
                url_hash="h1",
                title="t",
                snippet="",
                status="discovered",
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
        )
        session.commit()
        blob = LocalBlobStore(tmp_path / "b")
        out = fc.fetch_discovered_candidates(
            session,
            blob,
            resolve_dns=False,
            html_overrides={"https://example.com/ok": html},
            enable_l2=True,
            enable_l15=False,
        )
        assert out["fetched"] == 1
        assert out["l2_used"] == 0
        assert out.get("l15_used", 0) == 0


def test_l1_fail_l15_ok(tmp_path, monkeypatch) -> None:
    SessionLocal = _wire(tmp_path, monkeypatch)

    def boom(*a, **k):
        raise RuntimeError("Server disconnected without sending a response.")

    class Page:
        url = "https://www.reuters.com/x"
        title = "Reuters via L15"
        text = "Chinese EV plant news in Indonesia with enough text body."
        html = b"<html><body><article><p>Chinese EV plant news in Indonesia with enough text body.</p></article></body></html>"
        final_url = "https://www.reuters.com/x"
        status_code = 200

    monkeypatch.setattr(fc, "fetch_and_extract", boom)
    monkeypatch.setattr(fc, "scrapling_l15_available", lambda: True)
    monkeypatch.setattr(fc, "fetch_and_extract_l15", lambda *a, **k: Page())
    monkeypatch.setattr(fc, "circuit_breaker_enabled", lambda: False)

    with SessionLocal() as session:
        session.add(
            ReviewCandidate(
                run_id="r",
                provider="search",
                query="q",
                original_url="https://www.reuters.com/x",
                canonical_url="https://www.reuters.com/x",
                url_hash="h15",
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
        assert out["fetched"] == 1
        assert out["l15_used"] == 1
        assert out["details"][0]["final"]["selected_level"] == "l15"


def test_l1_fail_l15_fail_then_l2(tmp_path, monkeypatch) -> None:
    SessionLocal = _wire(tmp_path, monkeypatch)

    def boom(*a, **k):
        raise RuntimeError("Server disconnected without sending a response.")

    def l15_boom(*a, **k):
        raise RuntimeError("Server disconnected without sending a response.")

    class Page:
        url = "https://www.kompas.com/x"
        title = "Kompas L2"
        text = "Chinese EV plant news in Indonesia with enough text body."
        html = b"<html><body><article><p>Chinese EV plant news in Indonesia with enough text body.</p></article></body></html>"
        final_url = "https://www.kompas.com/x"
        status_code = 200

    monkeypatch.setattr(fc, "fetch_and_extract", boom)
    monkeypatch.setattr(fc, "scrapling_l15_available", lambda: True)
    monkeypatch.setattr(fc, "fetch_and_extract_l15", l15_boom)
    monkeypatch.setattr(fc, "scrapling_available", lambda: True)
    monkeypatch.setattr(fc, "domain_allowed", lambda url, al: True)
    monkeypatch.setattr(
        fc, "_l2_allowlist_and_modes", lambda: ({"kompas.com"}, {"kompas.com": "dynamic"})
    )
    monkeypatch.setattr(fc, "fetch_and_extract_scrapling", lambda *a, **k: Page())
    monkeypatch.setattr(fc, "circuit_breaker_enabled", lambda: False)

    with SessionLocal() as session:
        session.add(
            ReviewCandidate(
                run_id="r",
                provider="rss",
                query="q",
                original_url="https://www.kompas.com/x",
                canonical_url="https://www.kompas.com/x",
                url_hash="h2",
                title="t",
                snippet="",
                status="discovered",
                source_id="kompas",
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
        )
        session.commit()
        out = fc.fetch_discovered_candidates(
            session,
            LocalBlobStore(tmp_path / "b"),
            resolve_dns=False,
            enable_l2=True,
            enable_l15=True,
        )
        assert out["fetched"] == 1
        assert out["l2_used"] == 1
        assert out["details"][0]["final"]["selected_level"] == "l2"


def test_no_escalate_when_l2_disabled(tmp_path, monkeypatch) -> None:
    SessionLocal = _wire(tmp_path, monkeypatch)
    monkeypatch.setattr(
        fc, "fetch_and_extract", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("403 Forbidden"))
    )
    called = {"n": 0}

    def l2(*a, **k):
        called["n"] += 1
        raise AssertionError("should not call L2")

    monkeypatch.setattr(fc, "fetch_and_extract_scrapling", l2)
    with SessionLocal() as session:
        session.add(
            ReviewCandidate(
                run_id="r",
                provider="rss",
                query="q",
                original_url="https://www.kompas.com/x",
                canonical_url="https://www.kompas.com/x",
                url_hash="h3",
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
        assert out["failed"] == 1
        assert called["n"] == 0


def test_escalate_on_l1_blocked_title(tmp_path, monkeypatch) -> None:
    SessionLocal = _wire(tmp_path, monkeypatch)

    class L1Page:
        url = "https://www.iea.org/countries/indonesia"
        title = "Just a moment..."
        text = "Checking your browser before accessing iea.org"
        html = b"<html><title>Just a moment...</title><body>cf-chl-</body></html>"
        final_url = "https://www.iea.org/countries/indonesia"
        status_code = 200

    class L2Page:
        url = "https://www.iea.org/countries/indonesia"
        title = "Indonesia - Countries & Regions - IEA"
        text = "Indonesia energy overview with meaningful extracted body text for validation."
        html = (
            b"<html><body><article><p>Indonesia energy overview with meaningful "
            b"extracted body text for validation.</p></article></body></html>"
        )
        final_url = "https://www.iea.org/countries/indonesia"
        status_code = 200

    monkeypatch.setattr(fc, "fetch_and_extract", lambda *a, **k: L1Page())
    monkeypatch.setattr(fc, "scrapling_available", lambda: True)
    monkeypatch.setattr(fc, "domain_allowed", lambda url, al: True)
    monkeypatch.setattr(
        fc, "_l2_allowlist_and_modes", lambda: ({"iea.org"}, {"iea.org": "stealthy"})
    )
    monkeypatch.setattr(fc, "fetch_and_extract_scrapling", lambda *a, **k: L2Page())
    monkeypatch.setattr(fc, "circuit_breaker_enabled", lambda: False)

    with SessionLocal() as session:
        session.add(
            ReviewCandidate(
                run_id="r",
                provider="mock",
                query="q",
                original_url="https://www.iea.org/countries/indonesia",
                canonical_url="https://www.iea.org/countries/indonesia",
                url_hash="h4",
                title="t",
                snippet="",
                status="discovered",
                source_id="iea_id",
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
        )
        session.commit()
        out = fc.fetch_discovered_candidates(
            session,
            LocalBlobStore(tmp_path / "b"),
            resolve_dns=False,
            enable_l2=True,
            enable_l15=False,
        )
        assert out["fetched"] == 1
        assert out["l2_used"] == 1


def test_blocked_title_no_l2_when_fetch_l2_disabled_on_source(tmp_path, monkeypatch) -> None:
    SessionLocal = _wire(tmp_path, monkeypatch)

    class L1Page:
        url = "https://www.iea.org/x"
        title = "Just a moment..."
        text = "x"
        html = b"<html>Just a moment...</html>"
        final_url = "https://www.iea.org/x"
        status_code = 200

    called = {"n": 0}

    def l2(*a, **k):
        called["n"] += 1
        raise AssertionError("L2 must not run")

    monkeypatch.setattr(fc, "fetch_and_extract", lambda *a, **k: L1Page())
    monkeypatch.setattr(fc, "scrapling_available", lambda: True)
    monkeypatch.setattr(fc, "_l2_allowlist_and_modes", lambda: (set(), {}))
    monkeypatch.setattr(fc, "fetch_and_extract_scrapling", l2)

    with SessionLocal() as session:
        session.add(
            ReviewCandidate(
                run_id="r",
                provider="mock",
                query="q",
                original_url="https://www.iea.org/x",
                canonical_url="https://www.iea.org/x",
                url_hash="h5",
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
            enable_l2=True,
            enable_l15=False,
        )
        assert out["failed"] == 1
        assert called["n"] == 0


def test_social_no_escalate(tmp_path, monkeypatch) -> None:
    SessionLocal = _wire(tmp_path, monkeypatch)
    called = {"l1": 0, "l15": 0, "l2": 0}

    def l1(*a, **k):
        called["l1"] += 1
        raise AssertionError("no L1 for social")

    monkeypatch.setattr(fc, "fetch_and_extract", l1)
    monkeypatch.setattr(
        fc, "fetch_and_extract_l15", lambda *a, **k: called.__setitem__("l15", 1)
    )
    monkeypatch.setattr(
        fc, "fetch_and_extract_scrapling", lambda *a, **k: called.__setitem__("l2", 1)
    )

    with SessionLocal() as session:
        session.add(
            ReviewCandidate(
                run_id="r",
                provider="search",
                query="q",
                original_url="https://www.instagram.com/p/abc",
                canonical_url="https://www.instagram.com/p/abc",
                url_hash="hig",
                title="ig",
                snippet="snip",
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
            enable_l2=True,
            enable_l15=True,
        )
        assert out["failed"] == 1
        assert called["l1"] == 0
        row = session.scalar(select(ReviewCandidate))
        assert row.fetch_error_type == "social_unsupported"
        assert row.status == "pending_review"
