from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.main import create_app
from app.models import ReviewCandidate


def _wire_db(tmp_path, monkeypatch):
    from app import db as dbmod

    engine = create_engine(
        f"sqlite:///{tmp_path / 'app.db'}",
        future=True,
        connect_args={"check_same_thread": False},
    )
    dbmod.engine = engine
    dbmod.SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    Base.metadata.create_all(engine)
    monkeypatch.setattr("app.config.settings.api_key", "dev-local-key")
    monkeypatch.setattr("app.config.settings.blob_root", str(tmp_path / "blobs"))
    return TestClient(create_app()), dbmod.SessionLocal


def test_dashboard_index_served(tmp_path, monkeypatch) -> None:
    client, _ = _wire_db(tmp_path, monkeypatch)
    r = client.get("/app/")
    assert r.status_code == 200
    assert "Indonesia Intel" in r.text
    assert "API Key" in r.text
    text = r.text
    assert 'data-tab="feed"' in text
    assert 'data-tab="stats"' in text
    assert 'data-tab="review"' in text
    assert "formal_events" in text


def test_dashboard_assets_served(tmp_path, monkeypatch) -> None:
    client, _ = _wire_db(tmp_path, monkeypatch)
    css = client.get("/app/tokens.css")
    assert css.status_code == 200
    assert "--color-accent" in css.text
    js = client.get("/app/app.js")
    assert js.status_code == 200
    assert "indonesia-intel.apiKey" in js.text
    assert "auto-fetch" in (client.get("/app/").text)
    assert "autoFetch" in js.text
    assert "textContent" in js.text
    assert "innerHTML = detail" not in js.text
    assert "/pipeline/summary" in js.text
    assert "/stats" in js.text


def test_fetch_requires_api_key(tmp_path, monkeypatch) -> None:
    client, _ = _wire_db(tmp_path, monkeypatch)
    r = client.post("/fetch", json={"limit": 5})
    assert r.status_code == 401


def test_fetch_discovered_to_pending(tmp_path, monkeypatch) -> None:
    client, SessionLocal = _wire_db(tmp_path, monkeypatch)
    html = b"<html><body><article><p>Factory in Indonesia</p></article></body></html>"
    with SessionLocal() as session:
        session.add(
            ReviewCandidate(
                run_id="t1",
                provider="mock",
                query="q",
                original_url="https://example.com/news/a",
                canonical_url="https://example.com/news/a",
                url_hash="abc",
                title="A",
                snippet="s",
                status="discovered",
            )
        )
        session.commit()

    import jobs.fetch_candidates as fc

    page = type(
        "Page",
        (),
        {
            "html": html,
            "text": "Factory in Indonesia",
            "title": "Plant",
            "final_url": "https://example.com/news/a",
        },
    )()
    monkeypatch.setattr(fc, "fetch_and_extract", lambda *a, **k: page)

    r = client.post("/fetch", json={"limit": 10}, headers={"X-API-Key": "dev-local-key"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["fetched"] == 1
    assert body["failed"] == 0

    listed = client.get(
        "/candidates?status=pending_review",
        headers={"X-API-Key": "dev-local-key"},
    )
    assert listed.status_code == 200
    assert len(listed.json()["items"]) == 1


def test_web_dir_exists() -> None:
    root = Path(__file__).resolve().parent.parent / "web"
    assert (root / "index.html").is_file()
    assert (root / "app.js").is_file()
    assert (root / "tokens.css").is_file()
