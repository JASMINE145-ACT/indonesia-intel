"""Bisnis L1 + discovery_enabled — WANd.INTEL.BISNIS_DISCOVERY.001."""

from pathlib import Path

from jobs.poll_sources import discovery_targets, poll_prefer_sources, source_has_listing_config
from sources.registry import SourceEntry, SourceRegistry
from sources.store import load_merged
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base


def _session(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'bis.db'}",
        future=True,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)()


def test_registry_bisnis_has_listing_not_search_only() -> None:
    reg = load_merged()
    b = reg.get("bisnis")
    assert b is not None
    assert source_has_listing_config(b)
    assert b.discovery_enabled is True
    assert b.fetch_mode != "search" or source_has_listing_config(b)
    assert "/read/" in (b.include_patterns or "")


def test_discovery_enabled_false_excludes_from_targets() -> None:
    reg = SourceRegistry(
        [
            SourceEntry(
                id="off",
                name="Off",
                domain="example.com",
                fetch_mode="list",
                list_url="https://www.example.com/",
                item_selector="article",
                discovery_enabled=False,
                enabled=True,
            ),
            SourceEntry(
                id="on",
                name="On",
                domain="example.com",
                fetch_mode="list",
                list_url="https://www.example.com/",
                item_selector="article",
                discovery_enabled=True,
                enabled=True,
            ),
        ]
    )
    assert {s.id for s in discovery_targets(reg)} == {"on"}


def test_discovery_enabled_false_skips_explicit_poll(tmp_path, monkeypatch) -> None:
    session = _session(tmp_path)
    html = b'<html><body><a href="/read/1">T</a></body></html>'

    def fake_load():
        return SourceRegistry(
            [
                SourceEntry(
                    id="bisnis",
                    name="Bisnis",
                    domain="bisnis.com",
                    fetch_mode="list",
                    list_url="https://www.bisnis.com/",
                    item_selector="a[href*='/read/']",
                    include_patterns="/read/",
                    discovery_enabled=False,
                    enabled=True,
                )
            ]
        )

    monkeypatch.setattr("jobs.poll_sources.load_merged", fake_load)
    out = poll_prefer_sources(
        session,
        source_ids=["bisnis"],
        html_overrides={"bisnis": html},
        resolve_gnews=False,
    )
    row = out["results"][0]
    assert row.get("skipped") is True
    assert row.get("reason") == "discovery_enabled=false"
    assert row.get("inserted", 0) == 0


def test_clear_selectors_removes_bisnis_from_targets() -> None:
    """Rollback path B: clear listing fields (not fetch_mode alone)."""
    configured = SourceEntry(
        id="bisnis",
        name="Bisnis",
        domain="bisnis.com",
        fetch_mode="list",
        list_url="https://www.bisnis.com/",
        item_selector="a[href*='/read/']",
        enabled=True,
    )
    cleared = SourceEntry(
        id="bisnis",
        name="Bisnis",
        domain="bisnis.com",
        fetch_mode="list",  # fetch_mode alone must not keep it in L1
        list_url="",
        item_selector="",
        home_url="https://www.bisnis.com/",
        enabled=True,
    )
    assert source_has_listing_config(configured)
    assert not source_has_listing_config(cleared)
    assert discovery_targets(SourceRegistry([cleared])) == []


def test_probe_evidence_exists() -> None:
    probe = Path(__file__).resolve().parents[1] / "evidence" / "bisnis-probe-20260801.json"
    assert probe.is_file()
