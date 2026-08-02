from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.config import settings
from app.main import create_app
from app.models import FormalEvent, ReviewCandidate


def _client(tmp_path):
    from app import db as dbmod

    engine = create_engine(
        f"sqlite:///{tmp_path / 'api_intel.db'}",
        future=True,
        connect_args={"check_same_thread": False},
    )
    dbmod.engine = engine
    dbmod.SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    Base.metadata.create_all(engine)
    return TestClient(create_app()), dbmod.SessionLocal


HEADERS = {"X-API-Key": settings.api_key}


def test_taxonomy_requires_api_key(tmp_path) -> None:
    client, _ = _client(tmp_path)
    assert client.get("/taxonomy").status_code == 401
    r = client.get("/taxonomy", headers=HEADERS)
    assert r.status_code == 200
    assert "汽车、工程机械与交通装备" in r.json()["industries"]


def test_company_create_list_roundtrip(tmp_path) -> None:
    client, _ = _client(tmp_path)
    created = client.post(
        "/companies",
        headers=HEADERS,
        json={"name_cn": "比亚迪", "industry": "汽车、工程机械与交通装备"},
    )
    assert created.status_code == 200
    company_id = created.json()["id"]

    listed = client.get("/companies", headers=HEADERS)
    assert listed.status_code == 200
    assert any(c["id"] == company_id for c in listed.json()["items"])


def test_company_create_rejects_bad_industry(tmp_path) -> None:
    client, _ = _client(tmp_path)
    r = client.post("/companies", headers=HEADERS, json={"name_cn": "X", "industry": "乱写"})
    assert r.status_code == 400


def test_project_create_list_roundtrip(tmp_path) -> None:
    client, _ = _client(tmp_path)
    r = client.post("/projects", headers=HEADERS, json={"name": "某项目", "stage": "签约"})
    assert r.status_code == 200
    listed = client.get("/projects", headers=HEADERS)
    assert listed.json()["count"] == 1


def test_project_update_missing_id_returns_404(tmp_path) -> None:
    client, _ = _client(tmp_path)
    r = client.post("/projects", headers=HEADERS, json={"project_id": 999, "stage": "建设"})
    assert r.status_code == 404


def test_stats_endpoint_shape(tmp_path) -> None:
    client, SessionLocal = _client(tmp_path)
    with SessionLocal() as session:
        session.add(
            FormalEvent(
                candidate_id=1,
                title="事件",
                canonical_url="https://example.com/1",
                provider="mock",
                industry="汽车、工程机械与交通装备",
            )
        )
        session.commit()

    r = client.get("/stats", headers=HEADERS)
    assert r.status_code == 200
    body = r.json()
    assert body["industry_distribution"] == [
        {"industry": "汽车、工程机械与交通装备", "count": 1}
    ]


def test_factcheck_endpoint_missing_event_returns_404(tmp_path) -> None:
    client, _ = _client(tmp_path)
    r = client.get("/formal-events/999/factcheck", headers=HEADERS)
    assert r.status_code == 404


def test_event_sources_roundtrip(tmp_path) -> None:
    client, SessionLocal = _client(tmp_path)
    with SessionLocal() as session:
        event = FormalEvent(
            candidate_id=1, title="事件", canonical_url="https://example.com/1", provider="mock"
        )
        session.add(event)
        session.commit()
        event_id = event.id

    listed_empty = client.get(f"/formal-events/{event_id}/sources", headers=HEADERS)
    assert listed_empty.json()["count"] == 0

    added = client.post(
        f"/formal-events/{event_id}/sources",
        headers=HEADERS,
        json={"url": "https://gov.example.id/press", "label": "政府声明"},
    )
    assert added.status_code == 200

    listed = client.get(f"/formal-events/{event_id}/sources", headers=HEADERS)
    assert listed.json()["count"] == 1
    assert listed.json()["items"][0]["label"] == "政府声明"


def test_event_sources_missing_event_returns_404(tmp_path) -> None:
    client, _ = _client(tmp_path)
    r = client.post(
        "/formal-events/999/sources", headers=HEADERS, json={"url": "https://example.com/x"}
    )
    assert r.status_code == 404


def test_export_events_csv_endpoint(tmp_path) -> None:
    client, SessionLocal = _client(tmp_path)
    with SessionLocal() as session:
        session.add(
            FormalEvent(
                candidate_id=1,
                title="事件",
                canonical_url="https://example.com/1",
                provider="mock",
                industry="汽车、工程机械与交通装备",
            )
        )
        session.commit()

    r = client.get("/export/events.csv", headers=HEADERS)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert "事件" in r.text


def test_dedup_check_endpoint(tmp_path) -> None:
    client, SessionLocal = _client(tmp_path)
    with SessionLocal() as session:
        session.add(
            ReviewCandidate(
                run_id="r1",
                provider="mock",
                query="q",
                original_url="https://example.com/a",
                canonical_url="https://example.com/a",
                url_hash="h1",
                title="某事件标题",
                snippet="",
                status="pending_review",
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
        )
        session.commit()
        cid = session.query(ReviewCandidate).one().id

    r = client.get(f"/candidates/{cid}/dedup-check", headers=HEADERS)
    assert r.status_code == 200
    assert r.json()["candidate_id"] == cid
