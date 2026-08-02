from __future__ import annotations

import asyncio
import concurrent.futures
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import ReviewCandidate
from jobs.csv_export import export_events_csv
from jobs.dedup_check import dedup_check
from jobs.entities import company_list, company_upsert, project_list, project_upsert
from jobs.event_sources import event_add_source, event_list_sources
from jobs.factcheck import factcheck_event
from jobs.fetch_candidates import fetch_discovered_candidates
from jobs.manual_intake import manual_add_candidate, manual_add_pdf
from jobs.poll_sources import poll_prefer_sources
from jobs.poll_rss import poll_rss_sources  # noqa: F401 — kept for direct RSS callers
from jobs.review_actions import confirm_candidate, ignore_candidate
from jobs.stats import dashboard_summary
from providers.factory import available_provider_names
from sources.store import sources_add, sources_list, sources_set_enabled
from storage.blob import LocalBlobStore
from taxonomy.registry import list_taxonomy


def _run_coro(coro: Any) -> Any:
    """Run async work from sync MCP tools (FastMCP may already own an event loop)."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


def intel_providers() -> dict[str, Any]:
    """L2 wide-search channels currently configured (Exa/Tavily/mock). Prefer/RSS is L1."""
    names = available_provider_names(
        brave_enabled=settings.brave_enabled,
        brave_api_key=settings.brave_api_key,
        exa_api_key=settings.exa_api_key,
        tavily_api_key=settings.tavily_api_key,
    )
    return {
        "available": names,
        "default": names[0] if names else "brave_mock",
        "exa_configured": bool(settings.exa_api_key),
        "tavily_configured": bool(settings.tavily_api_key),
        "search_union_enabled": bool(settings.search_union_enabled),
        "query_expand_enabled": bool(settings.query_expand_enabled),
        "fetch_soft_pending_enabled": bool(settings.fetch_soft_pending_enabled),
        "cascade": "L1 prefer/RSS first; L2 Exa∪Tavily wide search",
    }


def intel_sources_list(
    priority: str | None = None,
    region: str | None = None,
    enabled_only: bool = False,
) -> dict[str, Any]:
    """List prefer / fixed high-value sources (deep-research seed + learned)."""
    items = sources_list(priority=priority, region=region, enabled_only=enabled_only)
    return {"count": len(items), "items": items}


def intel_sources_add(
    domain: str,
    name: str = "",
    source_id: str = "",
    region: str = "",
    fetch_mode: str = "list",
    home_url: str = "",
    rss_url: str = "",
    priority: str = "B",
    notes: str = "added via MCP",
) -> dict[str, Any]:
    """Add a prefer source into learned.yaml (does not erase core registry.yaml)."""
    entry = sources_add(
        domain=domain,
        name=name,
        source_id=source_id,
        region=region,
        fetch_mode=fetch_mode,
        home_url=home_url,
        rss_url=rss_url,
        priority=priority,
        notes=notes,
    )
    return {"ok": True, "source": entry}


def intel_sources_set_enabled(source_id: str, enabled: bool) -> dict[str, Any]:
    """Enable or disable a prefer source (writes override into learned.yaml)."""
    entry = sources_set_enabled(source_id, enabled)
    return {"ok": True, "source": entry}


def intel_list(status: str = "pending_review", limit: int = 50) -> dict[str, Any]:
    """List review candidates by status (pending_review, discovered, confirmed, …).

    When fetch failed, each item includes full ``open_url`` + ``user_hint`` so the
    agent can show the user a clickable destination (no body truncation of URL).
    """
    from app import db as dbmod
    from jobs.ops_dashboard import list_item_dict

    dbmod.init_db()
    lim = max(1, min(int(limit), 200))
    with dbmod.SessionLocal() as db:  # type: Session
        rows = list(
            db.scalars(
                select(ReviewCandidate)
                .where(ReviewCandidate.status == status)
                .limit(lim)
            )
        )
        items = []
        for r in rows:
            item = list_item_dict(r)
            item["duplicate_of_event_id"] = r.duplicate_of_event_id
            items.append(item)
        return {
            "status": status,
            "count": len(rows),
            "items": items,
        }


def intel_poll_sources(
    source_ids: list[str] | None = None,
    limit_per_source: int = 30,
) -> dict[str, Any]:
    """L1: poll prefer sources via rss|sitemap|listing (configured). Not Exa/Tavily."""
    from app import db as dbmod

    dbmod.init_db()
    with dbmod.SessionLocal() as db:
        return poll_prefer_sources(
            db,
            source_ids=source_ids,
            limit_per_source=max(1, min(int(limit_per_source), 100)),
        )


def intel_search(query: str, provider: str | None = None, source_id: str | None = None) -> dict[str, Any]:
    """L2: wide search via Exa∪Tavily/mock → discovered. Prefer/RSS is L1 (intel_poll_sources)."""
    from app import db as dbmod
    from jobs.ingest_search import run_search_ingest_multi
    from jobs.query_expand import expand_queries
    from providers.factory import get_available_providers, get_default_provider, get_provider

    q = (query or "").strip()
    if not q:
        raise ValueError("query is required")
    common = dict(
        brave_enabled=settings.brave_enabled,
        brave_api_key=settings.brave_api_key,
        exa_api_key=settings.exa_api_key,
        tavily_api_key=settings.tavily_api_key,
    )

    dbmod.init_db()
    with dbmod.SessionLocal() as db:
        queries = expand_queries(
            q,
            db,
            enabled=bool(settings.query_expand_enabled),
            max_variants=4,
        )
        if provider:
            providers = [get_provider(provider, **common)]
        elif settings.search_union_enabled:
            providers = get_available_providers(**common)
        else:
            providers = [get_default_provider(**common)]

        summary = _run_coro(
            run_search_ingest_multi(
                db,
                providers,
                queries,
                source_id=source_id or None,
                max_per_query=10,
                timeout_s=float(settings.search_provider_timeout_s),
            )
        )
    summary["cascade"] = "L2 wide search (Exa∪Tavily/mock)"
    return summary


def intel_search_social(
    query: str,
    provider: str = "youtube",
    max_results: int = 10,
) -> dict[str, Any]:
    """Agent Reach social side toolkit → discovered. Requires INTEL_REACH_ENABLED=1.
    Does not replace intel_search (Exa∪Tavily). LinkedIn is stub without credentials.
    """
    from app import db as dbmod
    from jobs.ingest_reach import run_reach_ingest

    q = (query or "").strip()
    if not q:
        raise ValueError("query is required")
    dbmod.init_db()
    with dbmod.SessionLocal() as db:
        return run_reach_ingest(
            db,
            q,
            provider=provider or "youtube",
            youtube_api_key=settings.youtube_api_key,
            max_results=max(1, min(int(max_results), 25)),
        )


def intel_fetch(
    limit: int = 20,
    run_id: str | None = None,
    retry_failed: bool = False,
) -> dict[str, Any]:
    """Fetch discovered candidates → pending_review (or fetch_failed / soft-pending)."""
    from app import db as dbmod

    dbmod.init_db()
    blob = LocalBlobStore(settings.blob_path)
    with dbmod.SessionLocal() as db:
        return fetch_discovered_candidates(
            db,
            blob,
            limit=max(1, min(int(limit), 100)),
            run_id=run_id or None,
            retry_failed=bool(retry_failed),
        )


def intel_manual_add(
    title: str,
    url: str = "",
    text: str = "",
    source_attribution: str = "待验证",
    is_public_source: bool = True,
) -> dict[str, Any]:
    """PRD §4.4 人工投喂：网页链接 / 粘贴文字 / 无公开链接的手工事件 → 待审核池
    （跳过自动搜索，直接进入 pending_review，仍需 intel_confirm/intel_ignore）。
    source_attribution 取值见 intel_taxonomy_list()."""
    from app import db as dbmod

    dbmod.init_db()
    with dbmod.SessionLocal() as db:
        row = manual_add_candidate(
            db,
            title=title,
            url=url,
            text=text,
            source_attribution=source_attribution,
            is_public_source=is_public_source,
        )
        return {"id": row.id, "status": row.status, "canonical_url": row.canonical_url}


def intel_manual_add_pdf(
    path: str,
    source_attribution: str = "待验证",
    is_public_source: bool = True,
    title: str = "",
) -> dict[str, Any]:
    """Local PDF file → extract text → pending_review. Rejects path traversal / empty PDF."""
    from app import db as dbmod

    dbmod.init_db()
    with dbmod.SessionLocal() as db:
        row = manual_add_pdf(
            db,
            path,
            source_attribution=source_attribution,
            is_public_source=is_public_source,
            title=title,
        )
        return {
            "id": row.id,
            "status": row.status,
            "canonical_url": row.canonical_url,
            "title": row.title,
            "text_len": len(row.extracted_text or ""),
        }


def intel_confirm(
    candidate_id: int,
    reason: str | None = None,
    *,
    company_id: int | None = None,
    company_name: str = "",
    project_id: int | None = None,
    industry: str = "",
    event_type: str = "",
    project_stage: str = "",
    occurred_date: str = "",
    published_date: str = "",
    location: str = "",
    investment_amount: str = "",
    planned_capacity: str = "",
    partners: str = "",
    summary: str = "",
    credibility: str = "",
    is_public: bool | None = None,
    notes: str = "",
    allow_unfetched: bool = False,
) -> dict[str, Any]:
    """Confirm pending_review candidate into a structured formal event (PRD §5.2).

    Structured fields are optional (bare confirm still works), but industry /
    event_type / project_stage are checked against the §6 controlled taxonomy
    when provided — call intel_taxonomy_list() first to see allowed values.
    Leave is_public unset to inherit the "是否可对外使用" flag recorded at
    intake time (intel_manual_add) instead of defaulting to public.
    Unfetched (no body / fetch_status=failed) requires allow_unfetched=True;
    factcheck will still fail for content generation.
    """
    from app import db as dbmod

    dbmod.init_db()
    with dbmod.SessionLocal() as db:
        return confirm_candidate(
            db,
            int(candidate_id),
            reason=reason,
            actor="mcp",
            company_id=company_id,
            company_name=company_name or None,
            project_id=project_id,
            industry=industry or None,
            event_type=event_type or None,
            project_stage=project_stage or None,
            occurred_date=occurred_date or None,
            published_date=published_date or None,
            location=location or None,
            investment_amount=investment_amount or None,
            planned_capacity=planned_capacity or None,
            partners=partners or None,
            summary=summary or None,
            credibility=credibility or None,
            is_public=is_public,
            notes=notes or None,
            allow_unfetched=bool(allow_unfetched),
        )


def intel_ignore(candidate_id: int, reason: str | None = None) -> dict[str, Any]:
    """Ignore a pending_review or watching candidate."""
    from app import db as dbmod

    dbmod.init_db()
    with dbmod.SessionLocal() as db:
        return ignore_candidate(db, int(candidate_id), reason=reason, actor="mcp")


def intel_watch(candidate_id: int, reason: str | None = None) -> dict[str, Any]:
    """Move pending_review → watching (观察列表). Default intel_list does not include watching."""
    from app import db as dbmod
    from jobs.review_actions import watch_candidate

    dbmod.init_db()
    with dbmod.SessionLocal() as db:
        return watch_candidate(db, int(candidate_id), reason=reason, actor="mcp")


def intel_merge(
    candidate_id: int,
    target_formal_event_id: int,
    reason: str | None = None,
) -> dict[str, Any]:
    """Merge candidate into existing formal_event: add EventSource, status=merged."""
    from app import db as dbmod
    from jobs.review_actions import merge_candidate

    dbmod.init_db()
    with dbmod.SessionLocal() as db:
        return merge_candidate(
            db,
            int(candidate_id),
            target_formal_event_id=int(target_formal_event_id),
            reason=reason,
            actor="mcp",
        )


def intel_learn_source(
    url_or_domain: str,
    *,
    name: str = "",
    rss_url: str = "",
    region: str = "",
    priority: str = "B",
    notes: str = "learned via MCP",
) -> dict[str, Any]:
    """Learn/feed a website into prefer list (learned.yaml). Accepts domain or http(s) URL."""
    raw = (url_or_domain or "").strip()
    if not raw:
        raise ValueError("url_or_domain required")
    domain = raw
    home = ""
    if "://" in raw:
        parsed = urlparse(raw)
        if parsed.scheme not in {"http", "https"}:
            raise ValueError("only http(s) URLs accepted")
        domain = (parsed.hostname or "").removeprefix("www.")
        home = f"{parsed.scheme}://{parsed.netloc}/"
    fetch_mode = "rss" if rss_url else "list"
    entry = sources_add(
        domain=domain,
        name=name or domain,
        region=region,
        fetch_mode=fetch_mode,
        home_url=home,
        rss_url=rss_url,
        priority=priority,
        notes=notes,
    )
    return {"ok": True, "source": entry, "cascade": "prefer list grown (learn)"}


def intel_taxonomy_list() -> dict[str, Any]:
    """PRD §6 受控词表：industries / event_types / project_stages. AI 不得自创新类；
    人工需要扩展时直接编辑 taxonomy/registry.yaml。"""
    return list_taxonomy()


def intel_dedup_check(candidate_id: int, threshold: float = 0.55, limit: int = 5) -> dict[str, Any]:
    """PRD §4.3 疑似重复检测（标题相似度启发式）。确认前建议先跑一遍。"""
    from app import db as dbmod

    dbmod.init_db()
    with dbmod.SessionLocal() as db:
        return dedup_check(db, int(candidate_id), threshold=threshold, limit=int(limit))


def intel_company_upsert(
    name_cn: str,
    name_en: str = "",
    name_id: str = "",
    brand: str = "",
    parent_company_id: int | None = None,
    industry: str = "",
    cn_hq: str = "",
    id_presence: str = "",
    is_listed: bool | None = None,
    first_entry_date: str = "",
    website: str = "",
    summary: str = "",
    main_business_id: str = "",
) -> dict[str, Any]:
    """企业档案 upsert（PRD §5.1）。按 name_cn 自然键匹配已有记录并合并更新。"""
    from app import db as dbmod

    dbmod.init_db()
    with dbmod.SessionLocal() as db:
        row = company_upsert(
            db,
            name_cn=name_cn,
            name_en=name_en or None,
            name_id=name_id or None,
            brand=brand or None,
            parent_company_id=parent_company_id,
            industry=industry or None,
            cn_hq=cn_hq or None,
            id_presence=id_presence or None,
            is_listed=is_listed,
            first_entry_date=first_entry_date or None,
            website=website or None,
            summary=summary or None,
            main_business_id=main_business_id or None,
        )
        return {"ok": True, "id": row.id, "name_cn": row.name_cn}


def intel_company_list(industry: str | None = None, limit: int = 50) -> dict[str, Any]:
    """企业库检索（PRD §10 企业库）。"""
    from app import db as dbmod

    dbmod.init_db()
    with dbmod.SessionLocal() as db:
        rows = company_list(db, industry=industry, limit=limit)
        return {
            "count": len(rows),
            "items": [
                {
                    "id": r.id,
                    "name_cn": r.name_cn,
                    "name_en": r.name_en,
                    "industry": r.industry,
                    "is_listed": r.is_listed,
                    "first_entry_date": r.first_entry_date,
                }
                for r in rows
            ],
        }


def intel_project_upsert(
    project_id: int | None = None,
    name: str = "",
    company_id: int | None = None,
    industry: str = "",
    location: str = "",
    stage: str = "",
    investment_amount: str = "",
    planned_capacity: str = "",
    partners: str = "",
    notes: str = "",
) -> dict[str, Any]:
    """项目档案 upsert（PRD §5.3）。传 project_id 追加同一时间线，否则按 name(+company_id) 匹配/新建。"""
    from app import db as dbmod

    dbmod.init_db()
    with dbmod.SessionLocal() as db:
        row = project_upsert(
            db,
            project_id=project_id,
            name=name,
            company_id=company_id,
            industry=industry or None,
            location=location or None,
            stage=stage or None,
            investment_amount=investment_amount or None,
            planned_capacity=planned_capacity or None,
            partners=partners or None,
            notes=notes or None,
        )
        return {"ok": True, "id": row.id, "name": row.name, "stage": row.stage}


def intel_project_list(
    company_id: int | None = None, stage: str | None = None, limit: int = 50
) -> dict[str, Any]:
    """项目库检索（PRD §10 项目库：项目时间线）。"""
    from app import db as dbmod

    dbmod.init_db()
    with dbmod.SessionLocal() as db:
        rows = project_list(db, company_id=company_id, stage=stage, limit=limit)
        return {
            "count": len(rows),
            "items": [
                {
                    "id": r.id,
                    "name": r.name,
                    "company_id": r.company_id,
                    "industry": r.industry,
                    "stage": r.stage,
                    "location": r.location,
                }
                for r in rows
            ],
        }


def intel_stats(
    industry: str = "",
    event_type: str = "",
    project_stage: str = "",
    company_id: int | None = None,
    date_from: str = "",
    date_to: str = "",
    public_only: bool = False,
    company_limit: int = 20,
    location: str = "",
) -> dict[str, Any]:
    """PRD §7.1 固定分析看板（含地区/来源/合作方/投资文本/新增vs存量）。"""
    from app import db as dbmod

    dbmod.init_db()
    with dbmod.SessionLocal() as db:
        return dashboard_summary(
            db,
            industry=industry or None,
            event_type=event_type or None,
            project_stage=project_stage or None,
            company_id=company_id,
            date_from=date_from or None,
            date_to=date_to or None,
            public_only=public_only,
            company_limit=company_limit,
            location=location or None,
        )


def intel_event_add_source(formal_event_id: int, url: str, label: str = "") -> dict[str, Any]:
    """PRD §5.4：给已确认事件追加一条来源（企业稿/政府声明/当地媒体/中国媒体转载等）。"""
    from app import db as dbmod

    dbmod.init_db()
    with dbmod.SessionLocal() as db:
        row = event_add_source(db, int(formal_event_id), url, label=label or None)
        return {"ok": True, "id": row.id, "event_id": row.event_id, "url": row.url}


def intel_event_sources(formal_event_id: int) -> dict[str, Any]:
    """列出某条正式事件的全部来源（PRD §5.4）。"""
    from app import db as dbmod

    dbmod.init_db()
    with dbmod.SessionLocal() as db:
        rows = event_list_sources(db, int(formal_event_id))
        return {
            "count": len(rows),
            "items": [
                {"id": r.id, "url": r.url, "source_domain": r.source_domain, "label": r.label}
                for r in rows
            ],
        }


def intel_export_events_csv(
    industry: str = "",
    event_type: str = "",
    project_stage: str = "",
    company_id: int | None = None,
    date_from: str = "",
    date_to: str = "",
    public_only: bool = False,
) -> dict[str, Any]:
    """PRD §11.1「Excel 导入导出」— 导出已确认 formal_events 为 CSV（Excel 可直接打开）。
    只导出确认过的事件，未审核候选不会出现在导出结果里。"""
    from app import db as dbmod

    dbmod.init_db()
    with dbmod.SessionLocal() as db:
        csv_text = export_events_csv(
            db,
            industry=industry or None,
            event_type=event_type or None,
            project_stage=project_stage or None,
            company_id=company_id,
            date_from=date_from or None,
            date_to=date_to or None,
            public_only=public_only,
        )
    return {"format": "csv", "content": csv_text}


def intel_factcheck_event(formal_event_id: int) -> dict[str, Any]:
    """PRD §9 事实检查面板：拦截无来源结论、脏引用、常见阶段误写。内容生成后应过一遍。"""
    from app import db as dbmod

    dbmod.init_db()
    with dbmod.SessionLocal() as db:
        return factcheck_event(db, int(formal_event_id))


# Parameter names that must never appear on MCP tool schemas (secrets).
FORBIDDEN_TOOL_PARAM_NAMES = frozenset(
    {
        "api_key",
        "apikey",
        "brave_api_key",
        "exa_api_key",
        "tavily_api_key",
        "youtube_api_key",
        "x_api_key",
        "password",
        "secret",
        "token",
    }
)
