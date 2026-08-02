from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from api.deps import get_db, require_api_key
from jobs.csv_export import export_events_csv
from jobs.dedup_check import dedup_check as do_dedup_check
from jobs.entities import company_list, company_upsert, project_list, project_upsert
from jobs.event_sources import event_add_source, event_list_sources
from jobs.factcheck import factcheck_event as do_factcheck
from jobs.ops_dashboard import pipeline_summary
from jobs.stats import dashboard_summary
from taxonomy.registry import list_taxonomy

router = APIRouter(tags=["intel"])


@router.get("/taxonomy")
def get_taxonomy(_: str = Depends(require_api_key)) -> dict:
    """PRD §6 受控词表：industries / event_types / project_stages."""
    return list_taxonomy()


@router.get("/pipeline/summary")
def get_pipeline_summary(
    _: str = Depends(require_api_key),
    db: Session = Depends(get_db),
) -> dict:
    """Candidate queue counts — WANd.INTEL.PIPELINE_SUMMARY.001 (not formal analytics)."""
    return pipeline_summary(db)


@router.get("/stats")
def get_stats(
    industry: str | None = None,
    event_type: str | None = None,
    project_stage: str | None = None,
    company_id: int | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    public_only: bool = False,
    location: str | None = None,
    _: str = Depends(require_api_key),
    db: Session = Depends(get_db),
) -> dict:
    """PRD §7.1 固定分析看板（含扩展分布；location 为 contains 筛选）。"""
    return dashboard_summary(
        db,
        industry=industry,
        event_type=event_type,
        project_stage=project_stage,
        company_id=company_id,
        date_from=date_from,
        date_to=date_to,
        public_only=public_only,
        location=location,
    )


@router.get("/candidates/{candidate_id}/dedup-check")
def get_dedup_check(
    candidate_id: int,
    threshold: float = 0.55,
    limit: int = 5,
    _: str = Depends(require_api_key),
    db: Session = Depends(get_db),
) -> dict:
    """PRD §4.3 疑似重复检测。"""
    try:
        return do_dedup_check(db, candidate_id, threshold=threshold, limit=limit)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


class EventSourceBody(BaseModel):
    url: str
    label: str | None = None


@router.get("/formal-events/{formal_event_id}/sources")
def list_event_sources(
    formal_event_id: int,
    _: str = Depends(require_api_key),
    db: Session = Depends(get_db),
) -> dict:
    """PRD §5.4 信息来源：同一事件的全部来源。"""
    try:
        rows = event_list_sources(db, formal_event_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {
        "count": len(rows),
        "items": [
            {"id": r.id, "url": r.url, "source_domain": r.source_domain, "label": r.label}
            for r in rows
        ],
    }


@router.post("/formal-events/{formal_event_id}/sources")
def add_event_source(
    formal_event_id: int,
    body: EventSourceBody,
    _: str = Depends(require_api_key),
    db: Session = Depends(get_db),
) -> dict:
    try:
        row = event_add_source(db, formal_event_id, body.url, label=body.label)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"id": row.id, "event_id": row.event_id, "url": row.url}


@router.get("/formal-events/{formal_event_id}/factcheck")
def get_factcheck(
    formal_event_id: int,
    _: str = Depends(require_api_key),
    db: Session = Depends(get_db),
) -> dict:
    """PRD §9 事实检查面板。"""
    try:
        return do_factcheck(db, formal_event_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/export/events.csv")
def export_events(
    industry: str | None = None,
    event_type: str | None = None,
    project_stage: str | None = None,
    company_id: int | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    public_only: bool = False,
    _: str = Depends(require_api_key),
    db: Session = Depends(get_db),
) -> Response:
    """PRD §11.1 Excel 导入导出：确认过的 formal_events 导出为 CSV。"""
    csv_text = export_events_csv(
        db,
        industry=industry,
        event_type=event_type,
        project_stage=project_stage,
        company_id=company_id,
        date_from=date_from,
        date_to=date_to,
        public_only=public_only,
    )
    return Response(
        content=csv_text,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=formal_events.csv"},
    )


class CompanyBody(BaseModel):
    name_cn: str
    name_en: str | None = None
    name_id: str | None = None
    brand: str | None = None
    parent_company_id: int | None = None
    industry: str | None = None
    cn_hq: str | None = None
    id_presence: str | None = None
    is_listed: bool | None = None
    first_entry_date: str | None = None
    website: str | None = None
    summary: str | None = None
    main_business_id: str | None = None


@router.get("/companies")
def list_companies(
    industry: str | None = None,
    limit: int = 50,
    _: str = Depends(require_api_key),
    db: Session = Depends(get_db),
) -> dict:
    """PRD §10 企业库。"""
    rows = company_list(db, industry=industry, limit=limit)
    return {
        "count": len(rows),
        "items": [
            {
                "id": r.id,
                "name_cn": r.name_cn,
                "name_en": r.name_en,
                "industry": r.industry,
                "is_listed": r.is_listed,
                "first_entry_date": r.first_entry_date,
            }
            for r in rows
        ],
    }


@router.post("/companies")
def upsert_company(
    body: CompanyBody,
    _: str = Depends(require_api_key),
    db: Session = Depends(get_db),
) -> dict:
    try:
        row = company_upsert(db, **body.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"id": row.id, "name_cn": row.name_cn}


class ProjectBody(BaseModel):
    project_id: int | None = None
    name: str = ""
    company_id: int | None = None
    industry: str | None = None
    location: str | None = None
    stage: str | None = None
    investment_amount: str | None = None
    planned_capacity: str | None = None
    partners: str | None = None
    notes: str | None = None


@router.get("/projects")
def list_projects(
    company_id: int | None = None,
    stage: str | None = None,
    limit: int = 50,
    _: str = Depends(require_api_key),
    db: Session = Depends(get_db),
) -> dict:
    """PRD §10 项目库：项目时间线。"""
    rows = project_list(db, company_id=company_id, stage=stage, limit=limit)
    return {
        "count": len(rows),
        "items": [
            {
                "id": r.id,
                "name": r.name,
                "company_id": r.company_id,
                "industry": r.industry,
                "stage": r.stage,
                "location": r.location,
            }
            for r in rows
        ],
    }


@router.post("/projects")
def upsert_project(
    body: ProjectBody,
    _: str = Depends(require_api_key),
    db: Session = Depends(get_db),
) -> dict:
    try:
        row = project_upsert(db, **body.model_dump())
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"id": row.id, "name": row.name, "stage": row.stage}
