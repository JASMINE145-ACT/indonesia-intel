"""Fetch resolved URL + hash collision — WANd.INTEL.FETCH_RESOLVED_URL.001."""

from datetime import datetime, timezone
from types import SimpleNamespace

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import ReviewCandidate
from dedup.url import normalize_url, url_hash
from jobs.fetch_candidates import fetch_discovered_candidates
from storage.blob import LocalBlobStore


def _session(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'fr.db'}",
        future=True,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)()


def _cand(url: str, **kw) -> ReviewCandidate:
    return ReviewCandidate(
        run_id=kw.get("run_id", "r1"),
        provider="mock",
        query="q",
        original_url=url,
        canonical_url=normalize_url(url),
        url_hash=url_hash(url),
        title="t",
        snippet="",
        status="discovered",
        fetch_status="not_attempted",
        discovery_method=kw.get("discovery_method", "rss"),
        resolution_status=kw.get("resolution_status", "not_required"),
        resolved_url=kw.get("resolved_url"),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


def test_fetch_uses_resolved_url(tmp_path, monkeypatch) -> None:
    session = _session(tmp_path)
    blob = LocalBlobStore(tmp_path / "blobs")
    resolved = "https://www.example.com/resolved-page"
    row = _cand(
        "https://news.google.com/articles/ABC",
        resolution_status="resolved",
        resolved_url=resolved,
    )
    session.add(row)
    session.commit()

    seen: list[str] = []

    def fake_fetch(url, resolve_dns=True, html_override=None, **kwargs):
        seen.append(url)
        html = html_override or b"<html><title>R</title><body>hello world article text enough</body></html>"
        return SimpleNamespace(
            html=html,
            text="hello world article text enough",
            title="R",
            final_url=url,
            content_kind="html",
            status_code=200,
        )
    
    monkeypatch.setattr("jobs.fetch_candidates.fetch_and_extract", fake_fetch)
    monkeypatch.setattr("jobs.fetch_candidates.page_is_invalid", lambda p: SimpleNamespace(ok=True))
    monkeypatch.setattr("jobs.fetch_candidates.fetch_l2_enabled", lambda: False)

    out = fetch_discovered_candidates(session, blob, enable_l2=False, enable_l15=False)
    assert out["fetched"] == 1
    assert seen == [resolved]
    session.refresh(row)
    assert row.status == "pending_review"
    assert row.fetch_status == "ok"


def test_fetch_uses_original_when_not_resolved(tmp_path, monkeypatch) -> None:
    session = _session(tmp_path)
    blob = LocalBlobStore(tmp_path / "blobs")
    original = "https://www.example.com/orig"
    row = _cand(original)
    session.add(row)
    session.commit()
    seen: list[str] = []

    def fake_fetch(url, resolve_dns=True, html_override=None, **kwargs):
        seen.append(url)
        html = b"<html><title>O</title><body>original body text content here</body></html>"
        return SimpleNamespace(
            html=html,
            text="original body text content here",
            title="O",
            final_url=url,
            content_kind="html",
            status_code=200,
        )

    monkeypatch.setattr("jobs.fetch_candidates.fetch_and_extract", fake_fetch)
    monkeypatch.setattr("jobs.fetch_candidates.page_is_invalid", lambda p: SimpleNamespace(ok=True))
    monkeypatch.setattr("jobs.fetch_candidates.fetch_l2_enabled", lambda: False)

    fetch_discovered_candidates(session, blob, enable_l2=False, enable_l15=False)
    assert seen == [original]


def test_hash_collision_does_not_abort_batch(tmp_path, monkeypatch) -> None:
    session = _session(tmp_path)
    blob = LocalBlobStore(tmp_path / "blobs")
    shared_final = "https://www.example.com/same-final"
    existing = _cand(shared_final, run_id="r0")
    existing.status = "pending_review"
    existing.fetch_status = "ok"
    colliding = _cand("https://www.example.com/alias", run_id="r1")
    ok_row = _cand("https://www.example.com/other", run_id="r1")
    session.add_all([existing, colliding, ok_row])
    session.commit()

    def fake_fetch(url, resolve_dns=True, html_override=None, **kwargs):
        final = shared_final if "alias" in url else url
        html = f"<html><title>X</title><body>body for {url} with enough text</body></html>".encode()
        return SimpleNamespace(
            html=html,
            text=f"body for {url} with enough text",
            title="X",
            final_url=final,
            content_kind="html",
            status_code=200,
        )

    monkeypatch.setattr("jobs.fetch_candidates.fetch_and_extract", fake_fetch)
    monkeypatch.setattr("jobs.fetch_candidates.page_is_invalid", lambda p: SimpleNamespace(ok=True))
    monkeypatch.setattr("jobs.fetch_candidates.fetch_l2_enabled", lambda: False)

    out = fetch_discovered_candidates(
        session, blob, enable_l2=False, enable_l15=False, run_id="r1"
    )
    assert out["fetched"] >= 1
    assert out["failed"] >= 1
    session.expire_all()
    coll = session.scalar(
        select(ReviewCandidate).where(ReviewCandidate.original_url.contains("alias"))
    )
    good = session.scalar(
        select(ReviewCandidate).where(ReviewCandidate.original_url.contains("other"))
    )
    assert coll.status == "ignored"
    assert coll.fetch_error_type == "url_hash_collision"
    assert good.status == "pending_review"
    assert good.fetch_status == "ok"
