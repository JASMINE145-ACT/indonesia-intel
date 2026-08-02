from __future__ import annotations

import hashlib
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import ReviewCandidate
from dedup.url import normalize_url, url_hash
from fetch.circuit_breaker import HostCircuitBreaker, circuit_breaker_enabled
from fetch.content import FetchedPage, fetch_and_extract
from fetch.content_validity import (
    classify_exception,
    host_from_url,
    is_hard_fetch_error,
    is_retryable_fetch_error,
    is_social_host,
    page_is_invalid,
    should_escalate,
)
from fetch.jina_fallback import (
    JinaFetchError,
    fetch_and_extract_jina,
    jina_already_attempted,
    jina_eligible,
    mark_jina_attempted,
)
from fetch.l15 import fetch_and_extract_l15, fetch_l15_enabled, scrapling_l15_available
from fetch.scrapling_l2 import (
    FetchMode,
    domain_allowed,
    fetch_and_extract_scrapling,
    fetch_l2_enabled,
    scrapling_available,
)
from jobs.discovery_flags import fetch_jina_fallback_enabled, pdf_queue_enabled
from jobs.pdf_queue import enqueue_pdf_job
from sources.store import load_merged
from storage.blob import LocalBlobStore


def _l2_allowlist_and_modes() -> tuple[set[str], dict[str, FetchMode]]:
    reg = load_merged()
    domains: set[str] = set()
    modes: dict[str, FetchMode] = {}
    for src in reg.enabled():
        if not getattr(src, "fetch_l2", False):
            continue
        d = (src.domain or "").lower().removeprefix("www.")
        if not d:
            continue
        domains.add(d)
        mode = (src.fetch_l2_mode or "http").lower()
        if mode not in {"http", "dynamic", "stealthy"}:
            mode = "http"
        modes[d] = mode  # type: ignore[assignment]
    return domains, modes


def _mode_for_url(url: str, modes: dict[str, FetchMode]) -> FetchMode:
    host = (urlparse(url).hostname or "").lower().removeprefix("www.")
    if host in modes:
        return modes[host]
    for d, m in modes.items():
        if host == d or host.endswith("." + d):
            return m
    return "http"


def _fetch_url_for_row(row: ReviewCandidate) -> str:
    if (row.resolution_status or "") == "resolved" and (row.resolved_url or "").strip():
        return row.resolved_url.strip()
    return row.original_url


def _apply_page(
    session: Session,
    row: ReviewCandidate,
    blob: LocalBlobStore,
    page: FetchedPage,
    backend: str,
) -> bool:
    new_hash = url_hash(page.final_url)
    if new_hash != row.url_hash:
        other = session.scalar(
            select(ReviewCandidate).where(
                ReviewCandidate.url_hash == new_hash,
                ReviewCandidate.id != row.id,
            )
        )
        if other is not None:
            row.fetch_status = "failed"
            row.fetch_error_type = "url_hash_collision"
            row.status = "ignored"
            row.updated_at = datetime.now(timezone.utc)
            return False
    suffix = getattr(page, "blob_suffix", None) or ".html"
    key = blob.put_bytes(page.html, suffix=suffix)
    row.object_key = key
    row.content_hash = hashlib.sha256(page.html).hexdigest()
    row.extracted_text = page.text[:50_000] if page.text else ""
    if page.title:
        row.title = page.title[:1024]
    row.canonical_url = normalize_url(page.final_url)
    row.url_hash = new_hash
    row.status = "pending_review"
    row.fetch_status = "ok"
    row.fetch_error_type = None
    if row.snippet and row.snippet.startswith("fetch_error:"):
        row.snippet = ""
    kind = getattr(page, "content_kind", "html")
    if kind == "pdf" and not (row.snippet or "").startswith("fetched_via="):
        row.snippet = (row.snippet or "")
        if not row.snippet:
            row.snippet = f"fetched_via={backend};content_kind=pdf"
        elif "content_kind=pdf" not in row.snippet:
            row.snippet = f"{row.snippet};content_kind=pdf"
    if kind == "jina_markdown":
        base = row.snippet or ""
        if "fetched_via=jina_reader" not in base:
            row.snippet = (
                f"{base};fetched_via=jina_reader;content_kind=jina_markdown"
                if base
                else "fetched_via=jina_reader;content_kind=jina_markdown"
            )
    elif (
        backend.startswith("l2:") or backend.startswith("l15:")
    ) and not row.snippet:
        row.snippet = f"fetched_via={backend}"
    row.updated_at = datetime.now(timezone.utc)
    return True


