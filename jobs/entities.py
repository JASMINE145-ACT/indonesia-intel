from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Company, Project
from taxonomy.registry import validate_industry, validate_project_stage


def _norm(name: str) -> str:
    return name.strip()


def company_upsert(
    session: Session,
    *,
    name_cn: str,
    name_en: str | None = None,
    name_id: str | None = None,
    brand: str | None = None,
    parent_company_id: int | None = None,
    industry: str | None = None,
    cn_hq: str | None = None,
    id_presence: str | None = None,
    is_listed: bool | None = None,
    first_entry_date: str | None = None,
    website: str | None = None,
    summary: str | None = None,
    main_business_id: str | None = None,
) -> Company:
    """企业档案 upsert（PRD §5.1）。按 name_cn 做自然键，实体自动合并是二期功能。"""
    name = _norm(name_cn)
    if not name:
        raise ValueError("name_cn is required")
    if industry is not None and not validate_industry(industry):
        raise ValueError(f"industry not in controlled taxonomy: {industry}")

    row = session.scalar(select(Company).where(Company.name_cn == name))
    now = datetime.now(timezone.utc)
    if row is None:
        row = Company(name_cn=name, created_at=now, updated_at=now)
        session.add(row)

    updates = {
        "name_en": name_en,
        "name_id": name_id,
        "brand": brand,
        "parent_company_id": parent_company_id,
        "industry": industry,
        "cn_hq": cn_hq,
        "id_presence": id_presence,
        "first_entry_date": first_entry_date,
        "website": website,
        "summary": summary,
        "main_business_id": main_business_id,
    }
    for field, value in updates.items():
        if value is not None:
            setattr(row, field, value)
    if is_listed is not None:
        row.is_listed = is_listed
    row.updated_at = now

    session.commit()
    session.refresh(row)
    return row


def company_get(session: Session, company_id: int) -> Company | None:
    return session.get(Company, company_id)


def company_list(
    session: Session, *, industry: str | None = None, limit: int = 50
) -> list[Company]:
    stmt = select(Company)
    if industry:
        stmt = stmt.where(Company.industry == industry)
    stmt = stmt.order_by(Company.updated_at.desc()).limit(max(1, min(int(limit), 200)))
    return list(session.scalars(stmt))


def project_upsert(
    session: Session,
    *,
    project_id: int | None = None,
    name: str = "",
    company_id: int | None = None,
    industry: str | None = None,
    location: str | None = None,
    stage: str | None = None,
    investment_amount: str | None = None,
    planned_capacity: str | None = None,
    partners: str | None = None,
    notes: str | None = None,
) -> Project:
    """项目档案 upsert（PRD §5.3）。传 project_id 追加同一时间线，否则按 name(+company_id) 匹配或新建。"""
    if industry is not None and not validate_industry(industry):
        raise ValueError(f"industry not in controlled taxonomy: {industry}")
    if stage is not None and not validate_project_stage(stage):
        raise ValueError(f"stage not in controlled taxonomy: {stage}")

    now = datetime.now(timezone.utc)
    if project_id is not None:
        row = session.get(Project, project_id)
        if row is None:
            raise KeyError(f"project not found: {project_id}")
        if name.strip():
            row.name = _norm(name)
    else:
        name_norm = _norm(name)
        if not name_norm:
            raise ValueError("name is required to create a new project")
        stmt = select(Project).where(Project.name == name_norm)
        if company_id is not None:
            stmt = stmt.where(Project.company_id == company_id)
        row = session.scalar(stmt)
        if row is None:
            row = Project(name=name_norm, created_at=now, updated_at=now)
            session.add(row)

    updates = {
        "company_id": company_id,
        "industry": industry,
        "location": location,
        "stage": stage,
        "investment_amount": investment_amount,
        "planned_capacity": planned_capacity,
        "partners": partners,
        "notes": notes,
    }
    for field, value in updates.items():
        if value is not None:
            setattr(row, field, value)
    row.updated_at = now

    session.commit()
    session.refresh(row)
    return row


def project_get(session: Session, project_id: int) -> Project | None:
    return session.get(Project, project_id)


def project_list(
    session: Session,
    *,
    company_id: int | None = None,
    stage: str | None = None,
    limit: int = 50,
) -> list[Project]:
    stmt = select(Project)
    if company_id:
        stmt = stmt.where(Project.company_id == company_id)
    if stage:
        stmt = stmt.where(Project.stage == stage)
    stmt = stmt.order_by(Project.updated_at.desc()).limit(max(1, min(int(limit), 200)))
    return list(session.scalars(stmt))
