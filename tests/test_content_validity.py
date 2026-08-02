"""Unit tests for content validity / block-marker classification."""

import pytest

from fetch.content import FetchedPage
from fetch.content_validity import (
    HARD_FETCH_ERROR_TYPES,
    RETRYABLE_FETCH_ERROR_TYPES,
    assess_extracted_page,
    classify_exception,
    find_block_marker,
    is_hard_fetch_error,
    is_retryable_fetch_error,
    is_social_host,
    page_is_invalid,
    should_escalate,
)
from fetch.ssrf import UnsafeURLError


def test_blocked_title_fails() -> None:
    v = assess_extracted_page(
        title="Sorry, you have been blocked",
        text="x" * 100,
        html=b"<html></html>",
    )
    assert v.ok is False
    assert v.error_type == "waf_blocked"


def test_cloudflare_body_fails() -> None:
    v = assess_extracted_page(
        title="Just a moment...",
        text="Checking your browser before accessing",
        html=b"<html>cf-chl-bypass</html>",
    )
    assert v.ok is False
    assert v.error_type == "cloudflare_challenge"


def test_javascript_disabled_fails() -> None:
    v = assess_extracted_page(
        title="JavaScript is disabled",
        text="Please enable JavaScript and cookies to continue",
        html=b"<html>enable javascript and cookies</html>",
    )
    assert v.ok is False
    assert v.error_type == "javascript_shell"


def test_valid_article_succeeds() -> None:
    v = assess_extracted_page(
        title="Indonesia investment update",
        text="Chinese EV maker advances plant construction in West Java Subang region.",
        html=b"<html><article><p>Chinese EV maker advances plant.</p></article></html>",
    )
    assert v.ok is True


def test_empty_extraction_fails() -> None:
    v = assess_extracted_page(title="", text="", html=b"<html></html>")
    assert v.ok is False
    assert v.error_type == "empty_extraction"


def test_status_403_not_empty(monkeypatch) -> None:
    monkeypatch.setenv("INTEL_FETCH_HTTP_RECLASS", "1")
    v = assess_extracted_page(
        title="",
        text="",
        html=b"<html>Forbidden</html>",
        status_code=403,
    )
    assert v.error_type == "http_403"


def test_status_410_terminal(monkeypatch) -> None:
    monkeypatch.setenv("INTEL_FETCH_HTTP_RECLASS", "1")
    v = assess_extracted_page(title="x", text="y" * 50, status_code=410)
    assert v.error_type == "terminal_gone"
    assert should_escalate("terminal_gone") is False


def test_status_404_terminal(monkeypatch) -> None:
    monkeypatch.setenv("INTEL_FETCH_HTTP_RECLASS", "1")
    v = assess_extracted_page(title="", text="", status_code=404)
    assert v.error_type == "terminal_not_found"


def test_find_block_marker_in_html() -> None:
    hit = find_block_marker(html_snippet=b"<div>Sorry, you have been blocked</div>")
    assert hit is not None
    assert hit[1] == "waf_blocked"


def test_article_mentioning_just_a_moment_in_body_ok() -> None:
    v = assess_extracted_page(
        title="Indonesia labor reform news",
        text=(
            "Officials said wait just a moment while the committee reviews "
            "investment proposals for the nickel downstreaming project."
        ),
        html=b"<html><article><p>Officials said wait just a moment while...</p></article></html>",
    )
    assert v.ok is True


def test_classify_certificate() -> None:
    assert (
        classify_exception(
            RuntimeError(
                "[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: "
                "unable to get local issuer certificate"
            )
        )
        == "certificate_failure"
    )


def test_classify_dns() -> None:
    assert classify_exception(UnsafeURLError("DNS failed for www.imip.co.id")) == "dns_failure"


def test_classify_remote_protocol() -> None:
    class RemoteProtocolError(Exception):
        pass

    assert classify_exception(RemoteProtocolError("peer closed")) == "remote_protocol_error"


def test_classify_oversized_not_http_403() -> None:
    assert (
        classify_exception(ValueError("response too large: 4030000 > 2000000"))
        == "response_too_large"
    )
    assert classify_exception(ValueError("pdf_too_large: 15000000 > 12000000")) == "pdf_too_large"


def test_legacy_tls_disconnect_retryable() -> None:
    assert is_retryable_fetch_error("tls_disconnect") is True


def test_circuit_open_hard_but_retryable() -> None:
    assert is_hard_fetch_error("circuit_open") is True
    assert is_retryable_fetch_error("circuit_open") is True


def test_social_host() -> None:
    assert is_social_host("https://www.instagram.com/p/x")
    assert is_social_host("https://facebook.com/x")
    assert not is_social_host("https://kompas.com/x")
    assert should_escalate("social_unsupported") is False


@pytest.mark.parametrize(
    "err,soft_hard,retry",
    [
        ("remote_protocol_error", False, True),
        ("http_403", False, True),
        ("terminal_gone", True, False),
        ("terminal_not_found", True, False),
        ("social_unsupported", False, False),
        ("circuit_open", True, True),
        ("pdf_too_large", True, False),
        ("tls_disconnect", False, True),
        ("ssrf", True, False),
    ],
)
def test_disposition_table(err: str, soft_hard: bool, retry: bool) -> None:
    assert is_hard_fetch_error(err) is soft_hard
    assert is_retryable_fetch_error(err) is retry


def test_page_is_invalid_wrapper() -> None:
    page = FetchedPage(
        url="https://www.iea.org/x",
        title="Just a moment...",
        text="short",
        html=b"<html>Just a moment...</html>",
        final_url="https://www.iea.org/x",
    )
    assert page_is_invalid(page).ok is False


def test_retryable_contains_new_types() -> None:
    for t in (
        "remote_protocol_error",
        "connection_reset",
        "read_error",
        "proxy_error",
        "tls_disconnect",
    ):
        assert t in RETRYABLE_FETCH_ERROR_TYPES
    assert "terminal_gone" in HARD_FETCH_ERROR_TYPES