def _mark_fetch_failure(
    row: ReviewCandidate,
    *,
    error_type: str | None,
    last_exc: BaseException | None,
    soft_pending: bool,
) -> None:
    err = error_type or (classify_exception(last_exc) if last_exc else "unknown")
    row.fetch_status = "failed"
    row.fetch_error_type = err[:64]
    row.updated_at = datetime.now(timezone.utc)
    if soft_pending and not is_hard_fetch_error(err):
        row.status = "pending_review"
        if row.snippet and row.snippet.startswith("fetch_error:"):
            row.snippet = ""
    else:
        row.status = "fetch_failed"
        if err == "circuit_open":
            # Avoid "fetch_error: None"
            if not row.snippet or row.snippet.startswith("fetch_error:"):
                row.snippet = "fetch_error: circuit_open"
        elif not row.snippet or row.snippet.startswith("fetch_error:"):
            if last_exc is not None:
                row.snippet = f"fetch_error: {last_exc}"[:2000]
            else:
                row.snippet = f"fetch_error: {err}"[:2000]


def _selected_level(backend: str) -> str | None:
    if backend.startswith("l2:"):
        return "l2"
    if backend.startswith("l15:"):
        return "l15"
    if backend == "jina_reader":
        return "jina"
    if backend == "l1":
        return "l1"
    return None


def _maybe_write_diagnostics(run_id: str | None, details: list[dict]) -> None:
    if not run_id or not details:
        return
    if os_environ_flag_off("INTEL_FETCH_DIAG_JSONL"):
        return
    try:
        root = Path(__file__).resolve().parents[1] / "evidence"
        root.mkdir(parents=True, exist_ok=True)
        path = root / f"fetch-diagnostics-{run_id}.jsonl"
        import json

        with path.open("a", encoding="utf-8") as fh:
            for row in details:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001
        pass


def os_environ_flag_off(name: str) -> bool:
    import os

    if name not in os.environ:
        return False
    return os.environ.get(name, "1").strip().lower() in {"0", "false", "no", "off"}


