"""Listing adapter — WANd.INTEL.LISTING_ADAPTER.001."""

from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import ReviewCandidate
from jobs.adapters.listing import extract_listing_urls, poll_listing_source
from sources.registry import SourceEntry

FIXTURE = Path(__file__).parent / "fixtures" / "discovery" / "listing_sample.html"


def _session(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'ls.db'}",
        future=True,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)()


def test_extract_listing_same_domain_only() -> None:
    hits = extract_listing_urls(
        FIXTURE.read_bytes(),
        list_url="https://www.example.com/",
        item_selector="article.item",
        url_selector="a",
        domain="example.com",
    )
    urls = [h["url"] for h in hits]
    assert "https://www.example.com/berita/a1" in urls
    assert "https://www.example.com/berita/a2" in urls
    assert not any("evil.example.net" in u for u in urls)
    assert len(urls) == 2  # dup collapsed


def test_poll_listing_inserts(tmp_path) -> None:
    session = _session(tmp_path)
    src = SourceEntry(
        id="ex_list",
        name="Ex",
        domain="example.com",
        fetch_mode="list",
        list_url="https://www.example.com/",
        item_selector="article.item",
        url_selector="a",
        enabled=True,
    )
    summary = poll_listing_source(
        session, src, html_override=FIXTURE.read_bytes(), resolve_dns=False
    )
    assert summary["inserted"] == 2
    rows = list(session.scalars(select(ReviewCandidate)))
    assert all(r.discovery_method == "listing" for r in rows)


def test_bad_selector_skips(tmp_path) -> None:
    session = _session(tmp_path)
    src = SourceEntry(
        id="bad_sel",
        name="Bad",
        domain="example.com",
        list_url="https://www.example.com/",
        item_selector="@@@not a selector!!!",
        url_selector="a",
        enabled=True,
    )
    summary = poll_listing_source(
        session, src, html_override=FIXTURE.read_bytes(), resolve_dns=False
    )
    assert summary["inserted"] == 0


def test_registry_kompas_detik_bisnis_not_gnews_only() -> None:
    from sources.store import load_merged

    reg = load_merged()
    komp = reg.get("kompas")
    det = reg.get("detik")
    bis = reg.get("bisnis")
    assert komp is not None
    assert det is not None
    assert bis is not None
    assert (komp.sitemap_url or komp.item_selector)
    assert det.item_selector
    assert "li" not in {p.strip() for p in (det.item_selector or "").split(",")}
    assert "/berita/d-" in (det.include_patterns or "")
    assert komp.fetch_mode != "search" or komp.sitemap_url
    assert bis.item_selector and "/read/" in (bis.include_patterns or "")
    assert bis.discovery_enabled is True


def test_broad_li_selector_without_filter_picks_nav() -> None:
    """Documents the Detik failure mode: `li` in item_selector steals early slots."""
    hits = extract_listing_urls(
        FIXTURE.read_bytes(),
        list_url="https://www.example.com/berita",
        item_selector="article, li",
        url_selector="a",
        domain="example.com",
    )
    urls = [h["url"] for h in hits]
    assert any("tagfrom=framebar" in u or "/terpopuler" in u for u in urls[:3])


def test_path_include_filters_nav_and_keeps_articles() -> None:
    hits = extract_listing_urls(
        FIXTURE.read_bytes(),
        list_url="https://www.example.com/berita",
        item_selector="article.list-content__item, article.item, li",
        url_selector="h3.media__title a, a",
        domain="example.com",
        include_patterns=["/berita/"],
        exclude_patterns=["/terpopuler", "/live"],
    )
    urls = [h["url"] for h in hits]
    assert "https://www.example.com/berita/a1" in urls
    assert "https://www.example.com/berita/d-100/title" in urls
    assert not any("terpopuler" in u or "/live" in u or "tagfrom=" in u for u in urls)
