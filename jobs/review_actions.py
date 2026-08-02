from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models import FormalEvent, ReviewCandidate, ReviewDecision
from jobs.entities import company_upsert
from jobs.event_sources import event_add_source
from taxonomy.registry import validate_event_type, validate_industry, validate_project_stage

_REVIEWABLE = frozenset({"pending_review", "watching"})


def watch_candidate(
    session: Session,
    candidate_id: int,
    *,
    reason: str | None = None,
    actor: str = "api-key",
) -> dict:
    """Move pending_review → watching (观察列表)."""
    row = session.get(ReviewCandidate, candidate_id)
    if row is None:
        raise KeyError(f"candidate not found: {candidate_id}")
    if row.status != "pending_review":
        raise ValueError(f"status={row.status}; expected pending_review")

    before = row.status
    row.status = "watching"
    row.updated_at = datetime.now(timezone.utc)
    session.add(
        ReviewDecision(
            candidate_id=row.id,
            action="watch",
            before_status=before,
            after_status="watching",
            reason=reason,
            actor=actor,
        )
    )
    session.commit()
    return {"id": row.id, "status": row.status}


def merge_candidate(
    session: Session,
    candidate_id: int,
    *,
    target_formal_event_id: int,
    reason: str | None = None,
    actor: str = "api-key",
) -> dict:
    """Merge candidate into an existing formal_event (add source; status=merged).

    Mutates candidate + decision + EventSource in one commit (atomic).
    """
    row = session.get(ReviewCandidate, candidate_id)
    if row is None:
        raise KeyError(f"candidate not found: {candidate_id}")
    if row.status not in _REVIEWABLE:
        raise ValueError(f"status={row.status}; expected pending_review|watching")
    if not row.canonical_url:
        raise ValueError("missing provenance url")

    event = session.get(FormalEvent, target_formal_event_id)
    if event is None:
        raise KeyError(f"formal_event not found: {target_formal_event_id}")

    before = row.status
    row.status = "merged"
    row.duplicate_of_event_id = int(target_formal_event_id)
    row.updated_at = datetime.now(timezone.utc)
    session.add(
        ReviewDecision(
            candidate_id=row.id,
            action="merge",
            before_status=before,
            after_status="merged",
            reason=reason,
            actor=actor,
        )
    )
    # Inline source add without nested commit (event_add_source commits itself).
    from urllib.parse import urlparse

    from sqlalchemy import select

    from app.models import EventSource

    clean_url = row.canonical_url.strip()
    existing_src = session.scalar(
        select(EventSource).where(
            EventSource.event_id == int(target_formal_event_id),
            EventSource.url == clean_url,
        )
    )
    if existing_src is None:
        session.add(
            EventSource(
                event_id=int(target_formal_event_id),
                url=clean_url,
                source_domain=urlparse(clean_url).netloc or None,
                label="merge_source",
                created_at=datetime.now(timezone.utc),
            )
        )
    session.commit()
    return {
        "id": row.id,
        "status": row.status,
        "duplicate_of_event_id": row.duplicate_of_event_id,
        "formal_event_id": int(target_formal_event_id),
    }


def confirm_candidate(
    session: Session,
    candidate_id: int,
    *,
    reason: str | None = None,
    actor: str = "api-key",
    company_id: int | None = None,
    company_name: str | None = None,
    project_id: int | None = None,
    industry: str | None = None,
    event_type: str | None = None,
    project_stage: str | None = None,
    occurred_date: str | None = None,
    published_date: str | None = None,
    location: str | None = None,
    investment_amount: str | None = None,
    planned_capacity: str | None = None,
    partners: str | None = None,
    summary: str | None = None,
    credibility: str | None = None,
    is_public: bool | None = None,
    notes: str | None = None,
    allow_unfetched: bool = False,
) -> dict:
    """确认入库 — PRD §5.2 企业动态。结构化字段全部可选（向后兼容裸确认），
    但一旦传入就必须落在 §6 受控词表内，否则拒绝写入（防止分类体系跑飞）。
    """
    row = session.get(ReviewCandidate, candidate_id)
    if row is None:
        raise KeyError(f"candidate not found: {candidate_id}")
    if row.status not in _REVIEWABLE:
        raise ValueError(f"status={row.status}; expected pending_review|watching")
    if not row.canonical_url:
        raise ValueError("missing provenance url")

    has_body = bool(row.object_key) or bool((row.extracted_text or "").strip())
    fetch_failed = getattr(row, "fetch_status", None) == "failed"
    if (not has_body or fetch_failed) and not allow_unfetched:
        raise ValueError(
            "unfetched: candidate has no body (object_key empty or fetch_status=failed); "
            "pass allow_unfetched=True to confirm anyway (factcheck will still fail)"
        )

    if not validate_industry(industry):
        raise ValueError(f"industry not in controlled taxonomy: {industry}")
    if not validate_event_type(event_type):
        raise ValueError(f"event_type not in controlled taxonomy: {event_type}")
    if not validate_project_stage(project_stage):
        raise ValueError(f"project_stage not in controlled taxonomy: {project_stage}")

    resolved_company_id = company_id
    if resolved_company_id is None and company_name:
        resolved_company_id = company_upsert(
            session, name_cn=company_name, industry=industry
        ).id

    resolved_is_public = row.is_public_source if is_public is None else is_public

    before = row.status
    row.status = "confirmed"
    row.updated_at = datetime.now(timezone.utc)
    session.add(
        ReviewDecision(
            candidate_id=row.id,
            action="confirm",
            before_status=before,
            after_status="confirmed",
            reason=reason,
            actor=actor,
        )
    )
    event = FormalEvent(
        candidate_id=row.id,
        title=row.title,
        canonical_url=row.canonical_url,
        provider=row.provider,
        object_key=row.object_key,
        company_id=resolved_company_id,
        project_id=project_id,
        industry=industry,
        event_type=event_type,
        project_stage=project_stage,
        occurred_date=occurred_date,
        published_date=published_date,
        location=location,
        investment_amount=investment_amount,
        planned_capacity=planned_capacity,
        partners=partners,
        summary=summary,
        credibility=credibility,
        is_public=resolved_is_public,
        notes=notes,
    )
    session.add(event)
    session.commit()
    session.refresh(event)
    event_add_source(session, event.id, row.canonical_url, label="confirm_source")
    return {
        "id": row.id,
        "status": row.status,
        "company_id": resolved_company_id,
        "formal_event_id": event.id,
    }


def ignore_candidate(
    session: Session,
    candidate_id: int,
    *,
    reason: str | None = None,
    actor: str = "api-key",
) -> dict:
    row = session.get(ReviewCandidate, candidate_id)
    if row is None:
        raise KeyError(f"candidate not found: {candidate_id}")
    if row.status not in _REVIEWABLE:
        raise ValueError(f"status={row.status}; expected pending_review|watching")

    before = row.status
    row.status = "ignored"
    row.updated_at = datetime.now(timezone.utc)
    session.add(
        ReviewDecision(
            candidate_id=row.id,
            action="ignore",
            before_status=before,
            after_status="ignored",
            reason=reason,
            actor=actor,
        )
    )
    session.commit()
    return {"id": row.id, "status": row.status}
