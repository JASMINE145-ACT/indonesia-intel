from __future__ import annotations

from collections import Counter
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.models import Company, EventSource, FormalEvent

PARTNER_KEY_MAX = 128
INVESTMENT_RAW_TOP_N = 20

LEGACY_SUMMARY_KEYS = (
    "industry_distribution",
    "event_type_distribution",
    "project_stage_distribution",
    "monthly_trend",
    "company_ranking",
)


def apply_filters(
    stmt: Select,
    *,
    industry: str | None = None,
    event_type: str | None = None,
    project_stage: str | None = None,
    company_id: int | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    public_only: bool = False,
    location: str | None = None,
) -> Select:
    if industry:
        stmt = stmt.where(FormalEvent.industry == industry)
    if event_type:
        stmt = stmt.where(FormalEvent.event_type == event_type)
    if project_stage:
        stmt = stmt.where(FormalEvent.project_stage == project_stage)
    if company_id:
        stmt = stmt.where(FormalEvent.company_id == company_id)
    if date_from:
        stmt = stmt.where(FormalEvent.occurred_date >= date_from)
    if date_to:
        stmt = stmt.where(FormalEvent.occurred_date <= date_to)
    if public_only:
        stmt = stmt.where(FormalEvent.is_public.is_(True))
    if location:
        stmt = stmt.where(FormalEvent.location.contains(location))
    return stmt


def industry_distribution(session: Session, **filters: Any) -> list[dict]:
    stmt = select(FormalEvent.industry, func.count(FormalEvent.id))
    stmt = apply_filters(stmt, **filters).group_by(FormalEvent.industry)
    stmt = stmt.order_by(func.count(FormalEvent.id).desc())
    return [{"industry": k or "未分类", "count": c} for k, c in session.execute(stmt)]


def event_type_distribution(session: Session, **filters: Any) -> list[dict]:
    stmt = select(FormalEvent.event_type, func.count(FormalEvent.id))
    stmt = apply_filters(stmt, **filters).group_by(FormalEvent.event_type)
    stmt = stmt.order_by(func.count(FormalEvent.id).desc())
    return [{"event_type": k or "未分类", "count": c} for k, c in session.execute(stmt)]


def project_stage_distribution(session: Session, **filters: Any) -> list[dict]:
    stmt = select(FormalEvent.project_stage, func.count(FormalEvent.id))
    stmt = apply_filters(stmt, **filters).group_by(FormalEvent.project_stage)
    stmt = stmt.order_by(func.count(FormalEvent.id).desc())
    return [{"project_stage": k or "未标注", "count": c} for k, c in session.execute(stmt)]


def monthly_trend(session: Session, **filters: Any) -> list[dict]:
    month = func.substr(FormalEvent.occurred_date, 1, 7)
    stmt = select(month, func.count(FormalEvent.id))
    stmt = apply_filters(stmt, **filters).group_by(month).order_by(month)
    return [{"month": k or "未知", "count": c} for k, c in session.execute(stmt)]


def company_ranking(session: Session, *, limit: int = 20, **filters: Any) -> list[dict]:
    stmt = select(FormalEvent.company_id, Company.name_cn, func.count(FormalEvent.id))
    stmt = apply_filters(stmt, **filters).join(Company, Company.id == FormalEvent.company_id)
    stmt = stmt.group_by(FormalEvent.company_id, Company.name_cn)
    stmt = stmt.order_by(func.count(FormalEvent.id).desc()).limit(max(1, min(int(limit), 100)))
    return [
        {"company_id": cid, "company": name, "count": c} for cid, name, c in session.execute(stmt)
    ]


def location_distribution(session: Session, **filters: Any) -> list[dict]:
    loc_key = func.coalesce(func.nullif(func.trim(FormalEvent.location), ""), "未标注")
    stmt = select(loc_key, func.count(FormalEvent.id))
    stmt = apply_filters(stmt, **filters).group_by(loc_key)
    stmt = stmt.order_by(func.count(FormalEvent.id).desc())
    return [{"location": k, "count": c} for k, c in session.execute(stmt)]


