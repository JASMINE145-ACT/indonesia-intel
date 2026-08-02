"""LinkedIn Reach provider — pure stub (no cookie / no API in this task)."""

from __future__ import annotations

from integrations.agent_reach.constants import DISCOVERY_METHOD, REASON_LINKEDIN_CREDS
from integrations.agent_reach.types import SocialSearchOutcome


def search_linkedin(query: str, *, max_results: int = 10) -> SocialSearchOutcome:
    _ = (query, max_results)
    provider = "linkedin"
    return SocialSearchOutcome(
        ok=False,
        reason=REASON_LINKEDIN_CREDS,
        provider=provider,
        discovery_method=DISCOVERY_METHOD[provider],
        hits=[],
    )
