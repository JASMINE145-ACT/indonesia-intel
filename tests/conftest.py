"""Default: disable L1.5 in unit tests to prevent live curl_cffi / Scrapling calls.

Opt in per-test with monkeypatch.setenv("INTEL_FETCH_L15", "1") or
fetch_discovered_candidates(..., enable_l15=True).
"""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _disable_l15_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INTEL_FETCH_L15", "0")
