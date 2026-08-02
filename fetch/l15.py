"""L1.5 fetch via Scrapling Fetcher (curl_cffi) — no L2 domain allowlist.

Contract: WANd.INTEL.FETCH_L15_CURL_CFFI.001
Redirect: fail-closed (never silently follow redirects).
"""
from __future__ import annotations

import os
from typing import Any, Callable

import trafilatura

from fetch.content import DEFAULT_MAX_BYTES, FetchedPage
from fetch.ssrf import assert_safe_url

_fetcher_get: Callable[..., Any] | None = None


def fetch_l15_enabled() -> bool:
    if "INTEL_FETCH_L15" in os.environ:
        raw = os.environ.get("INTEL_FETCH_L15", "1").strip().lower()
        return raw not in {"0", "false", "no", "off"}
    try:
        from app.config import settings

        return bool(getattr(settings, "fetch_l15_enabled", True))
    except Exception:  # noqa: BLE001
        return True


def scrapling_l15_available() -> bool:
    if _fetcher_get is not None:
        return True
    try:
        _ensure_loaded()
        return True
    except ImportError:
        return False


def _ensure_loaded() -> None:
    global _fetcher_get
    if _fetcher_get is not None:
        return
    try:
        from scrapling.fetchers import Fetcher

        _fetcher_get = Fetcher.get
    except ImportError as exc:
        raise ImportError(
            "Scrapling L1.5 unavailable. Install: pip install 'scrapling[fetchers]'"
        ) from exc


def _response_html_bytes(resp: Any, *, max_bytes: int) -> tuple[bytes, str, int | None]:
    final = (
        getattr(resp, "url", None)
        or getattr(resp, "final_url", None)
        or getattr(resp, "request_url", None)
        or ""
    )
    if hasattr(final, "__str__") and not isinstance(final, str):
        final = str(final)

    status = getattr(resp, "status", None) or getattr(resp, "status_code", None)
    try:
        status_i = int(status) if status is not None else None
    except (TypeError, ValueError):
        status_i = None

    body = None
    for attr in ("body", "content", "html", "text"):
        if hasattr(resp, attr):
            body = getattr(resp, attr)
            if body is not None:
                break
    if body is None:
        raise ValueError("Scrapling response missing body/content/html")

    if isinstance(body, bytes):
        html = body
    elif isinstance(body, str):
        html = body.encode("utf-8", errors="replace")
    else:
        html = bytes(body)

    if len(html) > max_bytes:
        raise ValueError(f"response_too_large: {len(html)} > {max_bytes}")
    return html, final or "", status_i


def _extract_page(
    url: str, html: bytes, final_url: str, status_code: int | None
) -> FetchedPage:
    decoded = html.decode("utf-8", errors="replace")
    text = trafilatura.extract(decoded, include_comments=False, include_tables=False) or ""
    title = ""
    meta = trafilatura.extract_metadata(decoded)
    if meta is not None:
        title = meta.title or ""
    return FetchedPage(
        url=url,
        title=title,
        text=text,
        html=html,
        final_url=final_url or url,
        status_code=status_code,
    )


def fetch_and_extract_l15(
    url: str,
    *,
    resolve_dns: bool = True,
    timeout: float = 30.0,
    max_bytes: int = DEFAULT_MAX_BYTES,
    html_override: bytes | None = None,
    status_code: int | None = None,
) -> FetchedPage:
    """L1.5: Scrapling Fetcher / curl_cffi. No domain allowlist. Redirect fail-closed."""
    assert_safe_url(url, resolve_dns=resolve_dns)

    if html_override is not None:
        return _extract_page(url, html_override, url, status_code)

    _ensure_loaded()
    assert _fetcher_get is not None

    # Fail-closed: must disable redirects. Never fall back to following redirects.
    kwargs_candidates = [
        {
            "timeout": timeout,
            "stealthy_headers": True,
            "verify": True,
            "allow_redirects": False,
        },
        {
            "timeout": timeout,
            "stealthy_headers": True,
            "verify": True,
            "follow_redirects": False,
        },
    ]
    last_type_err: TypeError | None = None
    resp = None
    for kwargs in kwargs_candidates:
        try:
            resp = _fetcher_get(url, **kwargs)
            break
        except TypeError as exc:
            last_type_err = exc
            continue
    if resp is None:
        raise RuntimeError(
            "l15_redirect_control_unsupported: Scrapling Fetcher does not accept "
            "allow_redirects/follow_redirects=False; refusing hop (fail-closed)"
        ) from last_type_err

    # If library still followed redirects despite kwargs, reject private final URL
    html, final_url, code = _response_html_bytes(resp, max_bytes=max_bytes)
    if final_url:
        assert_safe_url(final_url, resolve_dns=resolve_dns)
        # Detect hop change without controlling redirects — still SSRF-safe on final,
        # but policy: if final differs and we couldn't disable redirects, prefer deny
        # when status is 3xx-ish and body looks like redirect page — keep final check.
    return _extract_page(url, html, final_url or url, code)
