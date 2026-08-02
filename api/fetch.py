from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from api.deps import get_db, require_api_key
from app.config import settings
from jobs.fetch_candidates import fetch_discovered_candidates
from storage.blob import LocalBlobStore


router = APIRouter(tags=["fetch"])


class FetchBody(BaseModel):
    limit: int = Field(default=20, ge=1, le=100)
    run_id: str | None = None
    retry_failed: bool = False


@router.post("/fetch")
def post_fetch(
    body: FetchBody | None = None,
    _: str = Depends(require_api_key),
    db: Session = Depends(get_db),
) -> dict:
    """discovered → pending_review (or fetch_failed / soft-pending)."""
    payload = body or FetchBody()
    blob = LocalBlobStore(settings.blob_path)
    return fetch_discovered_candidates(
        db,
        blob,
        limit=payload.limit,
        run_id=payload.run_id,
        retry_failed=payload.retry_failed,
    )
