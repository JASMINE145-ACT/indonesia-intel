from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.main import create_app
from app.models import FormalEvent, ReviewCandidate, ReviewDecision
from app.config import settings
from jobs.fetch_candidates import fetch_discovered_candidates
from storage.blob import LocalBlobStore


FIXTURE_HTML = b"""<!doctype html><html><head><title>Plant News</title></head>
<body><article><p>Chinese company builds factory in Indonesia Subang.</p></article></body></html>"""


def _session(tmp_path):
    db = tmp_path / "t.db"
    engine = create_engine(f"sqlite:///{db}", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)()


def test_review_requires_api_key(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'app.db'}")
    from app import db as dbmod

    engine = create_engine(f"sqlite:///{tmp_path / 'app.db'}", future=True, connect_args={"check_same_thread": False})
    dbmod.engine = engine
    dbmod.SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    Base.metadata.create_all(engine)

    client = TestClient(create_app())
    r = client.get("/candidates")
    assert r.status_code == 401


def test_e2e_search_fetch_confirm(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "e2e.db"
    engine = create_engine(
        f"sqlite:///{db_path}", future=True, connect_args={"check_same_thread": False}
    )
    from app import db as dbmod

    dbmod.engine = engine
    dbmod.SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    Base.metadata.create_all(engine)

    blob = LocalBlobStore(tmp_path / "blobs")
    session = dbmod.SessionLocal()
    url = "https://example.com/news/plant"
    session.add(
        ReviewCandidate(
            run_id="e2e1",
            provider="brave_mock",
            query="test",
            original_url=url,
            canonical_url=url,
            url_hash="abc123deadbeef",
            title="Plant News",
            snippet="",
            status="discovered",
            raw_search_json="{}",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
    )
    session.commit()

    summary = fetch_discovered_candidates(
        session,
        blob,
        resolve_dns=False,
        html_overrides={url: FIXTURE_HTML},
    )
    assert summary["fetched"] == 1
    row = session.scalar(select(ReviewCandidate))
    assert row.status == "pending_review"
    assert row.object_key
    cid = row.id
    session.close()

    client = TestClient(create_app())
    headers = {"X-API-Key": settings.api_key}
    listed = client.get("/candidates", headers=headers)
    assert listed.status_code == 200
    assert any(i["id"] == cid for i in listed.json()["items"])

    bad = client.post(f"/candidates/{cid}/confirm")
    assert bad.status_code == 401

    ok = client.post(f"/candidates/{cid}/confirm", headers=headers, json={})
    assert ok.status_code == 200
    assert ok.json()["status"] == "confirmed"

    session = dbmod.SessionLocal()
    assert session.scalar(select(ReviewDecision)) is not None
    assert session.scalar(select(FormalEvent)) is not None
    session.close()


def test_manual_intake_endpoint(tmp_path) -> None:
    db_path = tmp_path / "manual.db"
    engine = create_engine(
        f"sqlite:///{db_path}", future=True, connect_args={"check_same_thread": False}
    )
    from app import db as dbmod

    dbmod.engine = engine
    dbmod.SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    Base.metadata.create_all(engine)

    client = TestClient(create_app())
    headers = {"X-API-Key": settings.api_key}

    r = client.post(
        "/candidates/manual",
        headers=headers,
        json={
            "title": "闭门交流纪要",
            "text": "某企业负责人透露的非公开计划。",
            "source_attribution": "商务交流",
            "is_public_source": False,
        },
    )
    assert r.status_code == 200
    cid = r.json()["id"]

    confirmed = client.post(f"/candidates/{cid}/confirm", headers=headers, json={})
    assert confirmed.status_code == 200

    session = dbmod.SessionLocal()
    event = session.scalar(select(FormalEvent).where(FormalEvent.candidate_id == cid))
    assert event.is_public is False
    session.close()


def test_manual_intake_rejects_missing_title(tmp_path) -> None:
    db_path = tmp_path / "manual2.db"
    engine = create_engine(
        f"sqlite:///{db_path}", future=True, connect_args={"check_same_thread": False}
    )
    from app import db as dbmod

    dbmod.engine = engine
    dbmod.SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    Base.metadata.create_all(engine)

    client = TestClient(create_app())
    headers = {"X-API-Key": settings.api_key}
    r = client.post("/candidates/manual", headers=headers, json={"title": "", "url": "https://example.com/a"})
    assert r.status_code == 400
