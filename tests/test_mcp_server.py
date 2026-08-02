from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import ReviewCandidate
from mcp_server import service
from mcp_server.server import mcp
from sources.store import load_merged, sources_add, sources_list, sources_set_enabled


def test_mcp_tools_registered() -> None:
    tools = getattr(mcp, "_tool_manager", None)
    assert tools is not None
    names = set(tools._tools.keys())  # noqa: SLF001
    for required in (
        "intel_providers",
        "intel_sources_list",
        "intel_sources_add",
        "intel_sources_set_enabled",
        "intel_list",
    ):
        assert required in names


def test_mcp_tool_schemas_have_no_secret_params() -> None:
    manager = mcp._tool_manager  # noqa: SLF001
    for name, tool in manager._tools.items():  # noqa: SLF001
        params = set((tool.parameters or {}).get("properties", {}).keys())
        bad = params & service.FORBIDDEN_TOOL_PARAM_NAMES
        assert not bad, f"{name} exposes secret params: {bad}"


def test_sources_list_includes_prefer_a(tmp_path) -> None:
    # uses default registry (deep-research seed)
    data = service.intel_sources_list(priority="A", enabled_only=True)
    assert data["count"] >= 20
    ids = {i["id"] for i in data["items"]}
    assert "bkpm" in ids
    assert "cninfo" in ids
    assert "reuters" in ids


def test_sources_add_and_enable_roundtrip(tmp_path) -> None:
    learned = tmp_path / "learned.yaml"
    registry = Path(__file__).resolve().parents[1] / "sources" / "registry.yaml"
    entry = sources_add(
        domain="example-prefer.test",
        name="Example Prefer",
        region="INT",
        learned_path=learned,
        registry_path=registry,
    )
    assert entry["id"] == "example_prefer_test"
    listed = sources_list(registry_path=registry, learned_path=learned)
    assert any(s["id"] == "example_prefer_test" for s in listed)
    disabled = sources_set_enabled(
        "example_prefer_test", False, registry_path=registry, learned_path=learned
    )
    assert disabled["enabled"] is False
    merged = load_merged(registry, learned)
    assert merged.get("example_prefer_test").enabled is False


def test_sources_add_rss_requires_url(tmp_path) -> None:
    learned = tmp_path / "learned.yaml"
    registry = Path(__file__).resolve().parents[1] / "sources" / "registry.yaml"
    with pytest.raises(ValueError, match="rss_url"):
        sources_add(
            domain="rss-only.test",
            fetch_mode="rss",
            learned_path=learned,
            registry_path=registry,
        )


def test_intel_list_pending(tmp_path, monkeypatch) -> None:
    from app import db as dbmod

    engine = create_engine(
        f"sqlite:///{tmp_path / 'm.db'}",
        future=True,
        connect_args={"check_same_thread": False},
    )
    dbmod.engine = engine
    dbmod.SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    Base.metadata.create_all(engine)
    with dbmod.SessionLocal() as session:
        session.add(
            ReviewCandidate(
                run_id="m1",
                provider="mock",
                query="q",
                original_url="https://example.com/a",
                canonical_url="https://example.com/a",
                url_hash="h1",
                title="T",
                snippet="s",
                status="pending_review",
            )
        )
        session.commit()

    out = service.intel_list(status="pending_review")
    assert out["count"] == 1
    assert out["items"][0]["title"] == "T"


def test_intel_providers_shape() -> None:
    body = service.intel_providers()
    assert "available" in body
    assert "cascade" in body
    assert "L1" in body["cascade"]
