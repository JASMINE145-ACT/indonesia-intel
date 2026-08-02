from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


class SourceEntry(BaseModel):
    id: str
    name: str
    domain: str
    country: str = ""
    region: str = ""  # CN | ID | INT
    language: str = ""
    level: str = "other"
    priority: str = "B"  # A = MVP must-cover, B = next
    fetch_mode: str = "list"  # rss | list | search | sitemap | guide
    home_url: str = ""
    rss_url: str = ""
    enabled: bool = True
    notes: str = ""
    # L2 Scrapling escalation (WANd.INTEL.FETCH_L2_SCRAPLING.001)
    fetch_l2: bool = False
    fetch_l2_mode: str = "http"  # http | dynamic | stealthy
    # Discovery adapters (WANd.INTEL.SITEMAP/LISTING) — selectors only in registry.yaml
    sitemap_url: str = ""
    list_url: str = ""
    item_selector: str = ""
    url_selector: str = "a"
    title_selector: str = ""
    include_patterns: str = ""  # pipe-separated path substrings
    exclude_patterns: str = ""
    # Per-source discovery opt-out — WANd.INTEL.BISNIS_DISCOVERY.001 / SOURCE_LANES
    # discovery_targets ignores fetch_mode; use this (or clear selectors) to leave L1.
    discovery_enabled: bool = True
    # Watch adapter — WANd.INTEL.WATCH_ADAPTER.001 (opt-in via INTEL_DISCOVERY_WATCH)
    watch_url: str = ""
    watch_selector: str = ""  # optional CSS scope; empty = whole body text hash

    @property
    def is_prefer_a(self) -> bool:
        return self.priority.upper() == "A" and self.enabled


class SourceRegistry:
    """Fixed-source registry — WANd.INTEL.SOURCE_REGISTRY.001"""

    def __init__(self, sources: list[SourceEntry]) -> None:
        if not sources:
            raise ValueError("SourceRegistry requires at least one source")
        self._by_id = {s.id: s for s in sources}
        if len(self._by_id) != len(sources):
            raise ValueError("duplicate source id in registry")

    @classmethod
    def load(cls, path: Path | str) -> SourceRegistry:
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        if not isinstance(data, dict) or "sources" not in data:
            raise ValueError("registry YAML must contain top-level 'sources' list")
        raw: list[Any] = data["sources"] or []
        if not raw:
            raise ValueError("sources list is empty")
        return cls([SourceEntry.model_validate(item) for item in raw])

    def all(self) -> list[SourceEntry]:
        return list(self._by_id.values())

    def enabled(self) -> list[SourceEntry]:
        return [s for s in self.all() if s.enabled]

    def prefer_a(self) -> list[SourceEntry]:
        return [s for s in self.enabled() if s.priority.upper() == "A"]

    def by_region(self, region: str) -> list[SourceEntry]:
        key = region.upper()
        return [s for s in self.enabled() if s.region.upper() == key]

    def rss_ready(self) -> list[SourceEntry]:
        return [
            s
            for s in self.enabled()
            if s.fetch_mode == "rss" and bool(s.rss_url.strip())
        ]

    def discovery_configured(self) -> list[SourceEntry]:
        """Sources with sitemap_url or listing selectors (not bare list mode)."""
        out: list[SourceEntry] = []
        for s in self.enabled():
            has_sm = bool((s.sitemap_url or "").strip()) or (
                s.fetch_mode == "sitemap" and bool((s.home_url or "").strip())
            )
            has_list = bool((s.list_url or s.home_url or "").strip()) and bool(
                (s.item_selector or "").strip()
            )
            if has_sm or has_list:
                out.append(s)
        return out

    def get(self, source_id: str) -> SourceEntry | None:
        return self._by_id.get(source_id)

    def assert_fetch_allowed(self, source_id: str) -> SourceEntry:
        src = self.get(source_id)
        if src is None:
            raise KeyError(f"unknown source: {source_id}")
        if not src.enabled:
            raise PermissionError(f"source disabled: {source_id}")
        return src
