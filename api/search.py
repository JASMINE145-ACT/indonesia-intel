from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from api.deps import get_db, require_api_key
from app.config import settings
from jobs.ingest_search import run_search_ingest_multi
from jobs.query_expand import expand_queries
from providers.factory import (
    available_provider_names,
    get_available_providers,
    get_default_provider,
    get_provider,
)


router = APIRouter(tags=["search"])


class SearchBody(BaseModel):
    query: str = Field(min_length=1)
    provider: str | None = None
    source_id: str | None = None


@router.get("/providers")
def list_providers(_: str = Depends(require_api_key)) -> dict:
    names = available_provider_names(
        brave_enabled=settings.brave_enabled,
        brave_api_key=settings.brave_api_key,
        exa_api_key=settings.exa_api_key,
        tavily_api_key=settings.tavily_api_key,
    )
    return {
        "available": names,
        "default": names[0] if names else "brave_mock",
        "brave_enabled": settings.brave_enabled,
        "exa_configured": bool(settings.exa_api_key),
        "tavily_configured": bool(settings.tavily_api_key),
        "search_union_enabled": settings.search_union_enabled,
        "query_expand_enabled": settings.query_expand_enabled,
    }


@router.post("/search")
async def post_search(
    body: SearchBody,
    _: str = Depends(require_api_key),
    db: Session = Depends(get_db),
) -> dict:
    """Search → ingest discovered candidates. Prefers Exa∪Tavily when configured."""
    common = dict(
        brave_enabled=settings.brave_enabled,
        brave_api_key=settings.brave_api_key,
        exa_api_key=settings.exa_api_key,
        tavily_api_key=settings.tavily_api_key,
    )
    try:
        if body.provider:
            providers = [get_provider(body.provider, **common)]
        elif settings.search_union_enabled:
            providers = get_available_providers(**common)
        else:
            providers = [get_default_provider(**common)]
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if body.source_id:
        from pathlib import Path

        from sources import SourceRegistry

        registry_path = Path(__file__).resolve().parent.parent / "sources" / "registry.yaml"
        try:
            SourceRegistry.load(registry_path).assert_fetch_allowed(body.source_id)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    queries = expand_queries(
        body.query,
        db,
        enabled=bool(settings.query_expand_enabled),
        max_variants=4,
    )
    try:
        summary = await run_search_ingest_multi(
            db,
            providers,
            queries,
            source_id=body.source_id,
            max_per_query=10,
            timeout_s=float(settings.search_provider_timeout_s),
        )
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc
    except RuntimeError as exc:
        if "all search providers failed" in str(exc):
            raise HTTPException(
                status_code=502,
                detail="search provider failed; check server logs and API keys",
            ) from None
        raise
    except Exception:
        # Do not echo SDK/network text (may leak URLs or key material).
        raise HTTPException(
            status_code=502,
            detail="search provider failed; check server logs and API keys",
        ) from None

    return summary
