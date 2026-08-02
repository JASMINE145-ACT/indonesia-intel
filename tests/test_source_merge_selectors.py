"""D8: learned merge must not wipe registry discovery selectors."""

from pathlib import Path

import yaml

from sources.registry import SourceEntry
from sources.store import load_merged, save_learned_entries, sources_set_enabled


def test_learned_enabled_does_not_wipe_registry_selectors(tmp_path) -> None:
    reg = tmp_path / "registry.yaml"
    learned = tmp_path / "learned.yaml"
    reg.write_text(
        yaml.safe_dump(
            {
                "sources": [
                    {
                        "id": "kompas_like",
                        "name": "K",
                        "domain": "example.com",
                        "fetch_mode": "sitemap",
                        "sitemap_url": "https://www.example.com/sitemap.xml",
                        "item_selector": "article.item",
                        "list_url": "https://www.example.com/",
                        "include_patterns": "/read/",
                        "enabled": True,
                    }
                ]
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    learned.write_text("sources: []\n", encoding="utf-8")

    sources_set_enabled(
        "kompas_like",
        False,
        registry_path=reg,
        learned_path=learned,
    )
    merged = load_merged(reg, learned)
    src = merged.get("kompas_like")
    assert src is not None
    assert src.enabled is False
    assert src.sitemap_url == "https://www.example.com/sitemap.xml"
    assert src.item_selector == "article.item"
    assert src.include_patterns == "/read/"


def test_learned_empty_selectors_do_not_override(tmp_path) -> None:
    reg = tmp_path / "registry.yaml"
    learned = tmp_path / "learned.yaml"
    reg.write_text(
        yaml.safe_dump(
            {
                "sources": [
                    {
                        "id": "x",
                        "name": "X",
                        "domain": "example.com",
                        "sitemap_url": "https://www.example.com/sm.xml",
                        "item_selector": "div.keep",
                        "enabled": True,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    save_learned_entries(
        [
            SourceEntry(
                id="x",
                name="X",
                domain="example.com",
                sitemap_url="",
                item_selector="",
                enabled=True,
                notes="learned stub",
            )
        ],
        learned,
    )
    src = load_merged(reg, learned).get("x")
    assert src.sitemap_url == "https://www.example.com/sm.xml"
    assert src.item_selector == "div.keep"
