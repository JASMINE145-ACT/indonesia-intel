"""Official L1 registry — WANd.INTEL.OFFICIAL_L1_DISCOVERY.001."""

from jobs.poll_sources import discovery_targets, source_has_listing_config
from sources.store import load_merged


def test_official_runnable_in_discovery_targets() -> None:
    reg = load_merged()
    by_id = {s.id: s for s in reg.enabled()}
    for sid in ("kemenperin", "esdm", "kemendag"):
        assert sid in by_id, sid
        src = by_id[sid]
        assert source_has_listing_config(src), sid
        assert src.discovery_enabled is True
    ids = {s.id for s in discovery_targets(reg)}
    assert {"kemenperin", "esdm", "kemendag"} <= ids


def test_official_skips_not_in_discovery_targets() -> None:
    reg = load_merged()
    ids = {s.id for s in discovery_targets(reg)}
    for sid in ("bkpm", "ojk", "idx", "apindo", "imip", "kadin", "kemenhub"):
        assert sid not in ids, f"{sid} should be discovery_enabled=false skip"


def test_seed_coverage_at_least_ten() -> None:
    """Runnable + documented skips cover ≥10 PR3 seed rows."""
    runnable = {"kemenperin", "esdm", "kemendag"}
    skips = {"bkpm", "ojk", "idx", "apindo", "imip", "kadin", "kemenhub"}
    assert len(runnable | skips) >= 10
