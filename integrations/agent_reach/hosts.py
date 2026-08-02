"""Discovery-side host allowlist for Agent Reach hits (not fetch is_social_host)."""

from __future__ import annotations

from urllib.parse import urlparse

# Subdomains of these registrable suffixes are allowed.
_ALLOWED_SUFFIXES = (
    "youtube.com",
    "youtu.be",
    "linkedin.com",
)


def host_allowed(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower().removeprefix("www.")
    if not host:
        return False
    for suffix in _ALLOWED_SUFFIXES:
        if host == suffix or host.endswith("." + suffix):
            return True
    return False
