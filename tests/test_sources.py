from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import ReviewCandidate
from dedup.url import url_hash
from jobs.ingest_search import run_search_ingest
from providers.brave import MockBraveProvider
from sources import SourceRegistry

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "sources" / "registry.yaml"


def test_registry_loads_deep_research_prefer_pool() -> None:
    reg = SourceRegistry.load(REGISTRY)
    assert len(reg.all()) >= 30
    assert len(reg.enabled()) >= 28
    must = {
        "cninfo",
        "sse",
        "szse",
        "hkexnews",
        "mofcom_fdi_guide",
        "mofcom_id_embassy",
        "bkpm",
        "kemenperin",
        "esdm",
        "idx",
        "ojk",
        "kadin",
        "antara",
        "kompas",
        "imip",
        "reuters",
        "worldbank_id",
        "imf_id",
        "unctad_wir",
        "iea_id",
        "dealstreetasia",
    }
    ids = {s.id for s in reg.all()}
    missing = must - ids
    assert not missing, f"missing prefer sources: {missing}"
    prefer_a = reg.prefer_a()
    assert len(prefer_a) >= 20
    regions = {s.region for s in prefer_a}
    assert {"CN", "ID", "INT"} <= regions
    assert reg.get("disabled_sample") is not None
    assert reg.get("disabled_sample").enabled is False
    assert any(s.rss_url for s in reg.rss_ready())


def test_rss_ready_rollout_covers_multiple_native_feeds() -> None:
    reg = SourceRegistry.load(REGISTRY)
    ready = reg.rss_ready()
    assert len(ready) >= 8
    ids = {s.id for s in ready}
    assert "antara" in ids
    assert {"cnbc_indonesia", "tempo_en", "kontan_en"} & ids


def test_registry_rejects_empty(tmp_path) -> None:
    p = tmp_path / "empty.yaml"
    p.write_text("sources: []\n", encoding="utf-8")
    with pytest.raises(ValueError, match="empty"):
        SourceRegistry.load(p)


def test_disabled_source_blocks_fetch() -> None:
    reg = SourceRegistry.load(REGISTRY)
    with pytest.raises(PermissionError, match="disabled"):
        reg.assert_fetch_allowed("disabled_sample")


def test_enabled_source_allows() -> None:
    reg = SourceRegistry.load(REGISTRY)
    src = reg.assert_fetch_allowed("kompas")
    assert src.domain == "kompas.com"


def _session(tmp_path):
    db = tmp_path / "t.db"
    engine = create_engine(f"sqlite:///{db}", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)()


@pytest.mark.asyncio
async def test_search_ingest_writes_discovered(tmp_path) -> None:
    session = _session(tmp_path)
    provider = MockBraveProvider()
    summary = await run_search_ingest(
        session, provider, "Chinese investment Indonesia", source_id="reuters"
    )
    assert summary["inserted"] >= 1
    rows = list(session.scalars(select(ReviewCandidate)))
    assert rows
    assert all(r.status == "discovered" for r in rows)
    assert all(r.provider == "brave_mock" for r in rows)
    assert all(r.url_hash for r in rows)
    assert all(r.source_id == "reuters" for r in rows)


@pytest.mark.asyncio
async def test_search_ingest_idempotent_skips_dup_url(tmp_path) -> None:
    session = _session(tmp_path)
    provider = MockBraveProvider()
    first = await run_search_ingest(session, provider, "q1")
    second = await run_search_ingest(session, provider, "q2")
    assert first["inserted"] >= 1
    assert second["inserted"] == 0
    assert second["skipped"] == first["inserted"]
    assert len(list(session.scalars(select(ReviewCandidate)))) == first["inserted"]


def test_url_hash_stable() -> None:
    assert url_hash("https://a.com/x/") == url_hash("https://a.com/x")
