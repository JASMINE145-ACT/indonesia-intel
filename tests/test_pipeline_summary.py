"""Pipeline summary API — WANd.INTEL.PIPELINE_SUMMARY.001."""

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.main import create_app
from app.models import ReviewCandidate


def _wire(tmp_path, monkeypatch):
    from app import db as dbmod

    engine = create_engine(
        f"sqlite:///{tmp_path / 'pipe.db'}",
        future=True,
        connect_args={"check_same_thread": False},
    )
    dbmod.engine = engine
    dbmod.SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    Base.metadata.create_all(engine)
    monkeypatch.setattr("app.config.settings.api_key", "dev-local-key")
    monkeypatch.setattr("app.config.settings.blob_root", str(tmp_path / "blobs"))
    return TestClient(create_app()), dbmod.SessionLocal


def test_pipeline_summary_counts(tmp_path, monkeypatch) -> None:
    client, SessionLocal = _wire(tmp_path, monkeypatch)
    with SessionLocal() as session:
        for i, st in enumerate(("discovered", "discovered", "pending_review")):
            session.add(
                ReviewCandidate(
                    run_id=f"r{i}",
                    provider="rss",
                    query="q",
                    original_url=f"https://www.example.com/{i}",
                    canonical_url=f"https://www.example.com/{i}",
                    url_hash=f"h{i}",
                    title=f"T{i}",
                    snippet="",
                    status=st,
                    discovery_method="rss" if i < 2 else "listing",
                )
            )
        session.commit()

    r = client.get("/pipeline/summary", headers={"X-API-Key": "dev-local-key"})
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 3
    assert body["counts_by_status"]["discovered"] == 2
    assert body["counts_by_status"]["pending_review"] == 1
    assert body["counts_by_discovery_method"]["rss"] == 2
    assert body["counts_by_discovery_method"]["listing"] == 1


def test_pipeline_summary_requires_key(tmp_path, monkeypatch) -> None:
    client, _ = _wire(tmp_path, monkeypatch)
    assert client.get("/pipeline/summary").status_code == 401
