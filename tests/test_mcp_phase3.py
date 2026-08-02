from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import FormalEvent, ReviewCandidate, ReviewDecision
from mcp_server import service
from mcp_server.server import mcp
from sources.store import sources_list


def _wire(tmp_path, monkeypatch):
    from app import db as dbmod

    engine = create_engine(
        f"sqlite:///{tmp_path / 'r.db'}",
        future=True,
        connect_args={"check_same_thread": False},
    )
    dbmod.engine = engine
    dbmod.SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    Base.metadata.create_all(engine)
    return dbmod.SessionLocal


def test_phase3_tools_registered() -> None:
    names = set(mcp._tool_manager._tools.keys())  # noqa: SLF001
    assert {"intel_confirm", "intel_ignore", "intel_learn_source"} <= names


def test_server_carries_playbook_instructions() -> None:
    assert mcp.instructions
    assert "taxonomy" in mcp.instructions.lower() or "受控" in mcp.instructions


def test_workflow_prompts_registered() -> None:
    names = set(mcp._prompt_manager._prompts.keys())  # noqa: SLF001
    assert {
        "review_pending_candidates",
        "analyze_topic",
        "generate_content_with_factcheck",
    } <= names


def test_phase_entities_tools_registered() -> None:
    names = set(mcp._tool_manager._tools.keys())  # noqa: SLF001
    assert {
        "intel_taxonomy_list",
        "intel_dedup_check",
        "intel_company_upsert",
        "intel_company_list",
        "intel_project_upsert",
        "intel_project_list",
        "intel_stats",
        "intel_factcheck_event",
        "intel_event_add_source",
        "intel_event_sources",
        "intel_export_events_csv",
        "intel_manual_add",
        "intel_manual_add_pdf",
        "intel_watch",
        "intel_merge",
    } <= names


def test_intel_manual_add_then_confirm_inherits_visibility(tmp_path, monkeypatch) -> None:
    _wire(tmp_path, monkeypatch)

    added = service.intel_manual_add(
        "闭门交流纪要",
        text="非公开计划细节。",
        source_attribution="商务交流",
        is_public_source=False,
    )
    assert added["status"] == "pending_review"
    assert added["canonical_url"].startswith("manual://")

    out = service.intel_confirm(added["id"])
    assert out["status"] == "confirmed"

    from app import db as dbmod

    with dbmod.SessionLocal() as session:
        event = session.get(FormalEvent, out["formal_event_id"])
        assert event.is_public is False


def test_intel_manual_add_rejects_bad_source_attribution(tmp_path, monkeypatch) -> None:
    _wire(tmp_path, monkeypatch)
    with pytest.raises(ValueError):
        service.intel_manual_add("标题", url="https://example.com/x", source_attribution="乱写")


