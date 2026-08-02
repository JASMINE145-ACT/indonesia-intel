"""Candidate detail + pipeline summary — ops dashboard APIs."""

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.main import create_app
from app.models import ReviewCandidate
from jobs.ops_dashboard import EXTRACTED_TEXT_LIMIT


def _wire(tmp_path, monkeypatch):
    from app import db as dbmod

    engine = create_engine(
        f"sqlite:///{tmp_path / 'ops.db'}",
        future=True,
        connect_args={"check_same_thread": False},
    )
    dbmod.engine = engine
    dbmod.SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    Base.metadata.create_all(engine)
    monkeypatch.setattr("app.config.settings.api_key", "dev-local-key")
    monkeypatch.setattr("app.config.settings.blob_root", str(tmp_path / "blobs"))
    return TestClient(create_app()), dbmod.SessionLocal


def test_candidate_detail_404(tmp_path, monkeypatch) -> None:
    client, _ = _wire(tmp_path, monkeypatch)
    r = client.get("/candidates/99999", headers={"X-API-Key": "dev-local-key"})
    assert r.status_code == 404


def test_candidate_detail_and_truncate(tmp_path, monkeypatch) -> None:
    client, SessionLocal = _wire(tmp_path, monkeypatch)
    big = "字" * (EXTRACTED_TEXT_LIMIT + 100)
    with SessionLocal() as session:
        session.add(
            ReviewCandidate(
                run_id="r1",
                provider="listing",
                query="q",
                original_url="https://www.example.com/a",
                canonical_url="https://www.example.com/a",
                url_hash="h1",
                title="T",
                snippet="sn",
                extracted_text=big,
                status="discovered",
                source_id="bisnis",
                discovery_method="listing",
            )
        )
        session.commit()
        cid = session.scalar(select(ReviewCandidate.id).limit(1))

    assert cid is not None
    r = client.get(f"/candidates/{cid}", headers={"X-API-Key": "dev-local-key"})
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == cid
    assert body["source_id"] == "bisnis"
    assert body["discovery_method"] == "listing"
    assert body["extracted_text_truncated"] is True
    assert len(body["extracted_text"]) == EXTRACTED_TEXT_LIMIT
    assert body["url"].startswith("https://")

