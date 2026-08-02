import pytest

from fetch.ssrf import UnsafeURLError, assert_safe_url
from fetch.content import fetch_and_extract


def test_ssrf_blocks_localhost() -> None:
    with pytest.raises(UnsafeURLError):
        assert_safe_url("http://127.0.0.1/x", resolve_dns=False)


def test_ssrf_blocks_private_literal() -> None:
    with pytest.raises(UnsafeURLError):
        assert_safe_url("http://192.168.1.1/", resolve_dns=False)


def test_ssrf_allows_public_host_without_dns() -> None:
    assert_safe_url("https://example.com/a", resolve_dns=False)


FIXTURE_HTML = b"""<!doctype html><html><head><title>BYD Subang Update</title></head>
<body><article><h1>BYD Subang Update</h1>
<p>Chinese EV maker advances Indonesia plant construction in West Java.</p>
</article></body></html>"""


def test_extract_from_html_override() -> None:
    page = fetch_and_extract(
        "https://example.com/news/byd",
        resolve_dns=False,
        html_override=FIXTURE_HTML,
    )
    assert "Indonesia" in page.text or "BYD" in page.title or "BYD" in page.text
    assert page.html.startswith(b"<!doctype")


def test_html_override_status_code(monkeypatch) -> None:
    from fetch.content_validity import page_is_invalid

    monkeypatch.setenv("INTEL_FETCH_HTTP_RECLASS", "1")
    page = fetch_and_extract(
        "https://example.com/gone",
        resolve_dns=False,
        html_override=b"<html><body>gone</body></html>",
        status_code=410,
    )
    assert page.status_code == 410
    assert page_is_invalid(page).error_type == "terminal_gone"
