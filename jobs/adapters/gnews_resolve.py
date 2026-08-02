"""Google News URL resolver — WANd.INTEL.GNEWS_RESOLVE.001."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import ReviewCandidate
from dedup.url import url_hash
from fetch.ssrf import assert_safe_url
from jobs.adapters.common import same_registrable_domain
from jobs.discovery_flags import discovery_gnews_resolve_enabled
from sources.store import load_merged

GNEWS_HOSTS = ("news.google.com",)


def is_google_news_url(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return any(host == h or host.endswith("." + h) for h in GNEWS_HOSTS)


def resolve_google_news_url(
    url: str,
    *,
    timeout_s: float = 15.0,
) -> dict[str, Any]:
    """Return {status, resolved_url, error}. Never raises for decode failures."""
    if not is_google_news_url(url):
        return {"status": "not_required", "resolved_url": None, "error": None}
    if not discovery_gnews_resolve_enabled():
        return {"status": "failed", "resolved_url": None, "error": "gnews resolve disabled"}

    def _decode() -> Any:
        from googlenewsdecoder import gnewsdecoder

        return gnewsdecoder(url, interval=1)

    try:
        pool = ThreadPoolExecutor(max_workers=1)
        try:
            fut = pool.submit(_decode)
            try:
                result = fut.result(timeout=timeout_s)
            except FuturesTimeout:
                return {
                    "status": "failed",
                    "resolved_url": None,
                    "error": f"timeout after {timeout_s}s",
                }
        finally:
            pool.shutdown(wait=False, cancel_futures=True)
        if isinstance(result, dict) and result.get("status") and result.get("decoded_url"):
            decoded = str(result["decoded_url"]).strip()
            assert_safe_url(decoded, resolve_dns=True)
            return {"status": "resolved", "resolved_url": decoded, "error": None}
        msg = ""
        if isinstance(result, dict):
            msg = str(result.get("message") or result.get("error") or "decode failed")
        return {"status": "unresolved", "resolved_url": None, "error": msg[:200]}
    except ImportError:
        return {
            "status": "failed",
            "resolved_url": None,
            "error": "googlenewsdecoder not installed",
        }
    except Exception as exc:  # noqa: BLE001
        return {"status": "failed", "resolved_url": None, "error": str(exc)[:200]}


def _find_duplicate_of_resolved(
    session: Session, row: ReviewCandidate, resolved: str
) -> ReviewCandidate | None:
    h = url_hash(resolved)
    return session.scalar(
        select(ReviewCandidate).where(
            ReviewCandidate.id != row.id,
            or_(
                ReviewCandidate.url_hash == h,
                ReviewCandidate.resolved_url == resolved,
            ),
        )
    )


def apply_resolve_to_candidate(
    session: Session,
    row: ReviewCandidate,
    *,
    max_budget: int = 20,
    budget_used: list[int] | None = None,
    timeout_s: float = 15.0,
) -> None:
    """Mutate row resolution fields; may mark ignored if duplicate of resolved URL."""
    if not is_google_news_url(row.original_url or ""):
        if not row.resolution_status or row.resolution_status == "pending":
            row.resolution_status = "not_required"
        return
    used = budget_used if budget_used is not None else [0]
    if used[0] >= max_budget:
        row.resolution_status = "pending"
        return
    used[0] += 1
    out = resolve_google_news_url(row.original_url or "", timeout_s=timeout_s)
    row.resolution_status = out["status"]
    if out.get("resolved_url"):
        decoded = out["resolved_url"]
        # D11: same registrable domain when prefer source_id is set
        if row.source_id:
            try:
                src = load_merged().get(row.source_id)
                if src and not same_registrable_domain(decoded, src.domain):
                    row.resolution_status = "failed"
                    raw = {}
                    try:
                        raw = json.loads(row.raw_search_json or "{}")
                    except json.JSONDecodeError:
                        pass
                    raw["resolve_error"] = "resolved_url_domain_mismatch"
                    row.raw_search_json = json.dumps(raw, ensure_ascii=False)
                    return
            except Exception:  # noqa: BLE001
                pass
        row.resolved_url = decoded
        other = _find_duplicate_of_resolved(session, row, decoded)
        if other is not None:
            row.status = "ignored"
            try:
                raw = json.loads(row.raw_search_json or "{}")
            except json.JSONDecodeError:
                raw = {}
            raw["ignore_reason"] = "duplicate_of_resolved"
            raw["duplicate_of_candidate_id"] = other.id
            row.raw_search_json = json.dumps(raw, ensure_ascii=False)
    elif out.get("error"):
        try:
            raw = json.loads(row.raw_search_json or "{}")
        except json.JSONDecodeError:
            raw = {}
        raw["resolve_error"] = out["error"]
        row.raw_search_json = json.dumps(raw, ensure_ascii=False)
