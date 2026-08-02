from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.deps import get_db, require_api_key
from app.models import ReviewCandidate
from jobs.manual_intake import manual_add_candidate, manual_add_pdf
from jobs.ops_dashboard import candidate_detail, list_item_dict
from jobs.review_actions import confirm_candidate as do_confirm
from jobs.review_actions import ignore_candidate as do_ignore
from jobs.review_actions import merge_candidate as do_merge
from jobs.review_actions import watch_candidate as do_watch


router = APIRouter(prefix="/candidates", tags=["review"])


class DecisionBody(BaseModel):
    reason: str | None = None
    company_id: int | None = None
    company_name: str | None = None
    project_id: int | None = None
    industry: str | None = None
    event_type: str | None = None
    project_stage: str | None = None
    occurred_date: str | None = None
    published_date: str | None = None
    location: str | None = None
    investment_amount: str | None = None
    planned_capacity: str | None = None
    partners: str | None = None
    summary: str | None = None
    credibility: str | None = None
    is_public: bool | None = None
    notes: str | None = None
    allow_unfetched: bool = False


class ManualIntakeBody(BaseModel):
    title: str
    url: str = ""
    text: str = ""
    source_attribution: str = "待验证"
    is_public_source: bool = True


@router.get("")
def list_candidates(
    status: str = "pending_review",
    _: str = Depends(require_api_key),
    db: Session = Depends(get_db),
) -> dict:
    rows = list(
        db.scalars(select(ReviewCandidate).where(ReviewCandidate.status == status).limit(100))
    )
    return {"items": [list_item_dict(r) for r in rows]}


@router.get("/{candidate_id}")
def get_candidate(
    candidate_id: int,
    _: str = Depends(require_api_key),
    db: Session = Depends(get_db),
) -> dict:
    """Ops dashboard detail — WANd.INTEL.CANDIDATE_DETAIL.001."""
    try:
        return candidate_detail(db, candidate_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


class ManualPdfBody(BaseModel):
    path: str
    source_attribution: str = "待验证"
    is_public_source: bool = True
    title: str = ""


@router.post("/manual")
def add_manual_candidate(
    body: ManualIntakeBody,
    _: str = Depends(require_api_key),
    db: Session = Depends(get_db),
) -> dict:
    """PRD §4.4 人工投喂：链接 / 粘贴文字 / 无公开链接的手工事件，统一落到待审核池。"""
    try:
        row = manual_add_candidate(
            db,
            title=body.title,
            url=body.url,
            text=body.text,
            source_attribution=body.source_attribution,
            is_public_source=body.is_public_source,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"id": row.id, "status": row.status, "canonical_url": row.canonical_url}


@router.post("/manual-pdf")
def add_manual_pdf(
    body: ManualPdfBody,
    _: str = Depends(require_api_key),
    db: Session = Depends(get_db),
) -> dict:
    """PRD §4.4 本地 PDF → 抽文本 → pending_review。"""
    try:
        row = manual_add_pdf(
            db,
            body.path,
            source_attribution=body.source_attribution,
            is_public_source=body.is_public_source,
            title=body.title,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "id": row.id,
        "status": row.status,
        "canonical_url": row.canonical_url,
        "title": row.title,
    }


@router.post("/{candidate_id}/confirm")
def confirm_candidate(
    candidate_id: int,
    body: DecisionBody | None = None,
    _: str = Depends(require_api_key),
    db: Session = Depends(get_db),
) -> dict:
    b = body or DecisionBody()
    try:
        return do_confirm(
            db,
            candidate_id,
            reason=b.reason,
            company_id=b.company_id,
            company_name=b.company_name,
            project_id=b.project_id,
            industry=b.industry,
            event_type=b.event_type,
            project_stage=b.project_stage,
            occurred_date=b.occurred_date,
            published_date=b.published_date,
            location=b.location,
            investment_amount=b.investment_amount,
            planned_capacity=b.planned_capacity,
            partners=b.partners,
            summary=b.summary,
            credibility=b.credibility,
            is_public=b.is_public,
            notes=b.notes,
            allow_unfetched=b.allow_unfetched,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        msg = str(exc)
        code = 409 if msg.startswith("status=") else 400
        raise HTTPException(status_code=code, detail=msg) from exc


class MergeBody(BaseModel):
    target_formal_event_id: int
    reason: str | None = None


@router.post("/{candidate_id}/watch")
def watch_candidate(
    candidate_id: int,
    body: DecisionBody | None = None,
    _: str = Depends(require_api_key),
    db: Session = Depends(get_db),
) -> dict:
    try:
        return do_watch(db, candidate_id, reason=(body.reason if body else None))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        msg = str(exc)
        code = 409 if msg.startswith("status=") else 400
        raise HTTPException(status_code=code, detail=msg) from exc


@router.post("/{candidate_id}/merge")
def merge_candidate(
    candidate_id: int,
    body: MergeBody,
    _: str = Depends(require_api_key),
    db: Session = Depends(get_db),
) -> dict:
    try:
        return do_merge(
            db,
            candidate_id,
            target_formal_event_id=body.target_formal_event_id,
            reason=body.reason,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        msg = str(exc)
        code = 409 if msg.startswith("status=") else 400
        raise HTTPException(status_code=code, detail=msg) from exc


@router.post("/{candidate_id}/ignore")
def ignore_candidate(
    candidate_id: int,
    body: DecisionBody | None = None,
    _: str = Depends(require_api_key),
    db: Session = Depends(get_db),
) -> dict:
    try:
        return do_ignore(db, candidate_id, reason=(body.reason if body else None))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        msg = str(exc)
        code = 409 if msg.startswith("status=") else 400
        raise HTTPException(status_code=code, detail=msg) from exc
