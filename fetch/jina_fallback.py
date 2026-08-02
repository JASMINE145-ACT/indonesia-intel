"""Jina Reader fail-only fallback — WANd.INTEL.JINA_FETCH_FALLBACK.001."""

from __future__ import annotations

import json
import os
import re
from typing import Any

import httpx

from fetch.content import FetchedPage
from fetch.content_validity import find_block_marker
from fetch.ssrf import UnsafeURLError, assert_safe_url

JINA_READER_PREFIX = "https://r.jina.ai/"

# Eligible typed reasons only (PRD JINA_NO excludes 401/social/pdf/ssrf/robots).
JINA_ELIGIBLE_ERROR_TYPES = frozenset(
    {
        "empty_extraction",
        "extraction_failed",
        "waf_blocked",
        "cloudflare_challenge",
        "javascript_shell",
        "insufficient_content",
        "http_403",
        "http_429",
        "read_timeout",
        "connect_timeout",
        "tls_disconnect",
        "ssl_handshake_timeout",
        "connection_reset",
        "remote_protocol_error",
        "read_error",
        "proxy_error",
    }
)

JINA_FAKE_MARKERS: tuple[tuple[str, str], ...] = (
    ("page not found", "jina_fake_body"),
    ("404 not found", "jina_fake_body"),
    ("access denied", "jina_fake_body"),
    ("captcha", "jina_fake_body"),
    ("verify you are human", "jina_fake_body"),
    ("just a moment", "jina_fake_body"),
    ("enable javascript", "jina_fake_body"),
)


class JinaFetchError(RuntimeError):
    """Typed Jina failure; ``error_type`` is a taxonomy code."""

    def __init__(self, error_type: str, detail: str = "") -> None:
        super().__init__(detail or error_type)
        self.error_type = error_type
        self.detail = detail


def jina_eligible(error_type: str | None) -> bool:
    if not error_type:
        return False
    return error_type in JINA_ELIGIBLE_ERROR_TYPES


def _api_key() -> str:
    for key in ("JINA_API_KEY", "INTEL_JINA_API_KEY"):
        val = (os.environ.get(key) or "").strip()
        if val:
            return val
    try:
        from app.config import settings

        return (getattr(settings, "jina_api_key", None) or "").strip()
    except Exception:  # noqa: BLE001
        return ""


def raw_meta(row: Any) -> dict:
    raw = getattr(row, "raw_search_json", None) or "{}"
    try:
        data = json.loads(raw) if isinstance(raw, str) else dict(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def jina_already_attempted(row: Any) -> bool:
    meta = raw_meta(row)
    if meta.get("jina_attempted") in (1, True, "1", "true"):
        return True
    return False


def mark_jina_attempted(row: Any) -> None:
    meta = raw_meta(row)
    meta["jina_attempted"] = 1
    row.raw_search_json = json.dumps(meta, ensure_ascii=False)


def jina_proxy_url(target_url: str) -> str:
    # Target already validated; encode path as absolute URL after prefix.
    return f"{JINA_READER_PREFIX}{target_url}"


def assess_jina_markdown(body: str, *, status_code: int | None = None) -> tuple[bool, str | None, str]:
    """Return (ok, error_type, detail). Fake / empty bodies fail."""
    text = (body or "").strip()
    if status_code == 429:
        return False, "jina_rate_limited", "http_status=429"
    if status_code is not None and status_code >= 400:
        return False, "jina_failed", f"http_status={status_code}"
    if not text:
        return False, "jina_fake_body", "empty_body"

    # Error JSON payloads
    if text.startswith("{") and text.endswith("}"):
        try:
            obj = json.loads(text)
            if isinstance(obj, dict) and (
                obj.get("error") or obj.get("code") or obj.get("message") == "error"
            ):
                return False, "jina_fake_body", "error_json"
        except json.JSONDecodeError:
            pass

    low = text[:4000].lower()
    for marker, err in JINA_FAKE_MARKERS:
        if marker in low:
            return False, err, f"fake_marker:{marker}"

    hit = find_block_marker(title="", text=text[:2000], final_url=None, html_snippet=None)
    if hit:
        marker, _err = hit
        return False, "jina_fake_body", f"block_marker:{marker}"

    # Strip markdown heading for length check
    plain = re.sub(r"^#+\s*", "", text, count=1).strip()
    if len(plain) < 40:
        return False, "jina_fake_body", f"insufficient_len={len(plain)}"
    return True, None, f"len={len(plain)}"


def _title_from_markdown(text: str) -> str:
    for line in text.splitlines()[:30]:
        s = line.strip()
        if s.startswith("#"):
            return re.sub(r"^#+\s*", "", s).strip()[:512]
    return ""


def fetch_and_extract_jina(
    url: str,
    *,
    client: httpx.Client | None = None,
    timeout: float = 30.0,
    resolve_dns: bool = True,
) -> FetchedPage:
    """Fetch via r.jina.ai; markdown native (no trafilatura)."""
    try:
        assert_safe_url(url, resolve_dns=resolve_dns)
    except UnsafeURLError as exc:
        raise JinaFetchError("ssrf", str(exc)) from exc

    endpoint = jina_proxy_url(url)
    headers: dict[str, str] = {"Accept": "text/markdown, text/plain, */*"}
    key = _api_key()
    if key:
        headers["Authorization"] = f"Bearer {key}"

    own = client is None
    http = client or httpx.Client(follow_redirects=True, timeout=timeout)
    try:
        resp = http.get(endpoint, headers=headers)
    except httpx.HTTPError as exc:
        raise JinaFetchError("jina_failed", f"{type(exc).__name__}: {exc}") from exc
    finally:
        if own:
            http.close()

    if resp.status_code == 429:
        raise JinaFetchError("jina_rate_limited", "http_status=429")

    body = resp.text or ""
    ok, err, detail = assess_jina_markdown(body, status_code=resp.status_code)
    if not ok:
        raise JinaFetchError(err or "jina_failed", detail)

    title = _title_from_markdown(body)
    raw = body.encode("utf-8", errors="replace")
    return FetchedPage(
        url=url,
        title=title or "jina",
        text=body[:50_000],
        html=raw,
        final_url=url,
        content_kind="jina_markdown",
        blob_suffix=".md",
        status_code=resp.status_code,
    )
