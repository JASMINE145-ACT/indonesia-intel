"""Ingest Agent Reach social hits → discovered. WANd.INTEL.AGENT_REACH_SOCIAL.001."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from integrations.agent_reach.constants import DISCOVERY_METHOD, REASON_REACH_DISABLED
from integrations.agent_reach.search import search_social
from jobs.adapters.common import insert_discovered_hits
from jobs.discovery_flags import reach_enabled


def run_reach_ingest(
    session: Session,
    query: str,
    provider: str = "youtube",
    *,
    youtube_api_key: str = "",
    max_results: int = 10,
    http_get=None,
    source_id: str | None = None,
) -> dict[str, Any]:
    p = (provider or "youtube").strip().lower()
    q = (query or "").strip()
    base: dict[str, Any] = {
        "ok": False,
        "reason": None,
        "provider": p,
        "discovery_method": DISCOVERY_METHOD.get(p),
        "query": q,
        "hits": 0,
        "inserted": 0,
        "skipped": 0,
        "run_id": None,
        "cascade": "Agent Reach social (side toolkit)",
    }
    if not reach_enabled():
        base["reason"] = REASON_REACH_DISABLED
        return base

    outcome = search_social(
        q,
        p,
        youtube_api_key=youtube_api_key,
        max_results=max_results,
        http_get=http_get,
    )
    base["reason"] = outcome.reason
    base["provider"] = outcome.provider or p
    base["discovery_method"] = outcome.discovery_method or DISCOVERY_METHOD.get(p)
    base["hits"] = len(outcome.hits)

    if not outcome.hits:
        base["ok"] = bool(outcome.ok)
        return base

    hit_dicts = [
        {
            "url": h.url,
            "title": h.title,
            "snippet": h.snippet,
            "query": h.query or q,
            "raw": h.raw,
        }
        for h in outcome.hits
    ]
    # insert_discovered_hits stores hit dict in raw_search_json — ensure no api key
    for hd in hit_dicts:
        raw = hd.get("raw") or {}
        if isinstance(raw, dict):
            for k in list(raw.keys()):
                if "key" in k.lower() or "token" in k.lower() or "secret" in k.lower():
                    del raw[k]

    sid = source_id or f"reach_{base['provider']}"
    inserted = insert_discovered_hits(
        session,
        hit_dicts,
        source_id=sid,
        provider=base["provider"],
        discovery_method=base["discovery_method"] or f"reach_{p}",
        note=f"reach:{p}:{q[:80]}",
    )
    base["ok"] = True
    base["reason"] = None
    base["run_id"] = inserted.get("run_id")
    base["inserted"] = inserted.get("inserted", 0)
    base["skipped"] = inserted.get("skipped", 0)
    base["hits"] = inserted.get("hits", len(hit_dicts))
    return base
