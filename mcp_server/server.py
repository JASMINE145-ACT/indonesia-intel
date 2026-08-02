"""Indonesia Intel MCP — stdio tools for Cursor / WorkBuddy."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from mcp_server import service

# Sent to the client during the MCP handshake. Tool schemas alone don't encode
# *sequencing* or business red lines (PRD §4.3/§6/§9) — this is the compact
# version of that; full detail lives in docs/agent_playbook.md.
INSTRUCTIONS = """\
中企出海印尼情报系统。工具是能力，PRD 的业务逻辑要你自己按顺序调用：

红线：
1. 未审核内容不进分析/内容生成 — intel_stats/intel_list 只读 formal_events，
   pending_review/discovered 状态的候选物理上读不到，正常调用就不会违反。
2. industry/event_type/project_stage/source_attribution 只能用
   intel_taxonomy_list() 里的值；别的值 intel_confirm 会直接拒绝。新增分类是
   人工编辑 taxonomy/registry.yaml 的事，不是你自创。
3. 往内容里写任何数字/案例前，先对其 formal_event_id 跑 intel_factcheck_event；
   ok:false 就不能用。
4. intel_manual_add 登记的 is_public_source=False 会被 intel_confirm 自动继承
   （除非你显式传 is_public=True）；不确定时不要手动改成公开。

标准顺序：
- 发现：intel_poll_sources (L1 rss|sitemap|listing|watch；SOURCE_LANES) → intel_search
  (L2 Exa/Tavily；Reach 不得替代) → 可选 intel_search_social（Agent Reach；需
  INTEL_REACH_ENABLED=1；仅社交窄搜进 discovered）。人工投喂用 intel_manual_add。
  INTEL_DISCOVERY_WATCH / INTEL_REACH_ENABLED / INTEL_FETCH_JINA_FALLBACK 默认关。
- 审核：intel_list(status="pending_review") → 对展示中的候选先 intel_dedup_check
  → intel_confirm / intel_ignore / intel_watch / intel_merge(target_formal_event_id)。
  观察池用 intel_list(status="watching")；默认 pending_review 不含 watching。
- 分析：intel_stats(筛选条件) 拿分布/趋势/排名，intel_list 取代表案例配 canonical_url。
- 内容：草稿引用的每个 formal_event_id 生成后过一遍 intel_factcheck_event，
  附上 intel_event_sources 的来源链接。
- 导出：intel_export_events_csv 只导出已确认事件。

详细步骤见 skill indonesia-intel（.cursor/skills/indonesia-intel/SKILL.md）
与 docs/agent_playbook.md。

