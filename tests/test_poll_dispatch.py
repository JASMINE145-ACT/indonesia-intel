"""Poll dispatch — WANd.INTEL.POLL_DISPATCH.001."""

from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from jobs.poll_sources import discovery_targets, poll_prefer_sources, source_has_listing_config
from sources.registry import SourceEntry, SourceRegistry

FIXTURE_SM = Path(__file__).parent / "fixtures" / "discovery" / "sitemap_sample.xml"


def _session(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'pd.db'}",
        future=True,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)()


def test_discovery_targets_rss_only_without_config() -> None:
    reg = SourceRegistry(
        [
            SourceEntry(
                id="r1",
                name="R",
                domain="example.com",
                fetch_mode="rss",
                rss_url="https://example.com/feed.xml",
                enabled=True,
            ),
            SourceEntry(
                id="bare_list",
                name="Bare",
                domain="example.com",
                fetch_mode="list",
                home_url="https://example.com/",
                enabled=True,
            ),
        ]
    )
    ids = {s.id for s in discovery_targets(reg)}
    assert ids == {"r1"}


def test_discovery_enabled_false_drops_rss() -> None:
    reg = SourceRegistry(
        [
            SourceEntry(
                id="r1",
                name="R",
                domain="example.com",
                fetch_mode="rss",
                rss_url="https://example.com/feed.xml",
                discovery_enabled=False,
                enabled=True,
            ),
        ]
    )
    assert discovery_targets(reg) == []


def test_switches_off_equiv_rss_ready(monkeypatch) -> None:
    monkeypatch.setenv("INTEL_DISCOVERY_SITEMAP", "0")
    monkeypatch.setenv("INTEL_DISCOVERY_LISTING", "0")
    reg = SourceRegistry(
        [
            SourceEntry(
                id="r1",
                name="R",
                domain="example.com",
                fetch_mode="rss",
                rss_url="https://example.com/feed.xml",
                enabled=True,
            ),
            SourceEntry(
                id="sm1",
                name="S",
                domain="example.com",
                fetch_mode="sitemap",
                sitemap_url="https://example.com/sitemap.xml",
                enabled=True,
            ),
            SourceEntry(
                id="li1",
                name="L",
                domain="example.com",
                fetch_mode="list",
                list_url="https://example.com/",
                item_selector="article",
                enabled=True,
            ),
        ]
    )
    ids = {s.id for s in discovery_targets(reg)}
    assert ids == {"r1"}


def test_poll_prefer_isolates_source_error(tmp_path, monkeypatch) -> None:
    session = _session(tmp_path)
    rss_xml = b"""<?xml version="1.0"?><rss version="2.0"><channel>
<item><title>T</title><link>https://example.com/rss/1</link></item>
</channel></rss>"""

    def fake_load():
        return SourceRegistry(
            [
                SourceEntry(
                    id="ok_rss",
                    name="OK",
                    domain="example.com",
                    fetch_mode="rss",
                    rss_url="https://example.com/feed.xml",
                    enabled=True,
                ),
                SourceEntry(
                    id="bad_sm",
                    name="Bad",
                    domain="example.com",
                    fetch_mode="sitemap",
                    sitemap_url="https://www.example.com/sitemap.xml",
                    enabled=True,
                ),
            ]
        )

    monkeypatch.setattr("jobs.poll_sources.load_merged", fake_load)

    def boom(*_a, **_k):
        raise RuntimeError("403 forbidden")

    monkeypatch.setattr("jobs.adapters.sitemap.fetch_bytes", boom)
    out = poll_prefer_sources(
        session,
        source_ids=["ok_rss", "bad_sm"],
        xml_overrides={"ok_rss": rss_xml},
        resolve_gnews=False,
    )
    assert out["sources"] == 2
    by = {r["source_id"]: r for r in out["results"]}
    assert by["ok_rss"]["inserted"] == 1
    assert by["bad_sm"].get("inserted", 0) == 0
    assert "error" in by["bad_sm"]


def test_listing_config_helper() -> None:
    assert source_has_listing_config(
        SourceEntry(
            id="x",
            name="x",
            domain="d.com",
            list_url="https://d.com/",
            item_selector="a",
        )
    )
    assert not source_has_listing_config(
        SourceEntry(id="y", name="y", domain="d.com", home_url="https://d.com/")
    )
