---
name: indonesia-intel
description: "Operate the indonesia-intel MCP plugin for 中企出海印尼情报：搜索发现、抓取落库、人审确认、结构化入库、路由到分析子 skill、事实检查与内容生成。MUST use when calling intel_* tools, reviewing candidates, confirming events, or writing from the intel DB. For §7 analysis prefer child skills: indonesia-intel-dashboard, indonesia-intel-nl-analysis, indonesia-intel-compare, indonesia-intel-signals. Triggers: indonesia-intel, intel_search, intel_confirm, 待审核, 印尼情报, 中企出海, formal_events."
---

# Indonesia Intel — MCP Workflow Skill

Plugin contract: **MCP tools = capability**; **this skill = sequencing + red lines**（PRD 业务逻辑）。

Package root: `indonesia-intel/`. Conflict → `查资料prd/中企出海印尼-情报分析系统-PRD.md`.

## When to Apply

### Must Use

- Any `intel_*` MCP tool call
- Keyword / prefer-source discovery → fetch → local store
- Human review of `pending_review` candidates
- Confirm / ignore / structured event ingest
- Stats, NL analysis, article drafts from the intel DB
- Manual intake (link / paste / no-URL event)

### Skip

- Editing indonesia-intel Python internals with no MCP workflow
- Pure infra / pytest unrelated to review or analysis
- Tasks that never touch candidates, formal events, or intel MCP

## HARD-GATE

```text
<HARD-GATE>
1. Do NOT treat pending_review / discovered as analysis input.
   Only formal_events (post-confirm) feed intel_stats / content / export.
2. Do NOT invent industry / event_type / project_stage / source_attribution.
   Values MUST come from intel_taxonomy_list(); else intel_confirm rejects.
3. Do NOT quote a number/case in content until intel_factcheck_event(id) is ok.
4. Do NOT flip is_public to True when unsure; inherit manual intake flags.
5. Do NOT intel_confirm without presenting the candidate to the user first
   (unless the user already approved that specific id / batch).
6. Do NOT pass skill-layer taxonomy/dedup *suggestions* into intel_confirm
   unless the user explicitly approved those values.
7. Failure triage:
   - Missing/DEFERRED metric or filter → partial answer + 数据局限 (do not invent).
   - Factcheck ok:false → refuse to treat that claim as final; fix or drop.
   - Conflicting sources → present both + 需进一步核实; do not pick silently.
   - MCP tools unavailable → stop and tell user to fix mcp.json (no fake data).
8. Do NOT use candidates with fetch_status=failed / empty object_key as content facts.
   Soft-pending (pending_review + fetch failed) is for human triage only.
   Default intel_confirm rejects unfetched; allow_unfetched still fails factcheck.
   When fetch fails: ALWAYS show the user the full `open_url` (never truncate /
   paraphrase the link). Tell them to open it themselves; offer manual paste via
   intel_manual_add if they want the body in-queue.
</HARD-GATE>
```

## Prerequisites

1. MCP server `indonesia-intel` connected (`python -m mcp_server`, cwd = package root).
2. If tools missing: stop and tell the user to configure mcp.json (see package README).

## Route by Intent

| User intent | Workflow | Start |
|-------------|----------|--------|
| 搜 / 发现 / 关键词 / 扫源 | Discovery | Checklist A |
| 审 / 入库 / 忽略 / 待审核 | Review | Checklist B |
| 看板 / 分布 / 统计 | §7.1 | **Load skill `indonesia-intel-dashboard`** |
| 自然语言分析 / 布局 | §7.2 | **Load skill `indonesia-intel-nl-analysis`** |
| 对比 / 同比 / A vs B | §7.3 | **Load skill `indonesia-intel-compare`** |
| 趋势 / 异常 / 激增 / 扎堆 | §7.4 | **Load skill `indonesia-intel-signals`** |
| 写文章 / 初稿 / 出内容 | Content | Checklist D |
| 投喂链接/粘贴/无链事件 | Manual | Checklist E |
| 加网站到 prefer | Learn source | `intel_learn_source` / `intel_sources_add` |

Analysis（§7）是 **skill-split**，不是一个 mega-checklist — 读完 child skill 再调工具。

Detailed discovery/review scripts: [workflows.md](workflows.md).

## Checklist A — Discovery

1. Prefer L1: `intel_poll_sources`（可选 `source_ids`）— rss|sitemap|listing|watch；
   当前覆盖 **12** 个源（9 RSS + kompas + detik + bisnis）。见
   `evidence/discovery-coverage-20260801.md`。SOURCE_LANES：Reach ≠ L1/L2；flags 默认关。
   可选：`intel_search_social`（`INTEL_REACH_ENABLED=1` 时）。
2. L2 宽搜：`intel_search(query=...)` — 默认 Exa∪Tavily + CN/EN/ID query expand；
   一个调用一个 `run_id`。传 `provider=` 可强制单一渠道。
