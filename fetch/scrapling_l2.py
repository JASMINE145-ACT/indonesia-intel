"""Scrapling L2 fetch — optional escalation behind SSRF + allowlist.

Contract: WANd.INTEL.FETCH_L2_SCRAPLING.001
"""
from __future__ import annotations

import os
from typing import Any, Callable, Literal
from urllib.parse import urlparse

import trafilatura

from fetch.content import DEFAULT_MAX_BYTES, FetchedPage
from fetch.ssrf import assert_safe_url

FetchMode = Literal["http", "dynamic", "stealthy"]

# Soft-import hooks (tests may monkeypatch).
_fetcher_get: Callable[..., Any] | None = None
_dynamic_fetch: Callable[..., Any] | None = None
_stealthy_fetch: Callable[..., Any] | None = None
_import_error: str | None = None


def scrapling_available() -> bool:
    """True if scrapling fetchers can be imported (or test hooks injected)."""
    if _fetcher_get is not None or _dynamic_fetch is not None or _stealthy_fetch is not None:
        return True
    try:
        _ensure_scrapling_loaded()
        return True
    except ImportError:
        return False


def _ensure_scrapling_loaded() -> None:
    global _fetcher_get, _dynamic_fetch, _stealthy_fetch, _import_error
    if _fetcher_get is not None:
        return
    try:
        from scrapling.fetchers import DynamicFetcher, Fetcher, StealthyFetcher

        _fetcher_get = Fetcher.get
        _dynamic_fetch = DynamicFetcher.fetch
        _stealthy_fetch = StealthyFetcher.fetch
        _import_error = None
    except ImportError as exc:
        _import_error = str(exc)
        raise ImportError(
            "Scrapling L2 unavailable. Install: pip install 'scrapling[fetchers]' "
            "&& scrapling install"
        ) from exc


def fetch_l2_enabled() -> bool:
    """Env INTEL_FETCH_L2 wins; else settings.fetch_l2."""
    if "INTEL_FETCH_L2" in os.environ:
        raw = os.environ.get("INTEL_FETCH_L2", "1").strip().lower()
        return raw not in {"0", "false", "no", "off"}
    try:
        from app.config import settings

        return bool(settings.fetch_l2)
    except Exception:  # noqa: BLE001
        return True


def host_from_url(url: str) -> str:
    host = (urlparse(url).hostname or "").lower().removeprefix("www.")
    return host


def domain_allowed(url: str, allowlist: set[str] | frozenset[str] | list[str]) -> bool:
    """Match URL host against registry domains (suffix match)."""
    host = host_from_url(url)
    if not host:
        return False
    allowed = {d.lower().removeprefix("www.").strip() for d in allowlist if d}
    if host in allowed:
        return True
    return any(host == d or host.endswith("." + d) for d in allowed)


def _response_html_bytes(resp: Any, *, max_bytes: int) -> tuple[bytes, str]:
    """Normalize Scrapling response → (html bytes, final_url)."""
    final = (
        getattr(resp, "url", None)
        or getattr(resp, "final_url", None)
        or getattr(resp, "request_url", None)
        or ""
    )
    if hasattr(final, "__str__") and not isinstance(final, str):
        final = str(final)

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
        raise ValueError(f"response too large: {len(html)} > {max_bytes}")
    return html, final or ""


def _extract_page(url: str, html: bytes, final_url: str) -> FetchedPage:
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
    )


def l2_eligible_error(exc: BaseException) -> bool:
    """Heuristic: L1 failures worth escalating to Scrapling."""
    from fetch.ssrf import UnsafeURLError

    if isinstance(exc, (PermissionError, UnsafeURLError)):
        return False
    name = type(exc).__name__
    msg = str(exc).lower()
    if "dns failed" in msg or "certificate verify failed" in msg:
        return False  # out-of-scope for Scrapling
    if name in {
        "ConnectError",
        "RemoteProtocolError",
        "ReadTimeout",
        "ConnectTimeout",
        "HTTPStatusError",
    }:
        return True
    if "403" in msg or "cloudflare" in msg or "just a moment" in msg:
        return True
    if "unsupported content-type" in msg:
        return True
    if "server disconnected" in msg or "unexpected_eof" in msg:
        return True
    # Typed escalate is owned by content_validity.should_escalate (orchestrator).
    return False


def fetch_and_extract_scrapling(
    url: str,
    *,
    mode: FetchMode = "http",
    resolve_dns: bool = True,
    timeout: float = 30.0,
    max_bytes: int = DEFAULT_MAX_BYTES,
    allow_browser: bool = False,
    allowlist: set[str] | frozenset[str] | list[str] | None = None,
    html_override: bytes | None = None,
) -> FetchedPage:
    """L2 fetch via Scrapling. Browser modes require allow_browser + allowlist hit."""
    assert_safe_url(url, resolve_dns=resolve_dns)

    # Fail-closed: missing allowlist ⇒ deny
    effective_allowlist: set[str] | frozenset[str] | list[str] = (
        allowlist if allowlist is not None else ()
    )
    if not domain_allowed(url, effective_allowlist):
        raise PermissionError(f"domain not on L2 allowlist: {host_from_url(url)}")

    if mode in {"dynamic", "stealthy"} and not allow_browser:
        raise PermissionError("browser L2 modes require allow_browser=True")

    if html_override is not None:
        return _extract_page(url, html_override, url)

    _ensure_scrapling_loaded()
    assert _fetcher_get is not None

    if mode == "http":
        # Fail-closed: must disable redirects (SSRF parity with L1 / L1.5).
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
                "l2_redirect_control_unsupported: Scrapling Fetcher does not accept "
                "allow_redirects/follow_redirects=False; refusing hop (fail-closed)"
            ) from last_type_err
    elif mode == "dynamic":
        assert _dynamic_fetch is not None
        resp = _dynamic_fetch(url, headless=True, network_idle=True, timeout=int(timeout * 1000))
    elif mode == "stealthy":
        assert _stealthy_fetch is not None
        resp = _stealthy_fetch(
            url,
            headless=True,
            network_idle=True,
            solve_cloudflare=True,
            timeout=int(timeout * 1000),
        )
    else:
        raise ValueError(f"unknown L2 mode: {mode}")

    html, final_url = _response_html_bytes(resp, max_bytes=max_bytes)
    if final_url:
        assert_safe_url(final_url, resolve_dns=resolve_dns)
    return _extract_page(url, html, final_url or url)
