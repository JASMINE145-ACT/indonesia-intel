from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient

from app.db import Base
from app.main import create_app


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
    monkeypatch.setattr("app.config.settings.exa_api_key", "")
    monkeypatch.setattr("app.config.settings.tavily_api_key", "")
    monkeypatch.setattr("app.config.settings.brave_enabled", False)
    monkeypatch.setattr("app.config.settings.brave_api_key", "")
    return TestClient(create_app())


def test_search_requires_api_key(tmp_path, monkeypatch) -> None:
    client = _wire_db(tmp_path, monkeypatch)
    r = client.post("/search", json={"query": "china indonesia", "provider": "mock"})
    assert r.status_code == 401


def test_search_mock_ingests(tmp_path, monkeypatch) -> None:
    client = _wire_db(tmp_path, monkeypatch)
    r = client.post(
        "/search",
        json={"query": "china indonesia", "provider": "mock"},
        headers={"X-API-Key": "dev-local-key"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["provider"] == "brave_mock"
    assert body["hits"] >= 1
    assert body["inserted"] >= 1


def test_search_unknown_provider_400(tmp_path, monkeypatch) -> None:
    client = _wire_db(tmp_path, monkeypatch)
    r = client.post(
        "/search",
        json={"query": "q", "provider": "nope"},
        headers={"X-API-Key": "dev-local-key"},
    )
    assert r.status_code == 400


def test_search_brave_not_available_400(tmp_path, monkeypatch) -> None:
    client = _wire_db(tmp_path, monkeypatch)
    r = client.post(
        "/search",
        json={"query": "q", "provider": "brave"},
        headers={"X-API-Key": "dev-local-key"},
    )
    assert r.status_code == 400
    assert "not available" in r.json()["detail"]


def test_providers_lists_available(tmp_path, monkeypatch) -> None:
    client = _wire_db(tmp_path, monkeypatch)
    monkeypatch.setattr("app.config.settings.exa_api_key", "exa-k")
    monkeypatch.setattr("app.config.settings.tavily_api_key", "tav-k")
    r = client.get("/providers", headers={"X-API-Key": "dev-local-key"})
    assert r.status_code == 200
    body = r.json()
    assert "exa" in body["available"]
    assert "tavily" in body["available"]
    assert body["default"] == "exa"


def test_search_exa_with_injected_mapping(tmp_path, monkeypatch) -> None:
    client = _wire_db(tmp_path, monkeypatch)
    monkeypatch.setattr("app.config.settings.exa_api_key", "exa-k")

    class FakeExa:
        name = "exa"

        async def search(self, query, **kwargs):
            from providers.base import SearchResult

            return [
                SearchResult(
                    provider="exa",
                    query=query,
                    title="Exa hit",
                    url="https://exa.test/hit",
                    snippet="s",
                    source_domain="exa.test",
                    provider_rank=1,
                )
            ]

    monkeypatch.setattr(
        "api.search.get_provider",
        lambda name, **kw: FakeExa(),
    )
    r = client.post(
        "/search",
        json={"query": "china", "provider": "exa"},
        headers={"X-API-Key": "dev-local-key"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["provider"] == "exa"
    assert r.json()["inserted"] == 1