def fetch_discovered_candidates(
    session: Session,
    blob: LocalBlobStore,
    *,
    limit: int = 50,
    resolve_dns: bool = True,
    html_overrides: dict[str, bytes] | None = None,
    html_status_overrides: dict[str, int] | None = None,
    enable_l2: bool | None = None,
    enable_l15: bool | None = None,
    enable_jina: bool | None = None,
    run_id: str | None = None,
    retry_failed: bool = False,
) -> dict:
    """discovered → fetch → pending_review | fetch_failed.

    Ladder: social stub → L1 httpx → L1.5 curl_cffi → optional L2 Scrapling.
    """
    soft_pending = bool(getattr(settings, "fetch_soft_pending_enabled", True))
    if retry_failed:
        q = select(ReviewCandidate).where(
            or_(
                ReviewCandidate.status == "discovered",
                and_(
                    ReviewCandidate.status == "pending_review",
                    ReviewCandidate.fetch_status == "failed",
                ),
                and_(
                    ReviewCandidate.status == "fetch_failed",
                    ReviewCandidate.fetch_error_type == "circuit_open",
                ),
            )
        )
    else:
        q = select(ReviewCandidate).where(ReviewCandidate.status == "discovered")
    if run_id:
        q = q.where(ReviewCandidate.run_id == run_id)
    rows = list(session.scalars(q.limit(limit)))
    if retry_failed:
        filtered: list[ReviewCandidate] = []
        for row in rows:
            if row.status == "discovered":
                filtered.append(row)
            elif is_retryable_fetch_error(row.fetch_error_type):
                filtered.append(row)
        rows = filtered[:limit]

    ok = 0
    failed = 0
    pdf_queued = 0
    l2_used = 0
    l15_used = 0
    jina_used = 0
    overrides = html_overrides or {}
    status_overrides = html_status_overrides or {}
    use_l2 = fetch_l2_enabled() if enable_l2 is None else enable_l2
    use_l15 = fetch_l15_enabled() if enable_l15 is None else enable_l15
    use_jina = (
        fetch_jina_fallback_enabled() if enable_jina is None else enable_jina
    )
    allowlist, modes = _l2_allowlist_and_modes() if use_l2 else (set(), {})
    breaker = HostCircuitBreaker(threshold=3) if circuit_breaker_enabled() else None
    details: list[dict] = []
    gnews_budget = [0]

    for row in rows:
        try:
            from jobs.adapters.gnews_resolve import (
                apply_resolve_to_candidate,
                is_google_news_url,
            )

            if is_google_news_url(row.original_url or "") and (
                row.resolution_status or ""
            ) in {"pending", "not_required", ""}:
                apply_resolve_to_candidate(
                    session, row, max_budget=20, budget_used=gnews_budget
                )
        except Exception:  # noqa: BLE001
            pass

        url = _fetch_url_for_row(row)
        host = host_from_url(url)
        override = (
            overrides.get(url)
            or overrides.get(row.original_url)
            or overrides.get(row.canonical_url)
            or (overrides.get(row.resolved_url) if row.resolved_url else None)
        )
        status_ov = (
            status_overrides.get(url)
            or status_overrides.get(row.original_url or "")
            or status_overrides.get(row.canonical_url or "")
        )

        page: FetchedPage | None = None
        backend = "l1"
        last_exc: BaseException | None = None
        l1_info: dict = {"ok": False, "error_type": None, "fetcher": "httpx"}
        l15_info: dict = {"attempted": False, "ok": False, "fetcher": "curl_cffi"}
        l2_info: dict = {"attempted": False, "ok": False, "mode": None}
        jina_info: dict = {"attempted": False, "ok": False, "fetcher": "jina_reader"}
        t0 = time.perf_counter()

        # Social stub — no network escalate
        if is_social_host(url):
            _mark_fetch_failure(
                row,
                error_type="social_unsupported",
                last_exc=None,
                soft_pending=soft_pending,
            )
            failed += 1
            details.append(
                {
                    "candidate_id": row.id,
                    "url": url,
                    "domain": host,
                    "l1": {"ok": False, "error_type": "social_unsupported"},
                    "l15": l15_info,
                    "l2": l2_info,
                    "jina": jina_info,
                    "final": {
                        "ok": False,
                        "selected_level": None,
                        "fetch_status": row.fetch_status,
                        "status": row.status,
                        "error_type": "social_unsupported",
                    },
                }
            )
            continue

        if breaker and breaker.is_open(host):
            _mark_fetch_failure(
                row,
                error_type="circuit_open",
                last_exc=None,
                soft_pending=False,
            )
            failed += 1
            details.append(
                {
                    "candidate_id": row.id,
                    "url": url,
                    "domain": host,
                    "l1": {"ok": False, "error_type": "circuit_open"},
                    "l15": l15_info,
                    "l2": l2_info,
                    "jina": jina_info,
                    "final": {
                        "ok": False,
                        "selected_level": None,
                        "fetch_status": row.fetch_status,
                        "status": row.status,
                        "error_type": "circuit_open",
                    },
                }
            )
            continue

        err_type: str | None = None
        try:
            page = fetch_and_extract(
                url,
                resolve_dns=resolve_dns,
                html_override=override,
                status_code=status_ov,
            )
            verdict = page_is_invalid(page)
            if not verdict.ok:
                err_type = verdict.error_type
                l1_info = {
                    "ok": False,
                    "error_type": verdict.error_type,
                    "block_marker": verdict.block_marker,
                    "detail": verdict.detail,
                    "fetcher": "httpx",
                    "status_code": getattr(page, "status_code", None),
                }
                page = None
            else:
                l1_info = {
                    "ok": True,
                    "error_type": None,
                    "fetcher": "httpx",
                    "status_code": getattr(page, "status_code", None),
                }
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            page = None
            err_type = classify_exception(exc)
            l1_info = {
                "ok": False,
                "error_type": err_type,
                "detail": str(exc)[:300],
                "fetcher": "httpx",
                "exception_class": type(exc).__name__,
            }

        # L1.5
        if page is None and use_l15 and override is None and scrapling_l15_available():
            if should_escalate(err_type) and not (breaker and breaker.is_open(host)):
                l15_info["attempted"] = True
                t1 = time.perf_counter()
                try:
                    page = fetch_and_extract_l15(url, resolve_dns=resolve_dns)
                    v15 = page_is_invalid(page)
                    if not v15.ok:
                        err_type = v15.error_type
                        last_exc = RuntimeError(
                            f"L15 invalid content ({v15.error_type}): {v15.detail}"
                        )
                        page = None
                        l15_info.update(
                            {
                                "ok": False,
                                "error_type": v15.error_type,
                                "block_marker": v15.block_marker,
                                "elapsed_ms": int((time.perf_counter() - t1) * 1000),
                            }
                        )
                        if breaker:
                            breaker.record_escalation_failure(host)
                    else:
                        backend = "l15:curl_cffi"
                        l15_used += 1
                        last_exc = None
                        err_type = None
                        l15_info.update(
                            {
                                "ok": True,
                                "elapsed_ms": int((time.perf_counter() - t1) * 1000),
                            }
                        )
                except Exception as l15exc:  # noqa: BLE001
                    last_exc = l15exc
                    page = None
                    err_type = classify_exception(l15exc)
                    l15_info.update(
                        {
                            "ok": False,
                            "error_type": err_type,
                            "detail": str(l15exc)[:300],
                            "exception_class": type(l15exc).__name__,
                            "elapsed_ms": int((time.perf_counter() - t1) * 1000),
                        }
                    )
                    if breaker:
                        breaker.record_escalation_failure(host)

        # L2 (allowlist)
        if page is None and use_l2 and override is None and scrapling_available():
            if (
                should_escalate(err_type)
                and domain_allowed(url, allowlist)
                and not (breaker and breaker.is_open(host))
            ):
                mode = _mode_for_url(url, modes)
                # Skip duplicate Fetcher if L1.5 already tried
                if mode == "http" and l15_info.get("attempted"):
                    l2_info = {
                        "attempted": False,
                        "ok": False,
                        "mode": mode,
                        "skipped": "l15_already_ran_fetcher",
                    }
                else:
                    l2_info = {"attempted": True, "ok": False, "mode": mode}
                    try:
                        page = fetch_and_extract_scrapling(
                            url,
                            mode=mode,
                            resolve_dns=resolve_dns,
                            allow_browser=mode in {"dynamic", "stealthy"},
                            allowlist=allowlist,
                        )
                        v2 = page_is_invalid(page)
                        if not v2.ok:
                            err_type = v2.error_type
                            last_exc = RuntimeError(
                                f"L2 invalid content ({v2.error_type}): {v2.detail}"
                            )
                            page = None
                            l2_info.update(
                                {
                                    "ok": False,
                                    "error_type": v2.error_type,
                                    "block_marker": v2.block_marker,
                                }
                            )
                            if breaker:
                                breaker.record_escalation_failure(host)
                        else:
                            backend = f"l2:{mode}"
                            l2_used += 1
                            last_exc = None
                            err_type = None
                            l2_info["ok"] = True
                    except Exception as l2exc:  # noqa: BLE001
                        last_exc = l2exc
                        page = None
                        err_type = classify_exception(l2exc)
                        l2_info.update(
                            {
                                "ok": False,
                                "error_type": err_type,
                                "detail": str(l2exc)[:300],
                            }
                        )
                        if breaker:
                            breaker.record_escalation_failure(host)

        # Jina Reader fail-only (after L1 → L1.5 → L2)
        if (
            page is None
            and use_jina
            and override is None
            and jina_eligible(err_type)
            and not jina_already_attempted(row)
        ):
            jina_info["attempted"] = True
            mark_jina_attempted(row)
            t_j = time.perf_counter()
            try:
                page = fetch_and_extract_jina(url, resolve_dns=resolve_dns)
                backend = "jina_reader"
                jina_used += 1
                last_exc = None
                err_type = None
                jina_info.update(
                    {
                        "ok": True,
                        "elapsed_ms": int((time.perf_counter() - t_j) * 1000),
                    }
                )
            except JinaFetchError as jexc:
                last_exc = jexc
                page = None
                err_type = jexc.error_type
                jina_info.update(
                    {
                        "ok": False,
                        "error_type": jexc.error_type,
                        "detail": (jexc.detail or str(jexc))[:300],
                        "elapsed_ms": int((time.perf_counter() - t_j) * 1000),
                    }
                )
            except Exception as jexc:  # noqa: BLE001
                last_exc = jexc
                page = None
                err_type = "jina_failed"
                jina_info.update(
                    {
                        "ok": False,
                        "error_type": "jina_failed",
                        "detail": str(jexc)[:300],
                        "elapsed_ms": int((time.perf_counter() - t_j) * 1000),
                    }
                )

        if page is not None:
            applied = False
            try:
                with session.begin_nested():
                    applied = _apply_page(session, row, blob, page, backend)
                    session.flush()
            except Exception as flush_exc:  # noqa: BLE001
                from sqlalchemy.exc import IntegrityError

                if isinstance(flush_exc, IntegrityError) or "UNIQUE" in str(
                    flush_exc
                ).upper():
                    row.fetch_status = "failed"
                    row.fetch_error_type = "url_hash_collision"
                    row.status = "ignored"
                    row.updated_at = datetime.now(timezone.utc)
                    applied = False
                else:
                    raise
            if applied:
                ok += 1
                selected = _selected_level(backend)
                if breaker:
                    breaker.record_success(host)
            else:
                failed += 1
                selected = None
        else:
            # If circuit just opened after this URL's failures, mark remaining semantics
            final_err = err_type or (
                classify_exception(last_exc) if last_exc else "unknown"
            )
            if final_err == "pdf_too_large" and pdf_queue_enabled():
                enqueue_pdf_job(session, row, url=url)
                pdf_queued += 1
                selected = None
            else:
                _mark_fetch_failure(
                    row,
                    error_type=str(final_err) if final_err else None,
                    last_exc=last_exc,
                    soft_pending=soft_pending,
                )
                failed += 1
                selected = None

        details.append(
            {
                "candidate_id": row.id,
                "url": url,
                "domain": host,
                "elapsed_ms": int((time.perf_counter() - t0) * 1000),
                "l1": l1_info,
                "l15": l15_info,
                "l2": l2_info,
                "jina": jina_info,
                "final": {
                    "ok": bool(selected),
                    "selected_level": selected,
                    "fetch_status": row.fetch_status,
                    "status": row.status,
                    "error_type": row.fetch_error_type,
                },
            }
        )

    session.commit()
    _maybe_write_diagnostics(run_id, details)
    # Surface full open URLs for failed rows so agents/UI can hand them to humans.
    from jobs.ops_dashboard import UNFETCHED_USER_HINT, best_open_url, is_unfetched

    unfetched_for_user = [
        {
            "candidate_id": row.id,
            "title": row.title,
            "open_url": best_open_url(row),
            "fetch_error_type": row.fetch_error_type,
            "status": row.status,
            "fetch_status": row.fetch_status,
            "user_hint": UNFETCHED_USER_HINT,
        }
        for row in rows
        if is_unfetched(row)
    ]
    return {
        "fetched": ok,
        "failed": failed,
        "pdf_queued": pdf_queued,
        "total": len(rows),
        "l15_used": l15_used,
        "l2_used": l2_used,
        "jina_used": jina_used,
        "l15_enabled": use_l15,
        "l2_enabled": use_l2,
        "jina_enabled": use_jina,
        "details": details,
        "unfetched_for_user": unfetched_for_user,
    }
