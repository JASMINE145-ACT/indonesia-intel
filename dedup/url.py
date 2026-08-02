from __future__ import annotations

import hashlib
from urllib.parse import urlparse, urlunparse


def normalize_url(url: str) -> str:
    raw = url.strip()
    parsed = urlparse(raw)
    scheme = (parsed.scheme or "https").lower()
    netloc = parsed.netloc.lower()
    path = parsed.path or ""
    if path.endswith("/") and path != "/":
        path = path[:-1]
    # drop fragments and common tracking is Phase 3-light: fragment only
    cleaned = urlunparse((scheme, netloc, path, "", parsed.query, ""))
    return cleaned


def url_hash(url: str) -> str:
    return hashlib.sha256(normalize_url(url).encode("utf-8")).hexdigest()