def source_distribution(session: Session, **filters: Any) -> list[dict]:
    """Count EventSource rows when present; else one provider:<name> per event."""
    stmt = select(FormalEvent.id, FormalEvent.provider)
    stmt = apply_filters(stmt, **filters)
    counts: Counter[str] = Counter()
    for eid, provider in session.execute(stmt):
        domains = list(
            session.execute(
                select(EventSource.source_domain).where(EventSource.event_id == eid)
            )
        )
        if domains:
            for (domain,) in domains:
                key = (domain or "").strip() or "未知域名"
                counts[key] += 1
        else:
            counts[f"provider:{(provider or 'unknown')}"] += 1
    rows = [{"source": k, "count": c} for k, c in counts.items()]
    rows.sort(key=lambda r: (-r["count"], r["source"]))
    return rows


def _partner_key(raw: str | None) -> str:
    text = (raw or "").strip()
    if not text:
        return "未标注"
    return text[:PARTNER_KEY_MAX]


def partner_distribution(session: Session, **filters: Any) -> list[dict]:
    stmt = select(FormalEvent.partners)
    stmt = apply_filters(stmt, **filters)
    counts: Counter[str] = Counter()
    for (partners,) in session.execute(stmt):
        counts[_partner_key(partners)] += 1
    rows = [{"partner": k, "count": c} for k, c in counts.items()]
    rows.sort(key=lambda r: (-r["count"], r["partner"]))
    return rows


def investment_presence(session: Session, **filters: Any) -> dict[str, int]:
    stmt = select(FormalEvent.investment_amount)
    stmt = apply_filters(stmt, **filters)
    with_amount = 0
    without_amount = 0
    for (amount,) in session.execute(stmt):
        if (amount or "").strip():
            with_amount += 1
        else:
            without_amount += 1
    return {"with_amount": with_amount, "without_amount": without_amount}


def investment_amount_raw(session: Session, **filters: Any) -> list[dict]:
    stmt = select(FormalEvent.investment_amount)
    stmt = apply_filters(stmt, **filters)
    counts: Counter[str] = Counter()
    for (amount,) in session.execute(stmt):
        text = (amount or "").strip()
        if text:
            counts[text] += 1
    rows = [{"amount": k, "count": c} for k, c in counts.items()]
    rows.sort(key=lambda r: (-r["count"], r["amount"]))
    return rows[:INVESTMENT_RAW_TOP_N]


def _company_anchor(session: Session, company_id: int) -> str | None:
    company = session.get(Company, company_id)
    if company and (company.first_entry_date or "").strip():
        return company.first_entry_date.strip()
    min_d = session.execute(
        select(func.min(FormalEvent.occurred_date)).where(FormalEvent.company_id == company_id)
    ).scalar()
    if min_d and str(min_d).strip():
        return str(min_d).strip()
    return None


def company_new_vs_existing(session: Session, **filters: Any) -> dict[str, int]:
    """Classify companies appearing in the filtered event set (see plan Decisions #3)."""
    date_from = filters.get("date_from") or None
    date_to = filters.get("date_to") or None
    stmt = select(FormalEvent.company_id).where(FormalEvent.company_id.isnot(None)).distinct()
    stmt = apply_filters(stmt, **filters)
    company_ids = [cid for (cid,) in session.execute(stmt)]

    new = existing = unknown = 0
    for cid in company_ids:
        anchor = _company_anchor(session, cid)
        if date_from or date_to:
            if anchor is None:
                unknown += 1
                continue
            ge_from = (not date_from) or (anchor >= date_from)
            le_to = (not date_to) or (anchor <= date_to)
            if ge_from and le_to:
                new += 1
            elif date_from and anchor < date_from:
                existing += 1
            else:
                unknown += 1
        else:
            if anchor is None:
                unknown += 1
            else:
                existing += 1
    return {"new": new, "existing": existing, "unknown": unknown}


def dashboard_summary(session: Session, *, company_limit: int = 20, **filters: Any) -> dict:
    """PRD §7.1 固定分析看板（含 §7.1 扩展分布；旧五键 additive 兼容）。"""
    return {
        "filters": filters,
        "industry_distribution": industry_distribution(session, **filters),
        "event_type_distribution": event_type_distribution(session, **filters),
        "project_stage_distribution": project_stage_distribution(session, **filters),
        "monthly_trend": monthly_trend(session, **filters),
        "company_ranking": company_ranking(session, limit=company_limit, **filters),
        "location_distribution": location_distribution(session, **filters),
        "source_distribution": source_distribution(session, **filters),
        "partner_distribution": partner_distribution(session, **filters),
        "investment_presence": investment_presence(session, **filters),
        "investment_amount_raw": investment_amount_raw(session, **filters),
        "company_new_vs_existing": company_new_vs_existing(session, **filters),
    }