def test_intel_confirm_with_structured_fields(tmp_path, monkeypatch) -> None:
    SessionLocal = _wire(tmp_path, monkeypatch)
    with SessionLocal() as session:
        session.add(
            ReviewCandidate(
                run_id="r1",
                provider="mock",
                query="q",
                original_url="https://example.com/e",
                canonical_url="https://example.com/e",
                url_hash="eh1",
                title="比亚迪印尼工厂开工建设",
                snippet="",
                status="pending_review",
                object_key="blob-mcp",
                extracted_text="fixture body for confirm gate",
                fetch_status="ok",
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
        )
        session.commit()
        cid = session.scalar(
            select(ReviewCandidate).where(ReviewCandidate.url_hash == "eh1")
        ).id

    out = service.intel_confirm(
        cid,
        company_name="比亚迪",
        industry="汽车、工程机械与交通装备",
        event_type="开工建设",
        project_stage="开工",
    )
    assert out["status"] == "confirmed"
    assert out["company_id"] is not None

    taxonomy = service.intel_taxonomy_list()
    assert "汽车、工程机械与交通装备" in taxonomy["industries"]

    stats = service.intel_stats()
    assert stats["industry_distribution"][0]["count"] == 1

    companies = service.intel_company_list()
    assert companies["count"] == 1

    dup = service.intel_dedup_check(cid)
    assert dup["candidate_id"] == cid

    formal_event_id = out["formal_event_id"]
    added = service.intel_event_add_source(
        formal_event_id, "https://media.example.cn/repost", label="中国媒体转载"
    )
    assert added["ok"] is True
    sources = service.intel_event_sources(formal_event_id)
    assert sources["count"] == 2  # confirm_source + the one just added

    export = service.intel_export_events_csv()
    assert export["format"] == "csv"
    assert "比亚迪印尼工厂开工建设" in export["content"]


def test_intel_confirm_rejects_bad_taxonomy(tmp_path, monkeypatch) -> None:
    SessionLocal = _wire(tmp_path, monkeypatch)
    with SessionLocal() as session:
        session.add(
            ReviewCandidate(
                run_id="r1",
                provider="mock",
                query="q",
                original_url="https://example.com/f",
                canonical_url="https://example.com/f",
                url_hash="fh1",
                title="F",
                snippet="",
                status="pending_review",
                object_key="blob-f",
                extracted_text="fixture body",
                fetch_status="ok",
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
        )
        session.commit()
        cid = session.scalar(
            select(ReviewCandidate).where(ReviewCandidate.url_hash == "fh1")
        ).id

    with pytest.raises(ValueError):
        service.intel_confirm(cid, industry="乱写行业")


def test_intel_confirm_and_ignore(tmp_path, monkeypatch) -> None:
    SessionLocal = _wire(tmp_path, monkeypatch)
    with SessionLocal() as session:
        session.add(
            ReviewCandidate(
                run_id="r1",
                provider="mock",
                query="q",
                original_url="https://example.com/c",
                canonical_url="https://example.com/c",
                url_hash="ch1",
                title="C",
                snippet="",
                status="pending_review",
                object_key="blob-c",
                extracted_text="fixture body",
                fetch_status="ok",
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
        )
        session.add(
            ReviewCandidate(
                run_id="r1",
                provider="mock",
                query="q",
                original_url="https://example.com/i",
                canonical_url="https://example.com/i",
                url_hash="ih1",
                title="I",
                snippet="",
                status="pending_review",
                object_key="blob-i",
                extracted_text="fixture body",
                fetch_status="ok",
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
        )
        session.commit()
        cid = session.scalar(
            select(ReviewCandidate).where(ReviewCandidate.url_hash == "ch1")
        ).id
        iid = session.scalar(
            select(ReviewCandidate).where(ReviewCandidate.url_hash == "ih1")
        ).id

    assert service.intel_confirm(cid)["status"] == "confirmed"
    assert service.intel_ignore(iid)["status"] == "ignored"
    with SessionLocal() as session:
        assert session.scalar(select(FormalEvent)) is not None
        assert session.scalars(select(ReviewDecision)).all()


def test_intel_learn_source(tmp_path) -> None:
    learned = tmp_path / "learned.yaml"
    registry = Path(__file__).resolve().parents[1] / "sources" / "registry.yaml"
    # patch DEFAULT via args inside sources_add through learn → monkeypatch store paths
    from sources import store as storemod

    old_l = storemod.DEFAULT_LEARNED
    old_r = storemod.DEFAULT_REGISTRY
    storemod.DEFAULT_LEARNED = learned
    storemod.DEFAULT_REGISTRY = registry
    try:
        out = service.intel_learn_source("https://new-prefer.example/path", name="New Prefer", region="INT")
        assert out["ok"] is True
        assert out["source"]["domain"] == "new-prefer.example"
        listed = sources_list(registry_path=registry, learned_path=learned)
        assert any(s["domain"] == "new-prefer.example" for s in listed)
    finally:
        storemod.DEFAULT_LEARNED = old_l
        storemod.DEFAULT_REGISTRY = old_r
