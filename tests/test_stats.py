from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import Company, EventSource, FormalEvent
from jobs.stats import (
    LEGACY_SUMMARY_KEYS,
    company_new_vs_existing,
    company_ranking,
    dashboard_summary,
    event_type_distribution,
    industry_distribution,
    investment_amount_raw,
    investment_presence,
    location_distribution,
    monthly_trend,
    partner_distribution,
    project_stage_distribution,
    source_distribution,
)


def _session(tmp_path):
    db = tmp_path / "stats.db"
    engine = create_engine(f"sqlite:///{db.as_posix()}", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)()


def _seed(session) -> Company:
    byd = Company(name_cn="比亚迪")
    session.add(byd)
    session.commit()

    session.add_all(
        [
            FormalEvent(
                candidate_id=1,
                title="比亚迪签约",
                canonical_url="https://example.com/1",
                provider="mock",
                company_id=byd.id,
                industry="汽车、工程机械与交通装备",
                event_type="签约与战略合作",
                project_stage="签约",
                occurred_date="2026-05-10",
                is_public=True,
            ),
            FormalEvent(
                candidate_id=2,
                title="比亚迪开工",
                canonical_url="https://example.com/2",
                provider="mock",
                company_id=byd.id,
                industry="汽车、工程机械与交通装备",
                event_type="开工建设",
                project_stage="开工",
                occurred_date="2026-06-01",
                is_public=True,
            ),
            FormalEvent(
                candidate_id=3,
                title="宁德时代基金",
                canonical_url="https://example.com/3",
                provider="mock",
                industry="新能源电池与材料",
                event_type="基金设立",
                project_stage=None,
                occurred_date="2026-06-15",
                is_public=False,
            ),
        ]
    )
    session.commit()
    return byd


def test_industry_distribution(tmp_path) -> None:
    session = _session(tmp_path)
    _seed(session)
    dist = industry_distribution(session)
    assert {"industry": "汽车、工程机械与交通装备", "count": 2} in dist
    assert {"industry": "新能源电池与材料", "count": 1} in dist


def test_event_type_distribution_with_filter(tmp_path) -> None:
    session = _session(tmp_path)
    _seed(session)
    dist = event_type_distribution(session, industry="汽车、工程机械与交通装备")
    assert sorted(d["event_type"] for d in dist) == ["开工建设", "签约与战略合作"]


def test_project_stage_distribution_labels_missing(tmp_path) -> None:
    session = _session(tmp_path)
    _seed(session)
    dist = project_stage_distribution(session)
    assert any(d["project_stage"] == "未标注" and d["count"] == 1 for d in dist)


def test_monthly_trend_buckets_by_month(tmp_path) -> None:
    session = _session(tmp_path)
    _seed(session)
    trend = monthly_trend(session)
    assert {"month": "2026-05", "count": 1} in trend
    assert {"month": "2026-06", "count": 2} in trend


def test_company_ranking_only_counts_tagged_events(tmp_path) -> None:
    session = _session(tmp_path)
    byd = _seed(session)
    ranking = company_ranking(session)
    assert ranking == [{"company_id": byd.id, "company": "比亚迪", "count": 2}]


def test_public_only_filter_excludes_private_events(tmp_path) -> None:
    session = _session(tmp_path)
    _seed(session)
    dist = industry_distribution(session, public_only=True)
    assert sum(d["count"] for d in dist) == 2


def test_legacy_five_blocks_unchanged(tmp_path) -> None:
    session = _session(tmp_path)
    byd = _seed(session)
    summary = dashboard_summary(session)
    for key in LEGACY_SUMMARY_KEYS:
        assert key in summary
    assert {"industry": "汽车、工程机械与交通装备", "count": 2} in summary["industry_distribution"]
    assert {"industry": "新能源电池与材料", "count": 1} in summary["industry_distribution"]
    assert sorted(d["event_type"] for d in summary["event_type_distribution"]) == [
        "基金设立",
        "开工建设",
        "签约与战略合作",
    ]
    assert any(d["project_stage"] == "未标注" and d["count"] == 1 for d in summary["project_stage_distribution"])
    assert {"month": "2026-05", "count": 1} in summary["monthly_trend"]
    assert {"month": "2026-06", "count": 2} in summary["monthly_trend"]
    assert summary["company_ranking"] == [{"company_id": byd.id, "company": "比亚迪", "count": 2}]


