"""Sitemap adapter — WANd.INTEL.SITEMAP_ADAPTER.001."""

from pathlib import Path

import httpx
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import ReviewCandidate
from jobs.adapters.sitemap import collect_sitemap_urls, parse_sitemap_xml, poll_sitemap_source
from sources.registry import SourceEntry

FIXTURE = Path(__file__).parent / "fixtures" / "discovery" / "sitemap_sample.xml"


def _session(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'sm.db'}",
        future=True,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)()


def test_parse_sitemap_filters_patterns() -> None:
    pages, children = parse_sitemap_xml(FIXTURE.read_bytes())
    assert any("/read/" in p for p in pages)
    assert not children


def test_collect_sitemap_urls_same_domain_and_patterns() -> None:
    urls = collect_sitemap_urls(
        "https://www.example.com/sitemap.xml",
        domain="example.com",
        include_patterns=["/read/", "/news/"],
        exclude_patterns=["/tag/"],
        xml_override=FIXTURE.read_bytes(),
        resolve_dns=False,
    )
    assert "https://www.example.com/read/china-ev-1" in urls
    assert "https://www.example.com/news/invest-2" in urls
    assert not any("/tag/" in u for u in urls)
    assert not any("other.com" in u for u in urls)
    assert not any("127.0.0.1" in u for u in urls)


def test_poll_sitemap_inserts_discovered(tmp_path) -> None:
    session = _session(tmp_path)
    src = SourceEntry(
        id="ex_sm",
        name="Ex",
        domain="example.com",
        fetch_mode="sitemap",
        sitemap_url="https://www.example.com/sitemap.xml",
        include_patterns="/read/|/news/",
        exclude_patterns="/tag/",
        enabled=True,
    )
    summary = poll_sitemap_source(
        session, src, xml_override=FIXTURE.read_bytes(), resolve_dns=False
    )
    assert summary["inserted"] >= 1
    rows = list(session.scalars(select(ReviewCandidate)))
    assert rows
    assert rows[0].discovery_method == "sitemap"
    assert rows[0].resolution_status == "not_required"
    assert rows[0].status == "discovered"


def test_sitemap_start_url_ssrf_rejected(tmp_path) -> None:
    session = _session(tmp_path)
    src = SourceEntry(
        id="ssrf",
        name="S",
        domain="127.0.0.1",
        fetch_mode="sitemap",
        sitemap_url="http://127.0.0.1/sitemap.xml",
        enabled=True,
    )
    out = poll_sitemap_source(session, src, resolve_dns=False)
    assert out.get("inserted", 0) == 0
    assert "error" in out or out.get("skipped")


def test_sitemap_http_error_does_not_raise(tmp_path, monkeypatch) -> None:
    session = _session(tmp_path)
    src = SourceEntry(
        id="bad",
        name="Bad",
        domain="example.com",
        fetch_mode="sitemap",
        sitemap_url="https://www.example.com/sitemap.xml",
        enabled=True,
    )

    def boom(*_a, **_k):
        raise httpx.HTTPStatusError(
            "403",
            request=httpx.Request("GET", "https://www.example.com/sitemap.xml"),
            response=httpx.Response(403),
        )

    monkeypatch.setattr("jobs.adapters.sitemap.fetch_bytes", boom)
    out = poll_sitemap_source(session, src, resolve_dns=False)
    assert out.get("inserted") == 0
    assert "error" in out or out.get("hits") == 0
