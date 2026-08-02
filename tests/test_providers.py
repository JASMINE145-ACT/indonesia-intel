import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from providers import SearchResult, get_default_provider, get_provider
from providers.brave import MockBraveProvider
from providers.exa import ExaSearchProvider, map_exa_results
from providers.tavily import TavilySearchProvider, map_tavily_results
from storage.blob import LocalBlobStore


@pytest.mark.asyncio
async def test_mock_brave_returns_unified_search_result_shape() -> None:
    provider = MockBraveProvider()
    hits = await provider.search("Chinese investment Indonesia")
    assert hits
    hit = hits[0]
    assert isinstance(hit, SearchResult)
    assert hit.provider == "brave_mock"
    assert hit.query == "Chinese investment Indonesia"
    assert hit.title
    assert hit.url.startswith("http")
    assert hit.source_domain
    assert isinstance(hit.raw, dict)


def test_default_provider_is_mock_when_no_keys() -> None:
    p = get_default_provider(brave_enabled=False, brave_api_key="")
    assert p.name == "brave_mock"


def test_default_provider_prefers_exa() -> None:
    p = get_default_provider(exa_api_key="exa-key", tavily_api_key="tav-key")
    assert p.name == "exa"


def test_default_provider_prefers_tavily_when_no_exa() -> None:
    p = get_default_provider(tavily_api_key="tav-key")
    assert p.name == "tavily"


def test_live_brave_requires_api_key() -> None:
    from providers.brave import BraveNewsProvider

    with pytest.raises(ValueError):
        BraveNewsProvider("")


def test_exa_requires_api_key() -> None:
    with pytest.raises(ValueError):
        ExaSearchProvider("")


def test_tavily_requires_api_key() -> None:
    with pytest.raises(ValueError):
        TavilySearchProvider("")


def test_get_provider_exa() -> None:
    p = get_provider("exa", exa_api_key="test-key")
    assert isinstance(p, ExaSearchProvider)
    assert p.name == "exa"


def test_get_provider_tavily() -> None:
    p = get_provider("tavily", tavily_api_key="test-key")
    assert isinstance(p, TavilySearchProvider)
    assert p.name == "tavily"


def test_get_provider_brave_not_available() -> None:
    with pytest.raises(ValueError, match="not available"):
        get_provider("brave", brave_enabled=True, brave_api_key="k")


def test_get_provider_mock() -> None:
    p = get_provider("mock")
    assert p.name == "brave_mock"


def test_get_available_providers_returns_configured() -> None:
    from providers.factory import get_available_providers

    provs = get_available_providers(exa_api_key="k1", tavily_api_key="k2")
    names = [p.name for p in provs]
    assert "exa" in names
    assert "tavily" in names
    assert "brave_mock" not in names


def test_get_available_providers_fallback_to_mock() -> None:
    from providers.factory import get_available_providers

    provs = get_available_providers()
    assert len(provs) == 1
    assert provs[0].name == "brave_mock"


def test_map_exa_results_shape() -> None:
    class Item:
        id = "exa-1"
        url = "https://news.example/id/plant"
        title = "Plant news"
        text = "Chinese firm expands in Indonesia"
        published_date = "2026-01-15T12:00:00+00:00"
        score = 0.91

    class Resp:
        results = [Item()]

    hits = map_exa_results("q", Resp())
    assert len(hits) == 1
    assert hits[0].provider == "exa"
    assert hits[0].url.startswith("https://")
    assert hits[0].source_domain == "news.example"
    assert hits[0].snippet.startswith("Chinese")


def test_map_tavily_results_shape() -> None:
    resp = {
        "results": [
            {
                "url": "https://tavily.example/a",
                "title": "Tavily hit",
                "content": "Investment summary",
                "published_date": "2026-02-01",
                "score": 0.8,
            }
        ]
    }
    hits = map_tavily_results("q", resp)
    assert hits[0].provider == "tavily"
    assert hits[0].title == "Tavily hit"
    assert hits[0].source_domain == "tavily.example"


@pytest.mark.asyncio
async def test_exa_provider_uses_injected_client() -> None:
    class Item:
        id = "1"
        url = "https://example.com/x"
        title = "X"
        text = "body"
        published_date = None
        score = 1.0

    class Resp:
        results = [Item()]

    class Client:
        def search_and_contents(self, query, **kwargs):
            assert query == "china indonesia"
            return Resp()

    p = ExaSearchProvider("k", client=Client())
    hits = await p.search("china indonesia")
    assert hits[0].provider == "exa"
    assert hits[0].url == "https://example.com/x"


@pytest.mark.asyncio
async def test_tavily_provider_uses_injected_client() -> None:
    class Client:
        def search(self, query, **kwargs):
            return {
                "results": [
                    {
                        "url": "https://example.com/t",
                        "title": "T",
                        "content": "c",
                        "score": 0.5,
                    }
                ]
            }

    p = TavilySearchProvider("k", client=Client())
    hits = await p.search("q")
    assert hits[0].provider == "tavily"


def test_blob_put_get_roundtrip(tmp_path) -> None:
    store = LocalBlobStore(tmp_path / "blobs")
    key = store.put_bytes(b"hello-indonesia", suffix=".txt")
    assert store.exists(key)
    assert store.get_bytes(key) == b"hello-indonesia"
    key2 = store.put_bytes(b"hello-indonesia", suffix=".txt")
    assert key == key2


def test_health_endpoint() -> None:
    client = TestClient(create_app())
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["phase"] == 7
    assert "exa_configured" in body
    assert "tavily_configured" in body
    assert body.get("dashboard") == "/app/"
