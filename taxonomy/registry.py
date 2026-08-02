from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent
DEFAULT_REGISTRY = ROOT / "registry.yaml"


def _load(registry_path: Path | str | None = None) -> dict[str, list[str]]:
    path = Path(registry_path or DEFAULT_REGISTRY)
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {
        "industries": list(data.get("industries") or []),
        "event_types": list(data.get("event_types") or []),
        "project_stages": list(data.get("project_stages") or []),
        "source_attributions": list(data.get("source_attributions") or []),
    }


def list_taxonomy(registry_path: Path | str | None = None) -> dict[str, list[str]]:
    """PRD §6 受控词表：行业 / 动态类型 / 项目阶段 / 来源属性。人工编辑 registry.yaml 来扩展。"""
    return _load(registry_path)


def validate_industry(value: str | None, registry_path: Path | str | None = None) -> bool:
    return value is None or value in _load(registry_path)["industries"]


def validate_event_type(value: str | None, registry_path: Path | str | None = None) -> bool:
    return value is None or value in _load(registry_path)["event_types"]


def validate_project_stage(value: str | None, registry_path: Path | str | None = None) -> bool:
    return value is None or value in _load(registry_path)["project_stages"]


def validate_source_attribution(value: str | None, registry_path: Path | str | None = None) -> bool:
    return value is None or value in _load(registry_path)["source_attributions"]
