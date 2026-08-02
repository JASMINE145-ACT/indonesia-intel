"""WANd.INTEL.AGENT_REACH_SOCIAL.001 — typed reasons + provider enums."""

from __future__ import annotations

PROVIDERS = frozenset({"youtube", "linkedin"})

DISCOVERY_METHOD = {
    "youtube": "reach_youtube",
    "linkedin": "reach_linkedin",
}

REASON_REACH_DISABLED = "reach_disabled"
REASON_YOUTUBE_MISSING_KEY = "youtube_missing_key"
REASON_YOUTUBE_QUOTA = "youtube_quota"
REASON_YOUTUBE_HTTP = "youtube_http_error"
REASON_LINKEDIN_CREDS = "linkedin_needs_credentials"
REASON_HOST_NOT_ALLOWED = "reach_host_not_allowed"
REASON_UNKNOWN_PROVIDER = "reach_unknown_provider"
REASON_EMPTY_QUERY = "reach_empty_query"