本地浏览器 Ops 看板（人工巡检，非 MCP 替代）：uvicorn 后打开
http://127.0.0.1:8765/app/#feed — 见 indonesia-intel/README.md § Local Ops Dashboard。
"""

mcp = FastMCP("indonesia-intel", instructions=INSTRUCTIONS)


@mcp.tool()
def intel_providers() -> dict:
    """L2 channels (Exa/Tavily/mock). Discovery cascade: L1 prefer/RSS first, then L2 wide search."""
    return service.intel_providers()


@mcp.tool()
def intel_sources_list(
    priority: str | None = None,
    region: str | None = None,
    enabled_only: bool = False,
) -> dict:
    """List prefer/fixed sources (CN/ID/INT deep-research seed + learned). Filters: priority A|B, region CN|ID|INT."""
    return service.intel_sources_list(
        priority=priority, region=region, enabled_only=enabled_only
    )


@mcp.tool()
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
) -> dict:
    """Add a website to the prefer list (learned.yaml). Use fetch_mode=rss with rss_url when available."""
    return service.intel_sources_add(
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


@mcp.tool()
def intel_sources_set_enabled(source_id: str, enabled: bool) -> dict:
    """Enable or disable a prefer source by id."""
    return service.intel_sources_set_enabled(source_id, enabled)


@mcp.tool()
def intel_poll_sources(
    source_ids: list[str] | None = None,
    limit_per_source: int = 30,
) -> dict:
    """L1 prefer-source poll (rss|sitemap|listing) → discovered. Not Exa/Tavily. Optional source_ids."""
    return service.intel_poll_sources(
        source_ids=source_ids, limit_per_source=limit_per_source
    )


@mcp.tool()
def intel_search(query: str, provider: str | None = None, source_id: str | None = None) -> dict:
    """L2 wide search (Exa→Tavily→mock) → discovered. Use after or beside L1 prefer poll (rss|sitemap|listing)."""
    return service.intel_search(query=query, provider=provider, source_id=source_id)


@mcp.tool()
def intel_search_social(
    query: str,
    provider: str = "youtube",
    max_results: int = 10,
) -> dict:
    """Agent Reach social side toolkit (YouTube / LinkedIn stub) → discovered.
    Requires INTEL_REACH_ENABLED=1. Does NOT replace intel_search. Default off."""
    return service.intel_search_social(
        query=query, provider=provider, max_results=max_results
    )


@mcp.tool()
def intel_fetch(
    limit: int = 20,
    run_id: str | None = None,
    retry_failed: bool = False,
) -> dict:
    """Fetch body for discovered candidates → pending_review.
    Soft-fail keeps pending_review with fetch_status=failed.
    retry_failed=True also retries soft-failed rows.
    Response includes unfetched_for_user[{open_url, user_hint, …}] for humans."""
    return service.intel_fetch(limit=limit, run_id=run_id, retry_failed=retry_failed)


@mcp.tool()
def intel_list(status: str = "pending_review", limit: int = 50) -> dict:
    """List review-queue candidates. Default pending_review excludes watching.
    status: pending_review|watching|discovered|confirmed|ignored|merged|fetch_failed.
    Unfetched rows include full open_url + user_hint for human self-service."""
    return service.intel_list(status=status, limit=limit)


@mcp.tool()
def intel_manual_add(
    title: str,
    url: str = "",
    text: str = "",
    source_attribution: str = "待验证",
    is_public_source: bool = True,
) -> dict:
    """PRD §4.4 manual feed: web link / pasted text / no-URL manual event → the
    review queue (skips auto-discovery, lands in pending_review; still needs
    intel_confirm/intel_ignore). See intel_taxonomy_list() for source_attribution
    values (公开网络/企业官方/活动现场/商务交流/个人观察/待验证)."""
    return service.intel_manual_add(
        title,
        url=url,
        text=text,
        source_attribution=source_attribution,
        is_public_source=is_public_source,
    )


@mcp.tool()
def intel_manual_add_pdf(
    path: str,
    source_attribution: str = "待验证",
    is_public_source: bool = True,
    title: str = "",
) -> dict:
    """PRD §4.4 local PDF only: path → extract text → pending_review.
    Rejects '..' traversal, non-.pdf, and empty extraction. Excel/Word/images deferred."""
    return service.intel_manual_add_pdf(
        path,
        source_attribution=source_attribution,
        is_public_source=is_public_source,
        title=title,
    )


@mcp.tool()
def intel_confirm(
    candidate_id: int,
    reason: str | None = None,
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
) -> dict:
    """Confirm candidate → structured formal event (PRD §5.2). All structured
    fields optional; industry/event_type/project_stage validated against
    intel_taxonomy_list(). Pass company_name to auto-upsert a company record.
    Leave is_public unset to inherit the intake-time "是否可对外使用" flag
    (see intel_manual_add) instead of defaulting to public.
    Unfetched candidates need allow_unfetched=True (factcheck still fails)."""
    return service.intel_confirm(
        candidate_id,
        reason=reason,
        company_id=company_id,
        company_name=company_name,
        project_id=project_id,
        industry=industry,
        event_type=event_type,
        project_stage=project_stage,
        occurred_date=occurred_date,
        published_date=published_date,
        location=location,
        investment_amount=investment_amount,
        planned_capacity=planned_capacity,
        partners=partners,
        summary=summary,
        credibility=credibility,
        is_public=is_public,
        notes=notes,
        allow_unfetched=allow_unfetched,
    )


@mcp.tool()
def intel_ignore(candidate_id: int, reason: str | None = None) -> dict:
    """Ignore pending_review or watching candidate."""
    return service.intel_ignore(candidate_id, reason=reason)


@mcp.tool()
def intel_watch(candidate_id: int, reason: str | None = None) -> dict:
    """Move pending_review → watching (观察). List with status=watching to retrieve."""
    return service.intel_watch(candidate_id, reason=reason)


@mcp.tool()
def intel_merge(
    candidate_id: int,
    target_formal_event_id: int,
    reason: str | None = None,
) -> dict:
    """Merge candidate into existing formal_event (add source; status=merged).
    Candidate must be pending_review or watching."""
    return service.intel_merge(
        candidate_id, target_formal_event_id, reason=reason
    )


@mcp.tool()
def intel_learn_source(
    url_or_domain: str,
    name: str = "",
    rss_url: str = "",
    region: str = "",
    priority: str = "B",
    notes: str = "learned via MCP",
) -> dict:
    """Feed/learn a website into prefer list (learned.yaml). Pass domain or URL; optional rss_url."""
    return service.intel_learn_source(
        url_or_domain,
        name=name,
        rss_url=rss_url,
        region=region,
        priority=priority,
        notes=notes,
    )


@mcp.tool()
def intel_taxonomy_list() -> dict:
    """PRD §6 controlled taxonomy: industries / event_types / project_stages.
    Call before intel_confirm to pick valid values; extension is human-only
    (edit taxonomy/registry.yaml), never auto-created by the agent."""
    return service.intel_taxonomy_list()


@mcp.tool()
def intel_dedup_check(candidate_id: int, threshold: float = 0.55, limit: int = 5) -> dict:
    """PRD §4.3 likely-duplicate check (title-similarity heuristic) before confirming."""
    return service.intel_dedup_check(candidate_id, threshold=threshold, limit=limit)


@mcp.tool()
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
) -> dict:
    """企业档案 upsert (PRD §5.1). Matches existing record by name_cn."""
    return service.intel_company_upsert(
        name_cn,
        name_en=name_en,
        name_id=name_id,
        brand=brand,
        parent_company_id=parent_company_id,
        industry=industry,
        cn_hq=cn_hq,
        id_presence=id_presence,
        is_listed=is_listed,
        first_entry_date=first_entry_date,
        website=website,
        summary=summary,
        main_business_id=main_business_id,
    )


@mcp.tool()
def intel_company_list(industry: str | None = None, limit: int = 50) -> dict:
    """企业库检索 (PRD §10 企业库)."""
    return service.intel_company_list(industry=industry, limit=limit)


@mcp.tool()
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
) -> dict:
    """项目档案 upsert (PRD §5.3). Pass project_id to append to an existing timeline."""
    return service.intel_project_upsert(
        project_id=project_id,
        name=name,
        company_id=company_id,
        industry=industry,
        location=location,
        stage=stage,
        investment_amount=investment_amount,
        planned_capacity=planned_capacity,
        partners=partners,
        notes=notes,
    )


@mcp.tool()
def intel_project_list(
    company_id: int | None = None, stage: str | None = None, limit: int = 50
) -> dict:
    """项目库检索 (PRD §10 项目库：项目时间线)."""
    return service.intel_project_list(company_id=company_id, stage=stage, limit=limit)


@mcp.tool()
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
) -> dict:
    """PRD §7.1 dashboard: legacy five blocks + location/source/partner/investment/new-vs-existing.
    location filter uses substring contains."""
    return service.intel_stats(
        industry=industry,
        event_type=event_type,
        project_stage=project_stage,
        company_id=company_id,
        date_from=date_from,
        date_to=date_to,
        public_only=public_only,
        company_limit=company_limit,
        location=location,
    )


@mcp.tool()
def intel_event_add_source(formal_event_id: int, url: str, label: str = "") -> dict:
    """PRD §5.4: attach another source to an already-confirmed event (multi-source
    provenance — 企业稿/政府声明/当地媒体/中国媒体转载 …)."""
    return service.intel_event_add_source(formal_event_id, url, label=label)


@mcp.tool()
def intel_event_sources(formal_event_id: int) -> dict:
    """List all sources attached to a formal event (PRD §5.4)."""
    return service.intel_event_sources(formal_event_id)


@mcp.tool()
def intel_export_events_csv(
    industry: str = "",
    event_type: str = "",
    project_stage: str = "",
    company_id: int | None = None,
    date_from: str = "",
    date_to: str = "",
    public_only: bool = False,
) -> dict:
    """PRD §11.1 Excel import/export: export confirmed formal_events as CSV text
    (Excel opens it directly). Unreviewed candidates are never included."""
    return service.intel_export_events_csv(
        industry=industry,
        event_type=event_type,
        project_stage=project_stage,
        company_id=company_id,
        date_from=date_from,
        date_to=date_to,
        public_only=public_only,
    )


@mcp.tool()
def intel_factcheck_event(formal_event_id: int) -> dict:
    """PRD §9 fact-check panel: catches source-less conclusions, dangling company/
    project references, out-of-taxonomy values, and common stage mislabels. Run
    this before quoting an event in generated content."""
    return service.intel_factcheck_event(formal_event_id)


# --- Prompts: canned action sequences for the workflows tool schemas alone
# don't encode (full detail in docs/agent_playbook.md). ---


@mcp.prompt()
def review_pending_candidates() -> str:
    """审核待审核池的标准流程（PRD §4.3）。"""
    return (
        "请按以下顺序处理待审核候选：\n"
        '1. intel_list(status="pending_review") 取候选列表。\n'
        "2. 对每条候选调用 intel_dedup_check(candidate_id)，若命中疑似重复，"
        "优先判断是否应合并到已有项目/事件而不是新建。\n"
        "3. 决定入库前调用 intel_taxonomy_list() 确认 industry/event_type/"
        "project_stage 的可选值，不要自创分类。\n"
        "4. 调用 intel_confirm(...) 附带结构化字段；不相关则 "
        "intel_ignore(candidate_id, reason=...)。\n"
        "5. 汇总本轮处理结果：入库了几条、忽略了几条、有哪些标记为疑似重复。"
    )


@mcp.prompt()
def analyze_topic(question: str) -> str:
    """自然语言分析标准动作序列（PRD §7.2）。"""
    return (
        f"请按 PRD §7.2 的五步法回答这个问题：{question}\n\n"
        "1. 用 intel_stats(...) 按问题涉及的行业/时间/地区等条件筛选统计。\n"
        "2. 用 intel_list 或查库拿代表性企业和它们的 canonical_url。\n"
        "3. 若涉及具体项目，用 intel_project_list 说明从签约到当前阶段的时间线。\n"
        "4. 结论区分三档，不要混着说：数据直接支持的结论 / 基于数据的推测 / "
        "需要人工进一步核实的判断。\n"
        "5. 把 intel_stats 的结构化结果转成图表或表格呈现，并注明数据局限。"
    )


@mcp.prompt()
def generate_content_with_factcheck(content_type: str, topic: str) -> str:
    """内容生成 + 事实检查标准动作序列（PRD §8/§9）。"""
    return (
        f"请生成一篇「{content_type}」，主题：{topic}。\n\n"
        "1. 用 intel_stats/intel_list 取数据，记下每个引用事实对应的 "
        "formal_event_id。\n"
        "2. 草稿完成后，对草稿里引用到的每一个 formal_event_id 调用 "
        "intel_factcheck_event；ok:false 的先修数据或改措辞，不要跳过硬发。\n"
        "3. 用 intel_event_sources 取每个事件的完整来源列表，附在文末或脚注。\n"
        "4. 明确标注哪些是数据支持的结论、哪些是推测。"
    )


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
