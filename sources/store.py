from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml

from fetch.ssrf import assert_safe_url
from sources.registry import SourceEntry, SourceRegistry

ROOT = Path(__file__).resolve().parent
DEFAULT_REGISTRY = ROOT / "registry.yaml"
DEFAULT_LEARNED = ROOT / "learned.yaml"

# Learned must not wipe registry discovery selectors (D8).
_SELECTOR_FIELDS = (
    "sitemap_url",
    "list_url",
    "item_selector",
    "url_selector",
    "title_selector",
    "include_patterns",
    "exclude_patterns",
)


def _slug_from_domain(domain: str) -> str:
    d = domain.lower().strip().removeprefix("www.")
    slug = "".join(ch if ch.isalnum() else "_" for ch in d)
    return slug.strip("_")[:48] or "source"


def load_learned_entries(path: Path | str | None = None) -> list[SourceEntry]:
    p = Path(path or DEFAULT_LEARNED)
    if not p.is_file():
        return []
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        return []
    raw = data.get("sources") or []
    return [SourceEntry.model_validate(item) for item in raw]


def save_learned_entries(
    entries: list[SourceEntry], path: Path | str | None = None
) -> None:
    p = Path(path or DEFAULT_LEARNED)
    payload = {"sources": [e.model_dump() for e in entries]}
    p.write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def _merge_source_entry(base: SourceEntry, overlay: SourceEntry) -> SourceEntry:
    """Field-level merge: overlay wins on scalars; registry keeps discovery selectors (D8)."""
    data = base.model_dump()
    over = overlay.model_dump()
    for key, val in over.items():
        if key in _SELECTOR_FIELDS:
            continue
        data[key] = val
    return SourceEntry.model_validate(data)


def load_merged(
    registry_path: Path | str | None = None,
    learned_path: Path | str | None = None,
) -> SourceRegistry:
    """Core registry.yaml + learned.yaml (learned field-merges same id)."""
    base = SourceRegistry.load(registry_path or DEFAULT_REGISTRY)
    learned = load_learned_entries(learned_path)
    by_id = {s.id: s for s in base.all()}
    for item in learned:
        if item.id in by_id:
            by_id[item.id] = _merge_source_entry(by_id[item.id], item)
        else:
            by_id[item.id] = item
    return SourceRegistry(list(by_id.values()))


def sources_list(
    *,
    priority: str | None = None,
    region: str | None = None,
    enabled_only: bool = False,
    registry_path: Path | str | None = None,
    learned_path: Path | str | None = None,
) -> list[dict[str, Any]]:
    reg = load_merged(registry_path, learned_path)
    rows = reg.enabled() if enabled_only else reg.all()
    if priority:
        rows = [s for s in rows if s.priority.upper() == priority.upper()]
    if region:
        rows = [s for s in rows if s.region.upper() == region.upper()]
    return [s.model_dump() for s in rows]


def sources_add(
    *,
    domain: str,
    name: str = "",
    source_id: str = "",
    region: str = "",
    country: str = "",
    language: str = "",
    fetch_mode: str = "list",
    home_url: str = "",
    rss_url: str = "",
    priority: str = "B",
    notes: str = "added via MCP",
    enabled: bool = True,
    registry_path: Path | str | None = None,
    learned_path: Path | str | None = None,
) -> dict[str, Any]:
    registry_path = registry_path or DEFAULT_REGISTRY
    learned_path = learned_path or DEFAULT_LEARNED
    domain = domain.strip().lower().removeprefix("www.")
    if not domain or "." not in domain:
        raise ValueError("domain must look like example.com")
    if home_url:
        parsed = urlparse(home_url)
        if parsed.scheme and parsed.scheme not in {"http", "https"}:
            raise ValueError("home_url must be http(s)")
        assert_safe_url(home_url, resolve_dns=False)
    if rss_url:
        parsed = urlparse(rss_url)
        if parsed.scheme not in {"http", "https"}:
            raise ValueError("rss_url must be http(s)")
        assert_safe_url(rss_url, resolve_dns=False)
    if fetch_mode == "rss" and not rss_url:
        raise ValueError("fetch_mode=rss requires rss_url")

    sid = (source_id or _slug_from_domain(domain)).strip()
    reg = load_merged(registry_path, learned_path)
    if reg.get(sid) is not None:
        raise ValueError(f"source id already exists: {sid}")

    entry = SourceEntry(
        id=sid,
        name=name or domain,
        domain=domain,
        region=region,
        country=country,
        language=language,
        fetch_mode=fetch_mode,
        home_url=home_url,
        rss_url=rss_url,
        priority=priority or "B",
        notes=notes,
        enabled=enabled,
        level="learned",
    )
    learned = load_learned_entries(learned_path)
    learned.append(entry)
    save_learned_entries(learned, learned_path)
    return entry.model_dump()


def sources_set_enabled(
    source_id: str,
    enabled: bool,
    *,
    registry_path: Path | str | None = None,
    learned_path: Path | str | None = None,
) -> dict[str, Any]:
    registry_path = registry_path or DEFAULT_REGISTRY
    learned_path = learned_path or DEFAULT_LEARNED
    reg = load_merged(registry_path, learned_path)
    src = reg.get(source_id)
    if src is None:
        raise KeyError(f"unknown source: {source_id}")

    updated = src.model_copy(update={"enabled": enabled})
    learned = load_learned_entries(learned_path)
    by_id = {e.id: e for e in learned}
    by_id[source_id] = updated
    save_learned_entries(list(by_id.values()), learned_path)
    return updated.model_dump()
