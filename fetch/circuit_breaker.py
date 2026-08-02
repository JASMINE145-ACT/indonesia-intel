"""In-batch per-host circuit breaker for fetch escalation.

Contract: WANd.INTEL.FETCH_CIRCUIT_BREAKER.001
"""
from __future__ import annotations

import os
from collections import defaultdict


def circuit_breaker_enabled() -> bool:
    if "INTEL_FETCH_CIRCUIT_BREAKER" in os.environ:
        raw = os.environ.get("INTEL_FETCH_CIRCUIT_BREAKER", "1").strip().lower()
        return raw not in {"0", "false", "no", "off"}
    try:
        from app.config import settings

        return bool(getattr(settings, "fetch_circuit_breaker_enabled", True))
    except Exception:  # noqa: BLE001
        return True


class HostCircuitBreaker:
    """Memory-only; resets each fetch_discovered_candidates call."""

    def __init__(self, *, threshold: int = 3) -> None:
        self.threshold = max(1, threshold)
        self._fails: dict[str, int] = defaultdict(int)
        self._open: set[str] = set()

    def is_open(self, host: str) -> bool:
        if not host:
            return False
        return host in self._open

    def record_success(self, host: str) -> None:
        if not host:
            return
        self._fails[host] = 0
        self._open.discard(host)

    def record_escalation_failure(self, host: str) -> None:
        """Count only after an escalation attempt still failed."""
        if not host:
            return
        self._fails[host] += 1
        if self._fails[host] >= self.threshold:
            self._open.add(host)
