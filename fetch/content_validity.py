"""Content-level validity checks — block / challenge / JS shell detection.

Contracts: WANd.INTEL.LIVE_SMOKE.001 / FETCH_L2_SCRAPLING.001 /
FETCH_ERROR_TAXONOMY.001 / FETCH_HTTP_STATUS.001 / FETCH_SOCIAL_STUB.001
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

BLOCK_MARKERS: tuple[tuple[str, str, str], ...] = (
    ("sorry, you have been blocked", "waf_blocked", "any"),
    ("just a moment", "cloudflare_challenge", "title"),
    ("javascript is disabled", "javascript_shell", "title"),
    ("enable javascript and cookies", "javascript_shell", "html"),
    ("access denied", "waf_blocked", "title"),
    ("attention required", "cloudflare_challenge", "title"),
    ("checking your browser", "cloudflare_challenge", "html"),
    ("cf-chl-", "cloudflare_challenge", "html"),
    ("please enable javascript", "javascript_shell", "html"),
    ("verify you are human", "cloudflare_challenge", "html"),
)

NO_ESCALATE_ERROR_TYPES = frozenset(
    {
        "ssrf",
        "dns_failure",
        "unsafe_url",
        "robots_disallowed",
        "certificate_failure",
        "terminal_not_found",
        "terminal_gone",
        "social_unsupported",
        "circuit_open",
        "pdf_too_large",
        "response_too_large",
        "unsupported_content_type",
        "too_many_redirects",
        "redirect_no_location",
        "url_hash_collision",
        "jina_rate_limited",
        "jina_fake_body",
        "jina_failed",
    }
)

HARD_FETCH_ERROR_TYPES = frozenset(
    {
        "ssrf",
        "dns_failure",
        "unsafe_url",
        "robots_disallowed",
        "terminal_not_found",
        "terminal_gone",
        "circuit_open",
        "pdf_too_large",
        "response_too_large",
        "unsupported_content_type",
        "too_many_redirects",
        "redirect_no_location",
        "jina_rate_limited",
        "jina_fake_body",
        "jina_failed",
    }
)

RETRYABLE_FETCH_ERROR_TYPES = frozenset(
    {
        "connect_timeout",
        "read_timeout",
        "ssl_handshake_timeout",
        "certificate_failure",
        "tls_disconnect",  # legacy — keep forever
        "remote_protocol_error",
        "connection_reset",
        "read_error",
        "proxy_error",
        "http_401",
        "http_403",
        "http_429",
        "empty_extraction",
        "extraction_failed",
        "waf_blocked",
        "cloudflare_challenge",
        "javascript_shell",
        "insufficient_content",
        "circuit_open",  # not soft-pending; retry_failed may requeue
    }
)


@dataclass(frozen=True)
class ContentVerdict:
    ok: bool
    error_type: str | None = None
    block_marker: str | None = None
    detail: str = ""


def http_reclass_enabled() -> bool:
    if "INTEL_FETCH_HTTP_RECLASS" in os.environ:
        raw = os.environ.get("INTEL_FETCH_HTTP_RECLASS", "1").strip().lower()
        return raw not in {"0", "false", "no", "off"}
    try:
        from app.config import settings

        return bool(getattr(settings, "fetch_http_reclass_enabled", True))
    except Exception:  # noqa: BLE001
        return True


def host_from_url(url: str) -> str:
    return (urlparse(url).hostname or "").lower().removeprefix("www.")


def is_social_host(url: str) -> bool:
    host = host_from_url(url)
    if not host:
        return False
    return any(
        host == d or host.endswith("." + d)
        for d in ("instagram.com", "facebook.com", "fb.com")
    )


def find_block_marker(
    *,
    title: str | None = None,
    text: str | None = None,
    final_url: str | None = None,
    html_snippet: bytes | str | None = None,
) -> tuple[str, str] | None:
    title_l = (title or "").lower()
    text_l = (text or "").lower()
    url_l = (final_url or "").lower()
    if isinstance(html_snippet, bytes):
        html_l = html_snippet[:8000].decode("utf-8", errors="replace").lower()
    elif html_snippet is not None:
        html_l = str(html_snippet)[:8000].lower()
    else:
        html_l = ""

    for marker, err, scope in BLOCK_MARKERS:
        if scope == "title":
            hay = f"{title_l}\n{url_l}"
        elif scope == "html":
            hay = f"{title_l}\n{html_l}"
        else:
            hay = f"{title_l}\n{text_l}\n{url_l}\n{html_l}"
        if marker in hay:
            return marker, err
    return None


def classify_exception(exc: BaseException) -> str:
    name = type(exc).__name__
    msg = str(exc)
    msg_l = msg.lower()

    if name == "ValueError":
        if msg_l.startswith("pdf_too_large"):
            return "pdf_too_large"
        if msg_l.startswith("response_too_large") or "response too large" in msg_l:
            return "response_too_large"
        if "unsupported content-type" in msg_l:
            return "unsupported_content_type"
        if "too many redirects" in msg_l:
            return "too_many_redirects"
        if "redirect without location" in msg_l:
            return "redirect_no_location"

    if "certificate verify failed" in msg_l or "unable to get local issuer" in msg_l:
        return "certificate_failure"
    if "dns failed" in msg_l or (name == "UnsafeURLError" and "dns" in msg_l):
        return "dns_failure"
    if name == "UnsafeURLError" or "unsafe url" in msg_l:
        return "ssrf"
    if "handshake" in msg_l and "timeout" in msg_l:
        return "ssl_handshake_timeout"
    if "connecttimeout" in name.lower() or ("timed out" in msg_l and "connect" in msg_l):
        return "connect_timeout"
    if "readtimeout" in name.lower():
        return "read_timeout"
    if "proxy" in name.lower() or "proxy error" in msg_l:
        return "proxy_error"
    if name == "RemoteProtocolError" or "remote protocol" in msg_l:
        return "remote_protocol_error"
    if "connection reset" in msg_l or "connection aborted" in msg_l or "broken pipe" in msg_l:
        return "connection_reset"
    if name in {"ReadError", "WriteError"}:
        return "read_error"
    if "unexpected_eof" in msg_l or "server disconnected" in msg_l:
        return "tls_disconnect"

    if name == "HTTPStatusError" or "status code" in msg_l:
        for code, label in (
            (401, "http_401"),
            (403, "http_403"),
            (404, "terminal_not_found"),
            (410, "terminal_gone"),
            (429, "http_429"),
        ):
            if f"status code {code}" in msg_l:
                return label
    if "403 forbidden" in msg_l or msg_l.strip() in {"403", "http 403"}:
        return "http_403"
    if "429" in msg_l and ("too many" in msg_l or "rate" in msg_l):
        return "http_429"

    return f"exception:{name}"


def is_hard_fetch_error(error_type: str | None) -> bool:
    if not error_type:
        return False
    if error_type in HARD_FETCH_ERROR_TYPES:
        return True
    return error_type.startswith("exception:UnsafeURL")


def is_retryable_fetch_error(error_type: str | None) -> bool:
    if not error_type:
        return False
    if error_type == "circuit_open":
        return True
    if is_hard_fetch_error(error_type):
        return False
    if error_type in RETRYABLE_FETCH_ERROR_TYPES:
        return True
    return error_type.startswith("exception:")


def should_escalate(error_type: str | None) -> bool:
    if not error_type:
        return False
    if error_type in NO_ESCALATE_ERROR_TYPES:
        return False
    return True


def error_type_from_status(status_code: int | None) -> str | None:
    if status_code is None:
        return None
    if status_code == 404:
        return "terminal_not_found"
    if status_code == 410:
        return "terminal_gone"
    if status_code == 401:
        return "http_401"
    if status_code == 403:
        return "http_403"
    if status_code == 429:
        return "http_429"
    if status_code >= 400:
        return f"http_{status_code}"
    return None


def assess_extracted_page(
    *,
    title: str | None = None,
    text: str | None = None,
    html: bytes | str | None = None,
    final_url: str | None = None,
    min_text_len: int = 40,
    status_code: int | None = None,
) -> ContentVerdict:
    if http_reclass_enabled():
        status_err = error_type_from_status(status_code)
        if status_err:
            return ContentVerdict(
                ok=False,
                error_type=status_err,
                detail=f"http_status={status_code}",
            )

    hit = find_block_marker(
        title=title, text=text, final_url=final_url, html_snippet=html
    )
    if hit:
        marker, err = hit
        return ContentVerdict(
            ok=False,
            error_type=err,
            block_marker=marker,
            detail=f"block marker: {marker}",
        )

    title_s = (title or "").strip()
    text_s = (text or "").strip()

    if len(text_s) < 20 and not title_s:
        return ContentVerdict(
            ok=False,
            error_type="empty_extraction",
            detail=f"title empty and text_len={len(text_s)}",
        )
    if len(text_s) < 20 and title_s:
        return ContentVerdict(
            ok=False,
            error_type="empty_extraction",
            detail=f"title={title_s[:60]!r} text_len={len(text_s)}",
        )
    if len(text_s) < min_text_len and not title_s:
        return ContentVerdict(
            ok=True,
            detail=f"title empty text_len={len(text_s)} (accepted)",
        )
    return ContentVerdict(ok=True, detail=f"title_len={len(title_s)} text_len={len(text_s)}")


def page_is_invalid(page: Any, *, min_text_len: int = 40) -> ContentVerdict:
    return assess_extracted_page(
        title=getattr(page, "title", None),
        text=getattr(page, "text", None),
        html=getattr(page, "html", None),
        final_url=getattr(page, "final_url", None),
        min_text_len=min_text_len,
        status_code=getattr(page, "status_code", None),
    )
