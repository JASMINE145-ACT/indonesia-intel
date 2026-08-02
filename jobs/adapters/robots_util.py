"""Best-effort robots.txt check — D19 (fail-open with note)."""

from __future__ import annotations

from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx

from fetch.ssrf import assert_safe_url
from jobs.poll_rss import _RSS_HEADERS

_UA = _RSS_HEADERS.get("User-Agent", "indonesia-intel/1.0")


def robots_allows(
    url: str,
    *,
    client: httpx.Client | None = None,
    resolve_dns: bool = True,
    timeout_s: float = 5.0,
) -> tuple[bool, str]:
    """Return (allowed, note). On parse/fetch failure → (True, note) fail-open."""
    try:
        parsed = urlparse(url)
        robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
        assert_safe_url(robots_url, resolve_dns=resolve_dns)
        http = client or httpx.Client(
            timeout=timeout_s, follow_redirects=False, headers=_RSS_HEADERS
        )
        close = client is None
        try:
            resp = http.get(robots_url)
            if resp.status_code >= 400:
                return True, f"robots_http_{resp.status_code}"
            body = resp.text
        finally:
            if close:
                http.close()
        rp = RobotFileParser()
        rp.parse(body.splitlines())
        allowed = rp.can_fetch(_UA, url)
        return allowed, "robots_ok" if allowed else "robots_disallow"
    except Exception as exc:  # noqa: BLE001
        return True, f"robots_unparsed:{type(exc).__name__}"
