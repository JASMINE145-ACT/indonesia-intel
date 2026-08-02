"""Runtime discovery feature flags — WANd.INTEL.POLL_DISPATCH.001."""

from __future__ import annotations

import os


def _env_bool(name: str) -> bool | None:
    if name not in os.environ:
        return None
    raw = os.environ.get(name, "1").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def discovery_sitemap_enabled() -> bool:
    for key in ("INTEL_DISCOVERY_SITEMAP", "DISCOVERY_SITEMAP_ENABLED"):
        v = _env_bool(key)
        if v is not None:
            return v
    try:
        from app.config import settings

        return bool(settings.discovery_sitemap_enabled)
    except Exception:  # noqa: BLE001
        return True


def discovery_listing_enabled() -> bool:
    for key in ("INTEL_DISCOVERY_LISTING", "DISCOVERY_LISTING_ENABLED"):
        v = _env_bool(key)
        if v is not None:
            return v
    try:
        from app.config import settings

        return bool(settings.discovery_listing_enabled)
    except Exception:  # noqa: BLE001
        return True


def discovery_gnews_resolve_enabled() -> bool:
    for key in ("INTEL_DISCOVERY_GNEWS", "DISCOVERY_GNEWS_RESOLVE_ENABLED"):
        v = _env_bool(key)
        if v is not None:
            return v
    try:
        from app.config import settings

        return bool(settings.discovery_gnews_resolve_enabled)
    except Exception:  # noqa: BLE001
        return True


def discovery_watch_enabled() -> bool:
    for key in ("INTEL_DISCOVERY_WATCH", "DISCOVERY_WATCH_ENABLED"):
        v = _env_bool(key)
        if v is not None:
            return v
    try:
        from app.config import settings

        return bool(settings.discovery_watch_enabled)
    except Exception:  # noqa: BLE001
        return False


def reach_enabled() -> bool:
    for key in ("INTEL_REACH_ENABLED", "REACH_ENABLED"):
        v = _env_bool(key)
        if v is not None:
            return v
    try:
        from app.config import settings

        return bool(settings.reach_enabled)
    except Exception:  # noqa: BLE001
        return False


def fetch_jina_fallback_enabled() -> bool:
    for key in ("INTEL_FETCH_JINA_FALLBACK", "FETCH_JINA_FALLBACK_ENABLED"):
        v = _env_bool(key)
        if v is not None:
            return v
    try:
        from app.config import settings

        return bool(settings.fetch_jina_fallback_enabled)
    except Exception:  # noqa: BLE001
        return False


def pdf_queue_enabled() -> bool:
    for key in ("INTEL_PDF_QUEUE_ENABLED", "PDF_QUEUE_ENABLED"):
        v = _env_bool(key)
        if v is not None:
            return v
    try:
        from app.config import settings

        return bool(settings.pdf_queue_enabled)
    except Exception:  # noqa: BLE001
        return True
