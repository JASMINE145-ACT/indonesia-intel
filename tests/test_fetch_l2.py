"""Unit tests for Scrapling L2 adapter (mocked — no live Scrapling required)."""

from __future__ import annotations

import pytest

from fetch import scrapling_l2 as l2
from fetch.content import FetchedPage
from fetch.ssrf import UnsafeURLError


FIXTURE_HTML = b"""<!doctype html><html><head><title>L2 Page</title></head>
<body><article><h1>L2 Page</h1><p>Chinese investment in Indonesia nickel.</p></article></body></html>"""


@pytest.fixture(autouse=True)
def _reset_hooks(monkeypatch):
    monkeypatch.setattr(l2, "_fetcher_get", None)
    monkeypatch.setattr(l2, "_dynamic_fetch", None)
    monkeypatch.setattr(l2, "_stealthy_fetch", None)
    monkeypatch.setattr(l2, "_import_error", None)
    yield
    monkeypatch.setattr(l2, "_fetcher_get", None)
    monkeypatch.setattr(l2, "_dynamic_fetch", None)
    monkeypatch.setattr(l2, "_stealthy_fetch", None)


def test_domain_allowed_suffix() -> None:
    assert l2.domain_allowed("https://www.kompas.com/x", ["kompas.com"])
    assert not l2.domain_allowed("https://evil.com/", ["kompas.com"])


def test_ssrf_blocks_before_scrapling(monkeypatch) -> None:
    called = {"n": 0}

    def boom(*a, **k):
        called["n"] += 1
        raise AssertionError("must not call scrapling")

    monkeypatch.setattr(l2, "_fetcher_get", boom)
    with pytest.raises(UnsafeURLError):
        l2.fetch_and_extract_scrapling("http://127.0.0.1/", resolve_dns=False, allowlist=["127.0.0.1"])
    assert called["n"] == 0


def test_browser_requires_allow_browser() -> None:
    with pytest.raises(PermissionError, match="allow_browser"):
        l2.fetch_and_extract_scrapling(
            "https://www.iea.org/x",
            mode="stealthy",
            resolve_dns=False,
            allow_browser=False,
            allowlist=["iea.org"],
            html_override=FIXTURE_HTML,
        )


def test_allowlist_required_fail_closed() -> None:
    with pytest.raises(PermissionError, match="allowlist"):
        l2.fetch_and_extract_scrapling(
            "https://www.kompas.com/",
            resolve_dns=False,
            html_override=FIXTURE_HTML,
        )


def test_wrong_allowlist_domain() -> None:
    with pytest.raises(PermissionError, match="allowlist"):
        l2.fetch_and_extract_scrapling(
            "https://www.kompas.com/",
            resolve_dns=False,
            allowlist=["iea.org"],
            html_override=FIXTURE_HTML,
        )


def test_unsafe_url_not_l2_eligible() -> None:
    assert not l2.l2_eligible_error(UnsafeURLError("private/blocked address"))


def test_html_override_extract() -> None:
    page = l2.fetch_and_extract_scrapling(
        "https://www.kompas.com/a",
        resolve_dns=False,
        allowlist=["kompas.com"],
        html_override=FIXTURE_HTML,
    )
    assert isinstance(page, FetchedPage)
    assert "Indonesia" in page.text or "L2" in page.title


def test_http_mode_calls_fetcher(monkeypatch) -> None:
    class Resp:
        body = FIXTURE_HTML
        url = "https://www.kompas.com/a"

    monkeypatch.setattr(l2, "_fetcher_get", lambda *a, **k: Resp())
    page = l2.fetch_and_extract_scrapling(
        "https://www.kompas.com/a",
        mode="http",
        resolve_dns=False,
        allowlist=["kompas.com"],
    )
    assert page.title or page.text
    assert page.final_url.startswith("https://")


def test_soft_import_message(monkeypatch) -> None:
    def boom() -> None:
        raise ImportError(
            "Scrapling L2 unavailable. Install: pip install 'scrapling[fetchers]' "
            "&& scrapling install"
        )

    monkeypatch.setattr(l2, "_ensure_scrapling_loaded", boom)
    with pytest.raises(ImportError, match="scrapling\\[fetchers\\]"):
        l2.fetch_and_extract_scrapling(
            "https://www.kompas.com/a",
            resolve_dns=False,
            allowlist=["kompas.com"],
        )


def test_l2_eligible_error_filters() -> None:
    assert l2.l2_eligible_error(RuntimeError("Server disconnected"))
    assert l2.l2_eligible_error(RuntimeError("HTTP 403"))
    assert not l2.l2_eligible_error(RuntimeError("DNS failed for www.imip.co.id"))
    assert not l2.l2_eligible_error(RuntimeError("certificate verify failed"))


def test_scrapling_available_with_hook(monkeypatch) -> None:
    monkeypatch.setattr(l2, "_fetcher_get", lambda *a, **k: None)
    assert l2.scrapling_available() is True
