from __future__ import annotations

from difflib import SequenceMatcher

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import FormalEvent, ReviewCandidate


def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a.strip().lower(), b.strip().lower()).ratio()


def dedup_check(
    session: Session,
    candidate_id: int,
    *,
    threshold: float = 0.55,
    limit: int = 5,
) -> dict:
    """疑似重复事件检测（PRD §4.3）— 标题相似度启发式（stdlib difflib，无外部依赖）。

    只负责把候选摆出来，合并/忽略/入库的最终决定仍由人工在 confirm/ignore 时做出。
    """
    cand = session.get(ReviewCandidate, candidate_id)
    if cand is None:
        raise KeyError(f"candidate not found: {candidate_id}")

    likely_events = []
    for row in session.scalars(select(FormalEvent)):
        score = _similarity(cand.title, row.title)
        if score >= threshold:
            likely_events.append(
                {
                    "formal_event_id": row.id,
                    "title": row.title,
                    "similarity": round(score, 3),
                    "canonical_url": row.canonical_url,
                    "company_id": row.company_id,
                    "project_id": row.project_id,
                }
            )
    likely_events.sort(key=lambda m: m["similarity"], reverse=True)

    likely_pending = []
    for row in session.scalars(
        select(ReviewCandidate).where(
            ReviewCandidate.status.in_(("discovered", "pending_review")),
            ReviewCandidate.id != candidate_id,
        )
    ):
        score = _similarity(cand.title, row.title)
        if score >= threshold:
            likely_pending.append(
                {
                    "candidate_id": row.id,
                    "title": row.title,
                    "similarity": round(score, 3),
                    "status": row.status,
                    "canonical_url": row.canonical_url,
                }
            )
    likely_pending.sort(key=lambda m: m["similarity"], reverse=True)

    return {
        "candidate_id": candidate_id,
        "title": cand.title,
        "likely_duplicate_events": likely_events[:limit],
        "likely_duplicate_pending": likely_pending[:limit],
    }
