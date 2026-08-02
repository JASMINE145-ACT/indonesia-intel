"""SOURCE_LANES guard — WANd.INTEL.SOURCE_LANES.001.

Reach/social integrations must not import L1 poll adapters, L2 search providers,
or confirm paths (AC-01 / AC-07).
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REACH_ROOT = ROOT / "integrations" / "agent_reach"

FORBIDDEN_MODULES = {
    "feedparser",
    "jobs.adapters.sitemap",
    "jobs.adapters.listing",
    "jobs.adapters.watch",
    "jobs.poll_sources",
    "jobs.poll_rss",
    "providers.exa",
    "providers.tavily",
    "providers.factory",
}
FORBIDDEN_NAME_FRAGMENTS = (
    "intel_confirm",
    "confirm_candidate",
    "review_actions",
)


def _iter_py_files(base: Path) -> list[Path]:
    if not base.is_dir():
        return []
    return [p for p in base.rglob("*.py") if p.is_file()]


def _imports_of(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                found.add(node.module)
    return found


def test_reach_tree_absent_or_lane_clean() -> None:
    files = _iter_py_files(REACH_ROOT)
    if not files:
        assert not REACH_ROOT.exists() or REACH_ROOT.is_dir()
        return
    for path in files:
        mods = _imports_of(path)
        text = path.read_text(encoding="utf-8")
        for bad in FORBIDDEN_MODULES:
            assert bad not in mods and not any(
                m == bad or m.startswith(bad + ".") for m in mods
            ), f"{path} imports forbidden module {bad}"
        for frag in FORBIDDEN_NAME_FRAGMENTS:
            assert frag not in text, f"{path} references forbidden symbol {frag}"


def test_poll_sources_does_not_import_agent_reach() -> None:
    poll = (ROOT / "jobs" / "poll_sources.py").read_text(encoding="utf-8")
    assert "agent_reach" not in poll
    assert "integrations.agent_reach" not in poll


def test_discovery_coverage_doc_exists() -> None:
    doc = ROOT / "evidence" / "discovery-coverage-20260801.md"
    assert doc.is_file()
    text = doc.read_text(encoding="utf-8")
    assert "Kompas" in text or "kompas" in text
    assert "detik" in text.lower()
    assert "SOURCE_LANES" in text or "lane" in text.lower()
    assert "INTEL_DISCOVERY_WATCH" in text
    assert "INTEL_REACH_ENABLED" in text
    assert "INTEL_FETCH_JINA_FALLBACK" in text


def test_flags_default_off_in_settings() -> None:
    from app.config import Settings

    assert Settings.model_fields["discovery_watch_enabled"].default is False
    assert Settings.model_fields["reach_enabled"].default is False
    assert Settings.model_fields["fetch_jina_fallback_enabled"].default is False
