import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from jobs.entities import company_get, company_list, company_upsert, project_get, project_list, project_upsert


def _session(tmp_path):
    db = tmp_path / "entities.db"
    engine = create_engine(f"sqlite:///{db}", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)()


def test_company_upsert_creates_then_merges_by_name_cn(tmp_path) -> None:
    session = _session(tmp_path)
    created = company_upsert(session, name_cn="比亚迪", industry="汽车、工程机械与交通装备")
    assert created.id is not None
    assert created.industry == "汽车、工程机械与交通装备"

    merged = company_upsert(session, name_cn="比亚迪", name_en="BYD", website="https://byd.com")
    assert merged.id == created.id
    assert merged.name_en == "BYD"
    assert merged.industry == "汽车、工程机械与交通装备"  # untouched field preserved
    assert company_get(session, created.id) is not None


def test_company_upsert_rejects_unknown_industry(tmp_path) -> None:
    session = _session(tmp_path)
    with pytest.raises(ValueError):
        company_upsert(session, name_cn="某公司", industry="乱写行业")


def test_company_upsert_requires_name(tmp_path) -> None:
    session = _session(tmp_path)
    with pytest.raises(ValueError):
        company_upsert(session, name_cn="   ")


def test_company_list_filters_by_industry(tmp_path) -> None:
    session = _session(tmp_path)
    company_upsert(session, name_cn="比亚迪", industry="汽车、工程机械与交通装备")
    company_upsert(session, name_cn="宁德时代", industry="新能源电池与材料")

    auto_only = company_list(session, industry="汽车、工程机械与交通装备")
    assert [c.name_cn for c in auto_only] == ["比亚迪"]
    assert len(company_list(session)) == 2


def test_project_upsert_creates_and_appends_same_timeline(tmp_path) -> None:
    session = _session(tmp_path)
    company = company_upsert(session, name_cn="比亚迪")

    created = project_upsert(
        session,
        name="比亚迪 Subang 工厂",
        company_id=company.id,
        stage="签约",
        location="西爪哇 Subang",
    )
    assert created.stage == "签约"

    advanced = project_upsert(session, project_id=created.id, stage="建设")
    assert advanced.id == created.id
    assert advanced.stage == "建设"
    assert advanced.location == "西爪哇 Subang"  # untouched field preserved
    assert project_get(session, created.id) is not None


def test_project_upsert_matches_existing_by_name_and_company(tmp_path) -> None:
    session = _session(tmp_path)
    company = company_upsert(session, name_cn="比亚迪")
    first = project_upsert(session, name="比亚迪 Subang 工厂", company_id=company.id, stage="签约")
    same = project_upsert(session, name="比亚迪 Subang 工厂", company_id=company.id, stage="开工")
    assert same.id == first.id
    assert same.stage == "开工"


def test_project_upsert_rejects_unknown_stage(tmp_path) -> None:
    session = _session(tmp_path)
    with pytest.raises(ValueError):
        project_upsert(session, name="某项目", stage="乱写阶段")


def test_project_upsert_missing_project_id_raises_key_error(tmp_path) -> None:
    session = _session(tmp_path)
    with pytest.raises(KeyError):
        project_upsert(session, project_id=999, stage="建设")


def test_project_list_filters_by_stage_and_company(tmp_path) -> None:
    session = _session(tmp_path)
    company = company_upsert(session, name_cn="比亚迪")
    project_upsert(session, name="项目A", company_id=company.id, stage="签约")
    project_upsert(session, name="项目B", company_id=company.id, stage="建设")

    by_stage = project_list(session, stage="建设")
    assert [p.name for p in by_stage] == ["项目B"]
    assert len(project_list(session, company_id=company.id)) == 2
