from __future__ import annotations

import os
from dataclasses import dataclass

import httpx
import trafilatura

from fetch.pdf import extract_pdf_text, looks_like_pdf
from fetch.ssrf import assert_safe_url


@dataclass
class FetchedPage:
    url: str
    title: str
    text: str
    html: bytes
    final_url: str
    content_kind: str = "html"  # html | pdf
    blob_suffix: str = ".html"
    status_code: int | None = None


DEFAULT_TIMEOUT = 15.0
DEFAULT_MAX_BYTES = 2_000_000
DEFAULT_MAX_PDF_BYTES = 12_000_000


def _proxy_from_env() -> str | None:
    for key in ("PROXY_URL", "HTTPS_PROXY", "HTTP_PROXY"):
        val = (os.environ.get(key) or "").strip()
        if val:
            return val
    try:
        from app.config import settings

        val = (settings.proxy_url or "").strip()
        if val:
            return val
    except Exception:  # noqa: BLE001
        pass
    return None


def _make_client(timeout: float) -> httpx.Client:
    proxy = _proxy_from_env()
    kwargs: dict = {"follow_redirects": False, "timeout": timeout}
    if proxy:
        kwargs["proxy"] = proxy
    return httpx.Client(**kwargs)


def fetch_and_extract(
    url: str,
    *,
    client: httpx.Client | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    max_bytes: int = DEFAULT_MAX_BYTES,
    max_pdf_bytes: int = DEFAULT_MAX_PDF_BYTES,
    resolve_dns: bool = True,
    html_override: bytes | None = None,
    status_code: int | None = None,
) -> FetchedPage:
    """L1 fetch: httpx + Trafilatura (HTML) or pypdf (PDF). html_override skips network."""
    assert_safe_url(url, resolve_dns=resolve_dns)

    ctype = ""
    code: int | None = status_code
    if html_override is not None:
        body = html_override
        final_url = url
        if looks_like_pdf(
            final_url,
            body,
            "application/pdf"
            if body[:5] == b"%PDF-" or url.lower().endswith(".pdf")
            else "",
        ) or body[:5] == b"%PDF-":
            if len(body) > max_pdf_bytes:
                raise ValueError(f"pdf_too_large: {len(body)} > {max_pdf_bytes}")
            title, text = extract_pdf_text(body)
            return FetchedPage(
                url=url,
                title=title,
                text=text,
                html=body,
                final_url=final_url,
                content_kind="pdf",
                blob_suffix=".pdf",
                status_code=code if code is not None else 200,
            )
    else:
        owns = client is None
        http = client or _make_client(timeout)
        try:
            current = url
            body = b""
            final_url = url
            for _ in range(5):
                assert_safe_url(current, resolve_dns=resolve_dns)
                resp = http.get(current)
                if resp.is_redirect:
                    loc = resp.headers.get("location")
                    if not loc:
                        raise ValueError("redirect without location")
                    current = str(httpx.URL(current).join(loc))
                    continue
                assert_safe_url(str(resp.url), resolve_dns=resolve_dns)
                body = resp.content
                ctype = resp.headers.get("content-type", "") or ""
                code = int(resp.status_code)
                limit = (
                    max_pdf_bytes
                    if looks_like_pdf(str(resp.url), body, ctype)
                    else max_bytes
                )
                if len(body) > limit:
                    if looks_like_pdf(str(resp.url), body, ctype) or str(resp.url).lower().endswith(
                        ".pdf"
                    ):
                        raise ValueError(f"pdf_too_large: {len(body)} > {limit}")
                    raise ValueError(f"response_too_large: {len(body)} > {limit}")
                if looks_like_pdf(str(resp.url), body, ctype):
                    final_url = str(resp.url)
                    break
                if (
                    ctype
                    and "html" not in ctype.lower()
                    and "text/" not in ctype.lower()
                    and "json" not in ctype.lower()
                ):
                    raise ValueError(f"unsupported content-type: {ctype}")
                final_url = str(resp.url)
                break
            else:
                raise ValueError("too many redirects")
        finally:
            if owns:
                http.close()

    if looks_like_pdf(final_url, body, ctype):
        title, text = extract_pdf_text(body)
        return FetchedPage(
            url=url,
            title=title,
            text=text,
            html=body,
            final_url=final_url,
            content_kind="pdf",
            blob_suffix=".pdf",
            status_code=code,
        )

    decoded = body.decode("utf-8", errors="replace")
    text = trafilatura.extract(decoded, include_comments=False, include_tables=False) or ""
    title = ""
    meta = trafilatura.extract_metadata(decoded)
    if meta is not None:
        title = meta.title or ""

    return FetchedPage(
        url=url,
        title=title,
        text=text,
        html=body,
        final_url=final_url,
        content_kind="html",
        blob_suffix=".html",
        status_code=code,
    )
