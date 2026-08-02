"""WANd.INTEL.FETCH_L15_CURL_CFFI.001"""

import pytest

from fetch import l15 as l15mod
from fetch.ssrf import UnsafeURLError


def test_l15_verify_true_and_no_redirect_fallback(monkeypatch) -> None:
    calls: list[dict] = []

    class Resp:
        url = "https://example.com/ok"
        status = 200
        body = b"<html><body><article><p>Enough text about Indonesia investment plant.</p></article></body></html>"

    def fake_get(url, **kwargs):
        calls.append(kwargs)
        if "allow_redirects" not in kwargs and "follow_redirects" not in kwargs:
            raise AssertionError("must not call without redirect control")
        return Resp()

    monkeypatch.setattr(l15mod, "_fetcher_get", fake_get)
    page = l15mod.fetch_and_extract_l15("https://example.com/ok", resolve_dns=False)
    assert page.text
    assert calls
    assert calls[0].get("verify") is True
    assert calls[0].get("allow_redirects") is False or calls[0].get("follow_redirects") is False


def test_l15_fail_closed_when_no_redirect_kwarg(monkeypatch) -> None:
    def fake_get(url, **kwargs):
        raise TypeError("unexpected kw")

    monkeypatch.setattr(l15mod, "_fetcher_get", fake_get)
    with pytest.raises(RuntimeError, match="l15_redirect_control_unsupported"):
        l15mod.fetch_and_extract_l15("https://example.com/x", resolve_dns=False)


def test_l15_ssrf_on_final_url(monkeypatch) -> None:
    class Resp:
        url = "http://169.254.169.254/latest"
        status = 200
        body = b"<html>meta</html>"

    monkeypatch.setattr(l15mod, "_fetcher_get", lambda url, **k: Resp())
    with pytest.raises(UnsafeURLError):
        l15mod.fetch_and_extract_l15("https://example.com/x", resolve_dns=False)


def test_fetch_l15_enabled_env(monkeypatch) -> None:
    monkeypatch.setenv("INTEL_FETCH_L15", "0")
    assert l15mod.fetch_l15_enabled() is False
    monkeypatch.setenv("INTEL_FETCH_L15", "1")
    assert l15mod.fetch_l15_enabled() is True