3. 抓取：`intel_fetch(run_id=...)` — 可恢复失败保留 `pending_review`，
   `fetch_status=failed`（重试：`intel_fetch(retry_failed=True)`）。
4. 软待审/抓取失败：展示标题 + 完整 `open_url`（来自
   `intel_list` / `intel_fetch.unfetched_for_user`）+ fetch_error_type +
   `user_hint`。不当作正文事实。从不隐藏或缩短链接。
5. 汇总计数；提供审核（Checklist B）— 不自动确认

## Checklist B — Review（human in the loop）

1. `intel_list(status="pending_review")` — **展示给用户**（默认不含 `watching`）
2. 预填（对话内，**不落库**；仅对**本轮展示**的 id，建议 cap≤10）：
   - `intel_taxonomy_list()` 一次
   - 每个展示的 id：`intel_dedup_check(candidate_id)`
   - 草稿行业/动态类型/项目阶段 **建议**从标题+摘要对照 taxonomy — 标为「建议非落库」
3. 展示卡片 + 建议；等待用户决策
   - 如 `unfetched` / `fetch_status=failed`：先给完整可点击 `open_url`
     和 `user_hint`（用户自己打开页面；可选经 Checklist E 粘贴）
4. 如重复指向已有事件：提供 `intel_merge(candidate_id, target_formal_event_id)`
5. 观察：`intel_watch(candidate_id)` — 后续 `intel_list(status="watching")`
6. 确认：`intel_confirm(...)`，用用户选的结构化字段（从不静默应用建议）
7. 拒绝：`intel_ignore(candidate_id, reason=...)`

## Checklist C — Analyze（PRD §7）— 路由

不要在这里自己发挥 §7。加载恰好一个 child skill：

1. 数字 / 看板 → `indonesia-intel-dashboard`
2. 开放式分析叙事 → `indonesia-intel-nl-analysis`
3. 对比 → `indonesia-intel-compare`
4. 趋势异常 → `indonesia-intel-signals`

（如果用户混合意图，先跑 dashboard，再跑对应的 narrative/compare/signals skill。）

## Checklist D — Content（PRD §8/§9）

1. 通过 `intel_stats` + list 拉事实；记录每个 `formal_event_id`
2. 初稿
3. 每个引用的 id → `intel_factcheck_event`；修正后再发
4. 通过 `intel_event_sources` 附上来源

## Checklist E — Manual intake（PRD §4.4）

1. 链接 / 粘贴 / 无链事件：`intel_manual_add(title, url=..., text=..., source_attribution=..., is_public_source=...)`
2. 仅本地 PDF：`intel_manual_add_pdf(path, ...)`（Excel/Word/图片延后）
3. 仍落入 `pending_review` → Checklist B

## Quick Tool Map

```text
sources     intel_sources_list / add / set_enabled / intel_learn_source
discover    intel_poll_sources → intel_search → intel_fetch
review      intel_list → dedup+taxonomy 建议 → intel_confirm | intel_ignore | intel_watch | intel_merge
intake      intel_manual_add | intel_manual_add_pdf
entities    intel_taxonomy_list / company_* / project_* / event_*source*
analyze     intel_stats
content     intel_factcheck_event → intel_event_sources
export      intel_export_events_csv（confirmed only）
```

## Anti-Patterns

- 调用 `intel_confirm` 但未给用户展示
- 在分析文案里用未确认候选
- 自创 taxonomy 标签
- 发布数字前跳过 `intel_factcheck_event`
- 用户说“看看板/流水/详情”时忽略本地 Ops Dashboard — 指引到 `http://127.0.0.1:8765/app/#feed`（见包 `README.md` § Local Ops Dashboard）；MCP `intel_*` 仍是 agent 路径
- 编造 DEFERRED §7.1 序列（投资/地区/合作方/来源/新增vs存量）

## Local Ops Dashboard（browser）

与 MCP 并存。从本包根目录：

```bat
uvicorn app.main:app --reload --host 127.0.0.1 --port 8765
```

打开 `http://127.0.0.1:8765/app/#feed` — 标签 `#feed` · `#stats` · `#review`。  
完整表格：`README.md` § Local Ops Dashboard。

## Scripts / smoke

从包根目录：

```bat
python .cursor\skills\indonesia-intel\scripts\smoke_section7.py
python scripts\ops_dash_smoke.py
```

每个 skill 的封装在各自 `scripts/smoke.py`。见 [examples.md](examples.md)。
## Evidence

分析运行应留下简短记录在 `evidence/analysis-YYYYMMDD-<kind>.md`
（`dashboard` | `nl` | `compare` | `signals`）。

## Rollback / disable a skill

Skills 是 `.cursor/skills/<name>/` 下的文件。禁用某个分析模式：删除或重命名该目录（以及包内镜像
`indonesia-intel/.cursor/skills/`）。MCP 服务器无需变。优先单独回滚某个 §7 子项 — 不要为了一个子项挖空父 skill。
