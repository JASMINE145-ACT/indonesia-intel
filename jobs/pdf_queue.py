"""PDF async queue — WANd.INTEL.FETCH_PDF_QUEUE.001 (no OCR)."""

from __future__ import annotations

import hashlib
import time
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

import httpx

from app.models import DocumentJob, ReviewCandidate
from fetch.pdf import extract_pdf_text, looks_like_pdf
from fetch.ssrf import assert_safe_url
from jobs.discovery_flags import pdf_queue_enabled
from storage.blob import LocalBlobStore

WORKER_MAX_PDF_BYTES = 50_000_000
STATUS_PDF_QUEUED = "pdf_queued"


def enqueue_pdf_job(
    session: Session,
    row: ReviewCandidate,
    *,
    url: str,
) -> DocumentJob:
    """Mark candidate pdf_queued and insert a document_jobs row."""
    now = datetime.now(timezone.utc)
    row.status = STATUS_PDF_QUEUED
    row.fetch_status = STATUS_PDF_QUEUED
    row.fetch_error_type = "pdf_too_large"
    row.updated_at = now
    if not row.snippet or row.snippet.startswith("fetch_error:"):
        row.snippet = "pdf_queued: awaiting native extract"

    existing = session.scalar(
        select(DocumentJob).where(
            DocumentJob.candidate_id == row.id,
            DocumentJob.status.in_(("queued", "processing")),
        )
    )
    if existing is not None:
        return existing

    job = DocumentJob(
        candidate_id=row.id,
        url=url,
        url_hash=row.url_hash,
        status="queued",
        attempts=0,
        created_at=now,
        updated_at=now,
    )
    session.add(job)
    return job


def revert_queued_to_failed(session: Session, *, limit: int = 500) -> int:
    """Move pdf_queued candidates → fetch_failed; fail open queue jobs."""
    rows = list(
        session.scalars(
            select(ReviewCandidate)
            .where(ReviewCandidate.status == STATUS_PDF_QUEUED)
            .limit(limit)
        )
    )
    n = 0
    now = datetime.now(timezone.utc)
    for row in rows:
        row.status = "fetch_failed"
        row.fetch_status = "failed"
        row.fetch_error_type = "pdf_too_large"
        row.snippet = "fetch_error: pdf_too_large (reverted from queue)"
        row.updated_at = now
        n += 1
        for job in session.scalars(
            select(DocumentJob).where(
                DocumentJob.candidate_id == row.id,
                DocumentJob.status.in_(("queued", "processing")),
            )
        ):
            job.status = "failed"
            job.failure_reason = "reverted"
            job.updated_at = now
    return n


def _reset_stale_processing(session: Session) -> int:
    jobs = list(
        session.scalars(select(DocumentJob).where(DocumentJob.status == "processing"))
    )
    now = datetime.now(timezone.utc)
    for job in jobs:
        job.status = "queued"
        job.updated_at = now
    return len(jobs)


def _reuse_text_for_sha(
    session: Session, sha: str
) -> tuple[str, str, str | None] | None:
    """Return (title, text, storage_path) if a prior done job or candidate has this SHA."""
    prior = session.scalar(
        select(DocumentJob)
        .where(DocumentJob.sha256 == sha, DocumentJob.status == "done")
        .order_by(DocumentJob.id.desc())
    )
    if prior is not None and prior.candidate_id:
        cand = session.get(ReviewCandidate, prior.candidate_id)
        if cand and (cand.extracted_text or "").strip():
            return (
                cand.title or "",
                cand.extracted_text or "",
                prior.storage_path,
            )
    # Also match review_candidates.content_hash when present
    cand2 = session.scalar(
        select(ReviewCandidate).where(ReviewCandidate.content_hash == sha).limit(1)
    )
    if cand2 and (cand2.extracted_text or "").strip():
        return (cand2.title or "", cand2.extracted_text or "", cand2.object_key)
    return None


