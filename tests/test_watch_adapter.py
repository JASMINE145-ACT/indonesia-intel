"""Watch adapter — WANd.INTEL.WATCH_ADAPTER.001."""

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import ReviewCandidate, SourceWatchState
from jobs.adapters.watch import content_fingerprint, poll_watch_source
from jobs.poll_sources import discovery_targets
from sources.registry import SourceEntry, SourceRegistry


def _session(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'watch.db'}",
        future=True,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)()


def test_fingerprint_stable_and_selector_scoped() -> None:
    html = b"<html><body><main>hello</main><aside>noise</aside></body></html>"
    h1 = content_fingerprint(html, selector="main")
    h2 = content_fingerprint(html, selector="main")
    assert h1 == h2
    changed = content_fingerprint(
        b"<html><body><main>hello world</main><aside>noise</aside></body></html>",
        selector="main",
    )
    assert changed != h1


def test_watch_baseline_then_change_inserts(tmp_path) -> None:
    session = _session(tmp_path)
    src = SourceEntry(
        id="w1",
        name="WatchMe",
        domain="example.com",
        watch_url="https://www.example.com/page",
        watch_selector="main",
        enabled=True,
    )
    html_a = b"<html><body><main>v1</main></body></html>"
    html_b = b"<html><body><main>v2</main></body></html>"

    r0 = poll_watch_source(session, src, html_override=html_a, resolve_dns=False)
    assert r0["inserted"] == 0
    assert r0.get("baseline") is True
    assert session.scalar(select(SourceWatchState).where(SourceWatchState.source_id == "w1"))

    r1 = poll_watch_source(session, src, html_override=html_a, resolve_dns=False)
    assert r1["inserted"] == 0
    assert r1.get("changed") is False

    r2 = poll_watch_source(session, src, html_override=html_b, resolve_dns=False)
    assert r2["inserted"] == 1
    assert r2.get("changed") is True
    rows = list(session.scalars(select(ReviewCandidate)))
    assert len(rows) == 1
    assert rows[0].discovery_method == "watch"
    assert rows[0].original_url == "https://www.example.com/page"


def test_watch_state_survives_new_session(tmp_path) -> None:
    db = tmp_path / "watch_persist.db"
    engine = create_engine(
        f"sqlite:///{db}",
        future=True,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    src = SourceEntry(
        id="w2",
        name="Persist",
        domain="example.com",
        watch_url="https://www.example.com/p",
        watch_selector="main",
        enabled=True,
    )
    html_a = b"<html><body><main>v1</main></body></html>"
    html_b = b"<html><body><main>v2</main></body></html>"

    s1 = Session()
    try:
        r0 = poll_watch_source(s1, src, html_override=html_a, resolve_dns=False)
        assert r0.get("baseline") is True
    finally:
        s1.close()

    s2 = Session()
    try:
        r1 = poll_watch_source(s2, src, html_override=html_a, resolve_dns=False)
        assert r1["inserted"] == 0
        assert r1.get("changed") is False
        r2 = poll_watch_source(s2, src, html_override=html_b, resolve_dns=False)
        assert r2["inserted"] == 1
        assert len(list(s2.scalars(select(ReviewCandidate)))) == 1
    finally:
        s2.close()


def test_watch_flag_off_excludes_targets(monkeypatch) -> None:
    monkeypatch.setenv("INTEL_DISCOVERY_WATCH", "0")
    reg = SourceRegistry(
        [
            SourceEntry(
                id="wonly",
                name="W",
                domain="example.com",
                watch_url="https://www.example.com/x",
                enabled=True,
            )
        ]
    )
    assert discovery_targets(reg) == []


def test_watch_flag_on_includes_targets(monkeypatch) -> None:
    monkeypatch.setenv("INTEL_DISCOVERY_WATCH", "1")
    monkeypatch.setenv("INTEL_DISCOVERY_SITEMAP", "0")
    monkeypatch.setenv("INTEL_DISCOVERY_LISTING", "0")
    reg = SourceRegistry(
        [
            SourceEntry(
                id="wonly",
                name="W",
                domain="example.com",
                watch_url="https://www.example.com/x",
                enabled=True,
            )
        ]
    )
    assert {s.id for s in discovery_targets(reg)} == {"wonly"}