def test_dashboard_summary_shape(tmp_path) -> None:
    session = _session(tmp_path)
    _seed(session)
    summary = dashboard_summary(session)
    assert set(summary.keys()) == {
        "filters",
        "industry_distribution",
        "event_type_distribution",
        "project_stage_distribution",
        "monthly_trend",
        "company_ranking",
        "location_distribution",
        "source_distribution",
        "partner_distribution",
        "investment_presence",
        "investment_amount_raw",
        "company_new_vs_existing",
    }


def test_location_distribution_and_empty_label(tmp_path) -> None:
    session = _session(tmp_path)
    _seed(session)
    rows = list(session.scalars(select(FormalEvent)))
    rows[0].location = "西爪哇Subang"
    rows[1].location = "西爪哇Subang"
    session.commit()
    dist = location_distribution(session)
    assert {"location": "西爪哇Subang", "count": 2} in dist
    assert {"location": "未标注", "count": 1} in dist


def test_location_filter_contains(tmp_path) -> None:
    session = _session(tmp_path)
    _seed(session)
    rows = list(session.scalars(select(FormalEvent)))
    rows[0].location = "西爪哇Subang"
    rows[1].location = "雅加达"
    session.commit()
    dist = location_distribution(session, location="爪哇")
    assert dist == [{"location": "西爪哇Subang", "count": 1}]


def test_source_distribution_multi_row(tmp_path) -> None:
    session = _session(tmp_path)
    _seed(session)
    rows = list(session.scalars(select(FormalEvent)))
    eid = rows[0].id
    session.add_all(
        [
            EventSource(event_id=eid, url="https://a.example/1", source_domain="antara.or.id"),
            EventSource(event_id=eid, url="https://b.example/1", source_domain="antara.or.id"),
        ]
    )
    session.commit()
    dist = source_distribution(session)
    assert {"source": "antara.or.id", "count": 2} in dist
    assert any(d["source"] == "provider:mock" and d["count"] >= 1 for d in dist)


def test_partner_distribution_empty(tmp_path) -> None:
    session = _session(tmp_path)
    _seed(session)
    dist = partner_distribution(session)
    assert dist == [{"partner": "未标注", "count": 3}]


def test_investment_presence(tmp_path) -> None:
    session = _session(tmp_path)
    _seed(session)
    rows = list(session.scalars(select(FormalEvent)))
    rows[0].investment_amount = "11.2万亿印尼盾"
    session.commit()
    assert investment_presence(session) == {"with_amount": 1, "without_amount": 2}


def test_investment_raw_topn_tiebreak(tmp_path) -> None:
    session = _session(tmp_path)
    _seed(session)
    rows = list(session.scalars(select(FormalEvent)))
    rows[0].investment_amount = "B-amount"
    rows[1].investment_amount = "A-amount"
    session.commit()
    raw = investment_amount_raw(session)
    assert raw == [
        {"amount": "A-amount", "count": 1},
        {"amount": "B-amount", "count": 1},
    ]


def test_company_new_vs_existing_window(tmp_path) -> None:
    session = _session(tmp_path)
    byd = Company(name_cn="比亚迪", first_entry_date="2024-01-01")
    newco = Company(name_cn="新茶饮", first_entry_date="2026-03-01")
    session.add_all([byd, newco])
    session.commit()
    session.add_all(
        [
            FormalEvent(
                candidate_id=10,
                title="旧企动态",
                canonical_url="https://example.com/old",
                provider="mock",
                company_id=byd.id,
                industry="汽车、工程机械与交通装备",
                occurred_date="2026-05-01",
                is_public=True,
            ),
            FormalEvent(
                candidate_id=11,
                title="新企动态",
                canonical_url="https://example.com/new",
                provider="mock",
                company_id=newco.id,
                industry="消费品牌、家电与服务业",
                occurred_date="2026-05-02",
                is_public=True,
            ),
        ]
    )
    session.commit()
    result = company_new_vs_existing(session, date_from="2026-01-01", date_to="2026-06-30")
    assert result == {"new": 1, "existing": 1, "unknown": 0}