def _download_pdf(
    url: str,
    *,
    resolve_dns: bool = True,
    max_bytes: int = WORKER_MAX_PDF_BYTES,
    timeout: float = 60.0,
) -> tuple[bytes, str]:
    """Download PDF with L1-style SSRF: no auto-follow; re-check every hop."""
    import os

    proxy = None
    for key in ("PROXY_URL", "HTTPS_PROXY", "HTTP_PROXY"):
        val = (os.environ.get(key) or "").strip()
        if val:
            proxy = val
            break
    kwargs: dict = {"follow_redirects": False, "timeout": timeout}
    if proxy:
        kwargs["proxy"] = proxy

    current = url
    with httpx.Client(**kwargs) as client:
        for _ in range(5):
            assert_safe_url(current, resolve_dns=resolve_dns)
            resp = client.get(current)
            if resp.is_redirect:
                loc = resp.headers.get("location")
                if not loc:
                    raise ValueError("redirect_no_location")
                current = str(httpx.URL(current).join(loc))
                continue
            assert_safe_url(str(resp.url), resolve_dns=resolve_dns)
            # Stream into a buffer with size guard (avoid OOM before cap)
            chunks: list[bytes] = []
            total = 0
            for chunk in resp.iter_bytes():
                if not chunk:
                    continue
                total += len(chunk)
                if total > max_bytes:
                    raise ValueError(f"pdf_too_large: {total} > {max_bytes}")
                chunks.append(chunk)
            body = b"".join(chunks) if chunks else (resp.content or b"")
            if len(body) > max_bytes:
                raise ValueError(f"pdf_too_large: {len(body)} > {max_bytes}")
            ctype = resp.headers.get("content-type", "")
            if not looks_like_pdf(str(resp.url), body, ctype) and body[:5] != b"%PDF-":
                raise ValueError("unsupported_content_type: not pdf")
            return body, str(resp.url)
        raise ValueError("too_many_redirects")



def process_pdf_queue(
    session: Session,
    blob: LocalBlobStore,
    *,
    limit: int = 5,
    resolve_dns: bool = True,
) -> dict[str, Any]:
    """Process up to ``limit`` queued PDF jobs. Commit per job."""
    if not pdf_queue_enabled():
        return {"processed": 0, "ok": 0, "failed": 0, "skipped": "flag_off"}

    reset = _reset_stale_processing(session)
    session.commit()

    jobs = list(
        session.scalars(
            select(DocumentJob)
            .where(DocumentJob.status == "queued")
            .order_by(DocumentJob.id.asc())
            .limit(limit)
        )
    )
    ok = 0
    failed = 0
    details: list[dict] = []

    for job in jobs:
        t0 = time.perf_counter()
        now = datetime.now(timezone.utc)
        job.status = "processing"
        job.attempts = int(job.attempts or 0) + 1
        job.updated_at = now
        session.commit()

        row = session.get(ReviewCandidate, job.candidate_id)
        info: dict[str, Any] = {"job_id": job.id, "candidate_id": job.candidate_id}

        try:
            body, final_url = _download_pdf(job.url, resolve_dns=resolve_dns)
            sha = hashlib.sha256(body).hexdigest()
            job.sha256 = sha
            job.content_length = len(body)
            job.url = final_url or job.url

            reused = _reuse_text_for_sha(session, sha)
            if reused is not None:
                title, text, storage = reused
                if storage:
                    job.storage_path = storage
                else:
                    key = blob.put_bytes(body, suffix=".pdf")
                    job.storage_path = key
            else:
                title, text = extract_pdf_text(body)
                key = blob.put_bytes(body, suffix=".pdf")
                job.storage_path = key

            if not (text or "").strip():
                raise ValueError("pdf_empty_extraction")

            if row is not None:
                row.object_key = job.storage_path
                row.content_hash = sha
                row.extracted_text = text[:50_000]
                if title:
                    row.title = title[:1024]
                row.status = "pending_review"
                row.fetch_status = "ok"
                row.fetch_error_type = None
                row.snippet = "fetched_via=pdf_queue;content_kind=pdf"
                row.updated_at = datetime.now(timezone.utc)

            job.status = "done"
            job.failure_reason = None
            job.updated_at = datetime.now(timezone.utc)
            session.commit()
            ok += 1
            info.update({"ok": True, "sha256": sha, "reused": reused is not None})
        except Exception as exc:  # noqa: BLE001
            err = str(exc)
            et = "pdf_empty_extraction" if "pdf_empty_extraction" in err else (
                "pdf_too_large" if err.startswith("pdf_too_large") else "pdf_queue_failed"
            )
            if err.startswith("unsupported_content_type"):
                et = "unsupported_content_type"
            job.status = "failed"
            job.failure_reason = et[:64]
            job.updated_at = datetime.now(timezone.utc)
            if row is not None:
                row.status = "fetch_failed"
                row.fetch_status = "failed"
                row.fetch_error_type = et[:64]
                row.snippet = f"fetch_error: {err}"[:2000]
                row.updated_at = datetime.now(timezone.utc)
            session.commit()
            failed += 1
            info.update({"ok": False, "error_type": et, "detail": err[:300]})

        info["elapsed_ms"] = int((time.perf_counter() - t0) * 1000)
        details.append(info)

    return {
        "processed": len(jobs),
        "ok": ok,
        "failed": failed,
        "stale_reset": reset,
        "details": details,
    }
