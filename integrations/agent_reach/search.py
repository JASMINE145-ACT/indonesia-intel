"""Agent Reach social search dispatcher — WANd.INTEL.AGENT_REACH_SOCIAL.001.

Lane rules: must not import providers.exa/tavily/factory, poll adapters, or confirm paths.
"""

from __future__ import annotations

from integrations.agent_reach.constants import (
    DISCOVERY_METHOD,
    PROVIDERS,
    REASON_EMPTY_QUERY,
    REASON_UNKNOWN_PROVIDER,
)
from integrations.agent_reach.linkedin import search_linkedin
from integrations.agent_reach.types import SocialSearchOutcome
from integrations.agent_reach.youtube import search_youtube


def search_social(
    query: str,
    provider: str,
    *,
    youtube_api_key: str = "",
    max_results: int = 10,
    http_get=None,
) -> SocialSearchOutcome:
    q = (query or "").strip()
    p = (provider or "").strip().lower()
    if not q:
        return SocialSearchOutcome(ok=False, reason=REASON_EMPTY_QUERY, provider=p)
    if p not in PROVIDERS:
        return SocialSearchOutcome(
            ok=False,
            reason=REASON_UNKNOWN_PROVIDER,
            provider=p,
            discovery_method=DISCOVERY_METHOD.get(p, ""),
        )
    if p == "youtube":
        return search_youtube(
            q,
            api_key=youtube_api_key,
            max_results=max_results,
            http_get=http_get,
        )
    return search_linkedin(q, max_results=max_results)
