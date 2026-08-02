"""FLAG off rollback — INTEL_FETCH_L15 / HTTP_RECLASS / CIRCUIT_BREAKER."""

from fetch.content_validity import assess_extracted_page, http_reclass_enabled
from fetch.circuit_breaker import circuit_breaker_enabled
from fetch.l15 import fetch_l15_enabled


def test_l15_flag_off(monkeypatch) -> None:
    monkeypatch.setenv("INTEL_FETCH_L15", "0")
    assert fetch_l15_enabled() is False


def test_http_reclass_flag_off_falls_to_empty(monkeypatch) -> None:
    monkeypatch.setenv("INTEL_FETCH_HTTP_RECLASS", "0")
    assert http_reclass_enabled() is False
    v = assess_extracted_page(title="", text="", html=b"<html></html>", status_code=403)
    assert v.error_type == "empty_extraction"


def test_circuit_flag_off(monkeypatch) -> None:
    monkeypatch.setenv("INTEL_FETCH_CIRCUIT_BREAKER", "0")
    assert circuit_breaker_enabled() is False
