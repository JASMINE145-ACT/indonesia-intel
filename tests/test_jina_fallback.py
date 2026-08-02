"""Jina Reader fail-only — WANd.INTEL.JINA_FETCH_FALLBACK.001."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import ReviewCandidate
from fetch.jina_fallback import (
    assess_jina_markdown,
    fetch_and_extract_jina,
    jina_already_attempted,
    jina_eligible,
    jina_proxy_url,
    mark_jina_attempted,
)
from jobs import fetch_candidates as fc
from jobs.ops_dashboard import pipeline_summary
from storage.blob import LocalBlobStore


def _wire(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'j.db'}",
        future=True,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def _cand(**kwargs):
    now = datetime.now(timezone.utc)
    base = dict(
        run_id="r",
        provider="mock",
        query="q",
        original_url="https://example.com/article",
        canonical_url="https://example.com/article",
        url_hash="jh1",
        title="t",
        snippet="",
        status="discovered",
        raw_search_json="{}",
        created_at=now,
        updated_at=now,
    )
    base.update(kwargs)
    return ReviewCandidate(**base)


@pytest.mark.parametrize(
    "err,ok",
    [
        ("empty_extraction", True),
        ("waf_blocked", True),
        ("http_403", True),
        ("http_401", False),
        ("social_unsupported", False),
        ("pdf_too_large", False),
        ("ssrf", False),
        ("robots_disallowed", False),
        ("terminal_not_found", False),
        (None, False),
    ],
)
def test_jina_eligible_matrix(err, ok) -> None:
    assert jina_eligible(err) is ok


def test_assess_jina_fake_and_ok() -> None:
    ok, err, _ = assess_jina_markdown("")
    assert ok is False and err == "jina_fake_body"
    ok, err, _ = assess_jina_markdown('{"error":"nope"}')
    assert ok is False and err == "jina_fake_body"
    ok, err, _ = assess_jina_markdown("Page not found\n" + ("x" * 50))
    assert ok is False and err == "jina_fake_body"
    ok, err, _ = assess_jina_markdown("", status_code=429)
    assert ok is False and err == "jina_rate_limited"
    body = "# Title\n\n" + ("Indonesia factory news. " * 10)
    ok, err, _ = assess_jina_markdown(body, status_code=200)
    assert ok is True and err is None


def test_ssrf_before_jina_proxy(monkeypatch) -> None:
    called = {"get": False}

    class BoomClient:
        def get(self, *a, **k):
            called["get"] = True
            raise AssertionError("must not call network on SSRF")

        def close(self):
            pass

    with pytest.raises(Exception) as ei:
        fetch_and_extract_jina(
            "http://127.0.0.1/secret",
            client=BoomClient(),  # type: ignore[arg-type]
            resolve_dns=True,
        )
    assert called["get"] is False
    assert getattr(ei.value, "error_type", None) == "ssrf"


def test_jina_proxy_url_shape() -> None:
    u = "https://example.com/a"
    assert jina_proxy_url(u) == f"https://r.jina.ai/{u}"


def test_flag_off_no_jina(tmp_path, monkeypatch) -> None:
    SessionLocal = _wire(tmp_path)

    def boom(*a, **k):
        raise RuntimeError("Server disconnected without sending a response.")

    jina_calls = {"n": 0}

    def jina(*a, **k):
        jina_calls["n"] += 1
        raise AssertionError("jina must not run")

    monkeypatch.setattr(fc, "fetch_and_extract", boom)
    monkeypatch.setattr(fc, "scrapling_l15_available", lambda: False)
    monkeypatch.setattr(fc, "scrapling_available", lambda: False)
    monkeypatch.setattr(fc, "fetch_and_extract_jina", jina)
    monkeypatch.setattr(fc, "circuit_breaker_enabled", lambda: False)

    with SessionLocal() as session:
        session.add(_cand())
        session.commit()
        out = fc.fetch_discovered_candidates(
            session,
            LocalBlobStore(tmp_path / "b"),
            resolve_dns=False,
            enable_l2=False,
            enable_l15=False,
            enable_jina=False,
        )
        assert out["fetched"] == 0
        assert out["jina_used"] == 0
        assert jina_calls["n"] == 0
        assert out["details"][0]["jina"]["attempted"] is False


def test_jina_success_after_ladder(tmp_path, monkeypatch) -> None:
    SessionLocal = _wire(tmp_path)

    def boom(*a, **k):
        raise RuntimeError("Server disconnected without sending a response.")

    class Page:
        url = "https://example.com/article"
        title = "Via Jina"
        text = "Chinese EV plant news in Indonesia with enough markdown body text here."
        html = text.encode()
        final_url = url
        content_kind = "jina_markdown"
        blob_suffix = ".md"
        status_code = 200

    monkeypatch.setattr(fc, "fetch_and_extract", boom)
    monkeypatch.setattr(fc, "scrapling_l15_available", lambda: False)
    monkeypatch.setattr(fc, "scrapling_available", lambda: False)
    monkeypatch.setattr(fc, "fetch_and_extract_jina", lambda *a, **k: Page())
    monkeypatch.setattr(fc, "circuit_breaker_enabled", lambda: False)

    with SessionLocal() as session:
        session.add(_cand())
        session.commit()
        out = fc.fetch_discovered_candidates(
            session,
            LocalBlobStore(tmp_path / "b"),
            resolve_dns=False,
            enable_l2=False,
            enable_l15=False,
            enable_jina=True,
        )
        assert out["fetched"] == 1
        assert out["jina_used"] == 1
        assert out["details"][0]["final"]["selected_level"] == "jina"
        row = session.scalar(select(ReviewCandidate))
        assert row is not None
        assert row.status == "pending_review"
        assert "jina_reader" in (row.snippet or "")
        assert jina_already_attempted(row)


def test_once_per_url_blocks_retry(tmp_path, monkeypatch) -> None:
    SessionLocal = _wire(tmp_path)

    def boom(*a, **k):
        raise RuntimeError("Server disconnected without sending a response.")

    calls = {"n": 0}

    def jina_fail(*a, **k):
        from fetch.jina_fallback import JinaFetchError

        calls["n"] += 1
        raise JinaFetchError("jina_failed", "nope")

    monkeypatch.setattr(fc, "fetch_and_extract", boom)
    monkeypatch.setattr(fc, "scrapling_l15_available", lambda: False)
    monkeypatch.setattr(fc, "scrapling_available", lambda: False)
    monkeypatch.setattr(fc, "fetch_and_extract_jina", jina_fail)
    monkeypatch.setattr(fc, "circuit_breaker_enabled", lambda: False)

    with SessionLocal() as session:
        session.add(_cand(url_hash="once1"))
        session.commit()
        fc.fetch_discovered_candidates(
            session,
            LocalBlobStore(tmp_path / "b"),
            resolve_dns=False,
            enable_l2=False,
            enable_l15=False,
            enable_jina=True,
        )
        assert calls["n"] == 1
        row = session.scalar(select(ReviewCandidate))
        assert row is not None
        assert jina_already_attempted(row)
        # Requeue as discovered; jina_attempted must block second call
        row.status = "discovered"
        row.fetch_status = "pending"
        row.fetch_error_type = None
        session.commit()
        fc.fetch_discovered_candidates(
            session,
            LocalBlobStore(tmp_path / "b"),
            resolve_dns=False,
            enable_l2=False,
            enable_l15=False,
            enable_jina=True,
        )
        assert calls["n"] == 1


def test_http_401_never_jina(tmp_path, monkeypatch) -> None:
    SessionLocal = _wire(tmp_path)
    jina_calls = {"n": 0}

    class Page401:
        url = "https://example.com/article"
        title = ""
        text = ""
        html = b"<html></html>"
        final_url = url
        status_code = 401

    def jina(*a, **k):
        jina_calls["n"] += 1
        raise AssertionError("no jina on 401")

    monkeypatch.setattr(fc, "fetch_and_extract", lambda *a, **k: Page401())
    monkeypatch.setattr(fc, "scrapling_l15_available", lambda: False)
    monkeypatch.setattr(fc, "scrapling_available", lambda: False)
    monkeypatch.setattr(fc, "fetch_and_extract_jina", jina)
    monkeypatch.setattr(fc, "circuit_breaker_enabled", lambda: False)

    with SessionLocal() as session:
        session.add(_cand())
        session.commit()
        out = fc.fetch_discovered_candidates(
            session,
            LocalBlobStore(tmp_path / "b"),
            resolve_dns=False,
            enable_l2=False,
            enable_l15=False,
            enable_jina=True,
        )
        assert jina_calls["n"] == 0
        assert out["jina_used"] == 0
        assert out["details"][0]["jina"]["attempted"] is False


def test_jina_429_typed(tmp_path, monkeypatch) -> None:
    SessionLocal = _wire(tmp_path)

    def boom(*a, **k):
        raise RuntimeError("Server disconnected without sending a response.")

    def jina429(*a, **k):
        from fetch.jina_fallback import JinaFetchError

        raise JinaFetchError("jina_rate_limited", "http_status=429")

    monkeypatch.setattr(fc, "fetch_and_extract", boom)
    monkeypatch.setattr(fc, "scrapling_l15_available", lambda: False)
    monkeypatch.setattr(fc, "scrapling_available", lambda: False)
    monkeypatch.setattr(fc, "fetch_and_extract_jina", jina429)
    monkeypatch.setattr(fc, "circuit_breaker_enabled", lambda: False)

    with SessionLocal() as session:
        session.add(_cand(url_hash="r429"))
        session.commit()
        out = fc.fetch_discovered_candidates(
            session,
            LocalBlobStore(tmp_path / "b"),
            resolve_dns=False,
            enable_l2=False,
            enable_l15=False,
            enable_jina=True,
        )
        assert out["failed"] == 1
        row = session.scalar(select(ReviewCandidate))
        assert row.fetch_error_type == "jina_rate_limited"
        assert jina_already_attempted(row)


def test_pipeline_summary_lanes(tmp_path) -> None:
    SessionLocal = _wire(tmp_path)
    with SessionLocal() as session:
        session.add(
            _cand(
                status="fetch_failed",
                fetch_error_type="jina_rate_limited",
                discovery_method="rss",
            )
        )
        session.commit()
        summary = pipeline_summary(session)
        assert "lanes" in summary
        assert summary["lanes"]["fetch"].get("jina_rate_limited") == 1
        assert summary["lanes"]["document"]["document_jobs"] == 0
        assert summary["counts_by_fetch_error_type"]["jina_rate_limited"] == 1


def test_mark_jina_attempted_roundtrip() -> None:
    class R:
        raw_search_json = "{}"

    r = R()
    assert jina_already_attempted(r) is False
    mark_jina_attempted(r)
    assert jina_already_attempted(r) is True


def test_jina_omits_authorization_without_key(monkeypatch) -> None:
    """missing_credentials contract: free-tier call has no Authorization header."""
    monkeypatch.delenv("JINA_API_KEY", raising=False)
    monkeypatch.delenv("INTEL_JINA_API_KEY", raising=False)
    captured: dict = {}

    class Resp:
        status_code = 200
        text = "# Hello\n\n" + ("Indonesia factory body text. " * 8)

    class Client:
        def get(self, url, headers=None):
            captured["url"] = url
            captured["headers"] = dict(headers or {})
            return Resp()

        def close(self):
            pass

    page = fetch_and_extract_jina(
        "https://example.com/",
        client=Client(),  # type: ignore[arg-type]
        resolve_dns=False,
    )
    assert "Authorization" not in captured["headers"]
    assert page.content_kind == "jina_markdown"


def test_jina_timeout_typed(monkeypatch) -> None:
    """timeout_handling: httpx timeout → jina_failed typed error."""
    import httpx
    from fetch.jina_fallback import JinaFetchError

    class Client:
        def get(self, *a, **k):
            raise httpx.ReadTimeout("read timed out")

        def close(self):
            pass

    with pytest.raises(JinaFetchError) as ei:
        fetch_and_extract_jina(
            "https://example.com/",
            client=Client(),  # type: ignore[arg-type]
            resolve_dns=False,
        )
    assert ei.value.error_type == "jina_failed"
    assert "ReadTimeout" in ei.value.detail or "timeout" in ei.value.detail.lower()
