"""Pipeline / candidate read helpers for ops dashboard."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import DocumentJob, ReviewCandidate

EXTRACTED_TEXT_LIMIT = 50_000

UNFETCHED_USER_HINT = (
    "正文未能自动抓取。请自行打开下方完整链接阅读；"
    "如需入库，可用人工投喂粘贴正文后再确认。"
)


def best_open_url(row: ReviewCandidate) -> str:
    """Prefer the resolved article URL so humans can open the real destination."""
    for candidate in (
        getattr(row, "resolved_url", None),
        row.canonical_url,
        row.original_url,
    ):
        u = (candidate or "").strip()
        if u:
            return u
    return ""


def body_available(row: ReviewCandidate) -> bool:
    return bool((row.object_key or "").strip() or (row.extracted_text or "").strip())


def is_unfetched(row: ReviewCandidate) -> bool:
    """True when automatic body fetch did not succeed (soft-pending or hard fail)."""
    if (row.status or "") == "fetch_failed":
        return True
    fs = getattr(row, "fetch_status", None) or ""
    return fs == "failed"


def unfetched_view_fields(row: ReviewCandidate) -> dict[str, Any]:
    open_url = best_open_url(row)
    failed = is_unfetched(row)
    return {
        "url": open_url,
        "open_url": open_url,
        "canonical_url": row.canonical_url,
        "original_url": row.original_url,
        "resolved_url": getattr(row, "resolved_url", None),
        "body_available": body_available(row),
        "unfetched": failed,
        "user_hint": UNFETCHED_USER_HINT if failed else None,
    }


def pipeline_summary(session: Session) -> dict[str, Any]:
    status_rows = session.execute(
        select(ReviewCandidate.status, func.count(ReviewCandidate.id)).group_by(
            ReviewCandidate.status
        )
    ).all()
    method_rows = session.execute(
        select(ReviewCandidate.discovery_method, func.count(ReviewCandidate.id)).group_by(
            ReviewCandidate.discovery_method
        )
    ).all()
    fetch_err_rows = session.execute(
        select(ReviewCandidate.fetch_error_type, func.count(ReviewCandidate.id)).group_by(
            ReviewCandidate.fetch_error_type
        )
    ).all()
    doc_rows = session.execute(
        select(DocumentJob.status, func.count(DocumentJob.id)).group_by(DocumentJob.status)
    ).all()
    counts_by_status = {str(k or "unknown"): int(c) for k, c in status_rows}
    counts_by_discovery_method = {str(k or "unknown"): int(c) for k, c in method_rows}
    counts_by_fetch_error_type = {
        str(k if k is not None else "none"): int(c) for k, c in fetch_err_rows
    }
    counts_by_document_job_status = {str(k or "unknown"): int(c) for k, c in doc_rows}
    document_jobs_total = sum(counts_by_document_job_status.values())
    total = sum(counts_by_status.values())
    search_only = int(counts_by_discovery_method.get("search", 0)) + int(
        counts_by_discovery_method.get("unknown", 0)
    )
    discovery_total = sum(counts_by_discovery_method.values()) or 1
    search_only_ratio = round(search_only / discovery_total, 4)
    return {
        "total": total,
        "counts_by_status": counts_by_status,
        "counts_by_discovery_method": counts_by_discovery_method,
        "counts_by_fetch_error_type": counts_by_fetch_error_type,
        "counts_by_document_job_status": counts_by_document_job_status,
        "search_only_ratio": search_only_ratio,
        "lanes": {
            "discovery": {
                **counts_by_discovery_method,
                "search_only_ratio": search_only_ratio,
            },
            "fetch": counts_by_fetch_error_type,
            "document": {
                "document_jobs": document_jobs_total,
                **counts_by_document_job_status,
            },
        },
    }


def candidate_detail(session: Session, candidate_id: int) -> dict[str, Any]:
    row = session.get(ReviewCandidate, candidate_id)
    if row is None:
        raise KeyError(f"candidate not found: {candidate_id}")
    text = row.extracted_text or ""
    truncated = len(text) > EXTRACTED_TEXT_LIMIT
    if truncated:
        text = text[:EXTRACTED_TEXT_LIMIT]
    return {
        "id": row.id,
        "title": row.title,
        **unfetched_view_fields(row),
        "status": row.status,
        "fetch_status": getattr(row, "fetch_status", None),
        "fetch_error_type": getattr(row, "fetch_error_type", None),
        "provider": row.provider,
        "source_id": row.source_id,
        "discovery_method": getattr(row, "discovery_method", None),
        "snippet": row.snippet or "",
        "extracted_text": text,
        "extracted_text_truncated": truncated,
        "extracted_text_limit": EXTRACTED_TEXT_LIMIT,
        "published_at": row.published_at.isoformat() if row.published_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "object_key": row.object_key,
    }


def list_item_dict(row: ReviewCandidate) -> dict[str, Any]:
    return {
        "id": row.id,
        "title": row.title,
        **unfetched_view_fields(row),
        "status": row.status,
        "fetch_status": getattr(row, "fetch_status", None),
        "fetch_error_type": getattr(row, "fetch_error_type", None),
        "provider": row.provider,
        "source_id": row.source_id,
        "discovery_method": getattr(row, "discovery_method", None),
        "object_key": row.object_key,
        "snippet": (row.extracted_text or row.snippet or "")[:280],
    }
