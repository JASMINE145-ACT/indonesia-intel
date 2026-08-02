"""PDF queue MVP — WANd.INTEL.FETCH_PDF_QUEUE.001."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import DocumentJob, ReviewCandidate
from jobs import fetch_candidates as fc
from jobs import pdf_queue as pq
from jobs.review_actions import confirm_candidate
from storage.blob import LocalBlobStore


def _wire(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'pq.db'}",
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
        original_url="https://example.com/big.pdf",
        canonical_url="https://example.com/big.pdf",
        url_hash="pdf1",
        title="t",
        snippet="",
        status="discovered",
        raw_search_json="{}",
        created_at=now,
        updated_at=now,
    )
    base.update(kwargs)
    return ReviewCandidate(**base)


def test_pdf_too_large_enqueues(tmp_path, monkeypatch) -> None:
    SessionLocal = _wire(tmp_path)
    monkeypatch.setenv("INTEL_PDF_QUEUE_ENABLED", "1")

    def boom(*a, **k):
        raise ValueError("pdf_too_large: 15000000 > 12000000")

    monkeypatch.setattr(fc, "fetch_and_extract", boom)
    monkeypatch.setattr(fc, "scrapling_l15_available", lambda: False)
    monkeypatch.setattr(fc, "scrapling_available", lambda: False)
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
        assert out["pdf_queued"] == 1
        row = session.scalar(select(ReviewCandidate))
        assert row.status == "pdf_queued"
        assert row.fetch_status == "pdf_queued"
        job = session.scalar(select(DocumentJob))
        assert job is not None and job.status == "queued"


def test_flag_off_still_fetch_failed(tmp_path, monkeypatch) -> None:
    SessionLocal = _wire(tmp_path)
    monkeypatch.setenv("INTEL_PDF_QUEUE_ENABLED", "0")

    def boom(*a, **k):
        raise ValueError("pdf_too_large: 15000000 > 12000000")

    monkeypatch.setattr(fc, "fetch_and_extract", boom)
    monkeypatch.setattr(fc, "scrapling_l15_available", lambda: False)
    monkeypatch.setattr(fc, "scrapling_available", lambda: False)
    monkeypatch.setattr(fc, "circuit_breaker_enabled", lambda: False)

    with SessionLocal() as session:
        session.add(_cand(url_hash="pdf2"))
        session.commit()
        out = fc.fetch_discovered_candidates(
            session,
            LocalBlobStore(tmp_path / "b"),
            resolve_dns=False,
            enable_l2=False,
            enable_l15=False,
            enable_jina=False,
        )
        assert out.get("pdf_queued", 0) == 0
        assert out["failed"] == 1
        row = session.scalar(select(ReviewCandidate))
        assert row.status == "fetch_failed"


def test_worker_to_pending_review(tmp_path, monkeypatch) -> None:
    SessionLocal = _wire(tmp_path)
    monkeypatch.setenv("INTEL_PDF_QUEUE_ENABLED", "1")
    from test_pdf_fetch import _minimal_pdf_with_text

    data = _minimal_pdf_with_text()

    def fake_dl(url, **k):
        return data, url

    monkeypatch.setattr(pq, "_download_pdf", fake_dl)

    with SessionLocal() as session:
        row = _cand(url_hash="pdf3", status="pdf_queued", fetch_status="pdf_queued")
        session.add(row)
        session.flush()
        session.add(
            DocumentJob(
                candidate_id=row.id,
                url=row.original_url,
                url_hash=row.url_hash,
                status="queued",
                attempts=0,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
        )
        session.commit()
        out = pq.process_pdf_queue(
            session, LocalBlobStore(tmp_path / "b"), limit=5, resolve_dns=False
        )
        assert out["ok"] == 1
        session.refresh(row)
        assert row.status == "pending_review"
        assert "Indonesia" in (row.extracted_text or "")


def test_sha_dedupe_reuses(tmp_path, monkeypatch) -> None:
    SessionLocal = _wire(tmp_path)
    monkeypatch.setenv("INTEL_PDF_QUEUE_ENABLED", "1")
    from test_pdf_fetch import _minimal_pdf_with_text

    data = _minimal_pdf_with_text()
    sha = __import__("hashlib").sha256(data).hexdigest()
    monkeypatch.setattr(pq, "_download_pdf", lambda url, **k: (data, url))

    with SessionLocal() as session:
        prior = _cand(
            url_hash="prior",
            original_url="https://example.com/old.pdf",
            canonical_url="https://example.com/old.pdf",
            status="pending_review",
            fetch_status="ok",
            content_hash=sha,
            extracted_text="Prior Indonesia factory text body for dedupe reuse.",
            title="Prior",
        )
        session.add(prior)
        session.flush()
        session.add(
            DocumentJob(
                candidate_id=prior.id,
                url=prior.original_url,
                url_hash=prior.url_hash,
                status="done",
                sha256=sha,
                storage_path="blobs/x.pdf",
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
        )
        row = _cand(url_hash="pdf4", status="pdf_queued", fetch_status="pdf_queued")
        session.add(row)
        session.flush()
        session.add(
            DocumentJob(
                candidate_id=row.id,
                url=row.original_url,
                url_hash=row.url_hash,
                status="queued",
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
        )
        session.commit()
        out = pq.process_pdf_queue(
            session, LocalBlobStore(tmp_path / "b"), limit=5, resolve_dns=False
        )
        assert out["ok"] == 1
        assert out["details"][0].get("reused") is True
        session.refresh(row)
        assert "Prior Indonesia" in (row.extracted_text or "")


def test_empty_extraction_terminal(tmp_path, monkeypatch) -> None:
    SessionLocal = _wire(tmp_path)
    monkeypatch.setenv("INTEL_PDF_QUEUE_ENABLED", "1")
    emptyish = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF"

    monkeypatch.setattr(pq, "_download_pdf", lambda url, **k: (emptyish, url))

    def boom_extract(*a, **k):
        raise ValueError("pdf_empty_extraction")

    monkeypatch.setattr(pq, "extract_pdf_text", boom_extract)

    with SessionLocal() as session:
        row = _cand(url_hash="pdf5", status="pdf_queued", fetch_status="pdf_queued")
        session.add(row)
        session.flush()
        session.add(
            DocumentJob(
                candidate_id=row.id,
                url=row.original_url,
                url_hash=row.url_hash,
                status="queued",
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
        )
        session.commit()
        out = pq.process_pdf_queue(
            session, LocalBlobStore(tmp_path / "b"), limit=5, resolve_dns=False
        )
        assert out["failed"] == 1
        session.refresh(row)
        assert row.status == "fetch_failed"
        assert row.fetch_error_type == "pdf_empty_extraction"


def test_revert_queued(tmp_path, monkeypatch) -> None:
    SessionLocal = _wire(tmp_path)
    with SessionLocal() as session:
        row = _cand(url_hash="pdf6", status="pdf_queued", fetch_status="pdf_queued")
        session.add(row)
        session.flush()
        session.add(
            DocumentJob(
                candidate_id=row.id,
                url=row.original_url,
                url_hash=row.url_hash,
                status="queued",
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
        )
        session.commit()
        n = pq.revert_queued_to_failed(session)
        session.commit()
        assert n == 1
        session.refresh(row)
        assert row.status == "fetch_failed"


def test_pdf_download_rechecks_redirect_ssrf(monkeypatch) -> None:
    import httpx
    from fetch.ssrf import UnsafeURLError

    class FakeResp:
        def __init__(self, *, is_redirect=False, location=None, url="https://example.com/a.pdf"):
            self.is_redirect = is_redirect
            self.headers = {"location": location} if location else {}
            self.url = httpx.URL(url)
            self._content = b"%PDF-1.4 fake"

        def iter_bytes(self):
            yield self._content

        @property
        def content(self):
            return self._content

    calls = {"n": 0}

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, url):
            calls["n"] += 1
            if "evil" in url or "127.0.0.1" in url:
                raise AssertionError("must not request private hop")
            if calls["n"] == 1:
                return FakeResp(
                    is_redirect=True,
                    location="http://127.0.0.1/secret.pdf",
                    url=url,
                )
            return FakeResp()

    monkeypatch.setattr(pq.httpx, "Client", FakeClient)
    try:
        pq._download_pdf("https://example.com/a.pdf", resolve_dns=True)
        raised = False
    except (UnsafeURLError, ValueError, Exception):
        raised = True
    assert raised is True
    assert calls["n"] == 1


def test_pdf_queued_not_confirmable(tmp_path) -> None:
    import pytest

    SessionLocal = _wire(tmp_path)
    with SessionLocal() as session:
        row = _cand(url_hash="pdf7", status="pdf_queued", fetch_status="pdf_queued")
        session.add(row)
        session.commit()
        with pytest.raises(ValueError, match="pdf_queued"):
            confirm_candidate(session, row.id, actor="t")
