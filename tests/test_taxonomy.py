from taxonomy.registry import (
    list_taxonomy,
    validate_event_type,
    validate_industry,
    validate_project_stage,
    validate_source_attribution,
)


def test_list_taxonomy_has_all_four_axes() -> None:
    t = list_taxonomy()
    assert "汽车、工程机械与交通装备" in t["industries"]
    assert "签约与战略合作" in t["event_types"]
    assert "线索发现" in t["project_stages"]
    assert "待验证" in t["source_attributions"]


def test_validate_none_is_always_allowed() -> None:
    assert validate_industry(None)
    assert validate_event_type(None)
    assert validate_project_stage(None)
    assert validate_source_attribution(None)


def test_validate_rejects_unknown_values() -> None:
    assert not validate_industry("乱写行业")
    assert not validate_event_type("乱写动态类型")
    assert not validate_project_stage("乱写阶段")
    assert not validate_source_attribution("乱写来源属性")


def test_validate_accepts_known_values() -> None:
    assert validate_industry("数字科技、AI 与通信")
    assert validate_event_type("开工建设")
    assert validate_project_stage("投产")
    assert validate_source_attribution("企业官方")
