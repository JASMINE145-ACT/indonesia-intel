# Agent Playbook — 中企出海印尼动态情报与分析系统

> **可加载 Skill（优先）**：`.cursor/skills/indonesia-intel/SKILL.md`  
> （包内同源：`indonesia-intel/.cursor/skills/indonesia-intel/`）  
> 本文件是给人 / 非 Cursor 宿主粘贴用的可读副本；改红线或流程时 **先改 Skill，再同步这里**。

给在 Cursor / WorkBuddy 里通过 `indonesia-intel` MCP 工作的 AI 用的操作手册。工具本身
只是能力(23 个 `intel_*` tool），**按什么顺序调、什么时候必须校验**是 PRD 的业务逻辑，
不会自动从工具签名里推出来——Skill / 本 playbook 补这一层。

**WorkBuddy 安装与 MCP 配置（给人看）：** [workbuddy-setup.md](./workbuddy-setup.md)

来源：`查资料prd/中企出海印尼-情报分析系统-PRD.md`。冲突以 PRD 原文为准。

L1 prefer 覆盖面（2026-08-01 lanes）：**12** 源可不靠广搜轮询 — 9 RSS + Kompas（sitemap）+ Detik + Bisnis（listing）。
Lane 归属见 `evidence/discovery-coverage-20260801.md`（SOURCE_LANES）。Watch / Reach / Jina 默认关。
Reach 旁路：`intel_search_social`（需 `INTEL_REACH_ENABLED=1`）只扩社交窄源进 `discovered`，**不**替代 `intel_search`。

**本地 Ops 看板（浏览器）：** `uvicorn` → `http://127.0.0.1:8765/app/#feed`（流水 / 分析汇总 / 审核）。详见包内 `README.md` § Local Ops Dashboard。Agent 仍以 MCP `intel_*` 为主。

## 红线（无条件遵守）

1. **未审核内容不得进分析/内容生成。** `intel_stats` / 分析用列表只读 `formal_events`；
   `pending_review` / `discovered` 不得当分析输入。Confirm 前须向用户展示候选。
2. **不得自创分类。** `industry` / `event_type` / `project_stage` / `source_attribution`
   只能用 `intel_taxonomy_list()` 返回的值；传别的值 `intel_confirm` 会拒绝。
   新增分类是人工编辑 `taxonomy/registry.yaml`，不是 AI 的事。
3. **不得生成无法追溯的结论。** 写数字/案例前先 `intel_factcheck_event`；
   `ok: false` 就不能用。
4. **非公开信息不能被默认成公开。** `intel_manual_add` 的 `is_public_source=False`
   会被 `intel_confirm` 继承（除非显式 `is_public=True`）。不确定时不要改成公开。

## 六环流程 ↔ 工具映射

```
信息源/关键词任务        intel_sources_list / intel_sources_add / intel_learn_source
        ↓
自动搜集 + 临时搜索       intel_poll_sources (L1 rss|sitemap|listing|watch；目前 12 源含 Bisnis listing)
        ↓                → intel_search (L2 Exa∪Tavily；无 L1 配置的源仍靠广搜)
                         intel_manual_add（链接/粘贴文字/无链接手工事件，PRD §4.4）
待审核池（人审）          intel_fetch → intel_list(status="pending_review")
                         可恢复抓取失败仍 pending_review（fetch_status=failed）；无正文不得当内容事实；
                         必须向用户展示完整 open_url，由用户自行打开阅读（可再人工投喂粘贴正文）
                         intel_dedup_check(candidate_id)  ← confirm 前跑一遍
        ↓
结构化入库                intel_confirm(...)  ← 结构化字段 + 受控词表
                         intel_company_upsert / intel_project_upsert
                         intel_event_add_source
        ↓
分析看板 / NL 分析        intel_stats(...)  ← 只覆盖 formal_events
        ↓
内容工作台 + 事实检查       intel_stats/intel_list → intel_factcheck_event → intel_event_sources
```

详细 checklist：Skill 内 [workflows.md](../.cursor/skills/indonesia-intel/workflows.md)。

## 审核一条候选的标准动作序列

1. `intel_list(status="pending_review")` 取候选并向用户展示。
2. 对每条先 `intel_dedup_check(candidate_id)`。
3. 入库前 `intel_taxonomy_list()` 确认受控词。
4. 用户批准后 `intel_confirm(...)`；已知 `company_id` 优先于仅传 `company_name`。
5. 不相关则 `intel_ignore(candidate_id, reason=...)`。

## 自然语言分析（PRD §7）

§7 拆成独立 skill（主 skill 路由）：

| 小节 | Skill | 要点 |
|------|--------|------|
| §7.1 看板 | `indonesia-intel-dashboard` | IN-SCOPE / DEFERRED 已锁定；缺指标只写局限不编造 |
| §7.2 NL 分析 | `indonesia-intel-nl-analysis` | 每步对应具名 `intel_*` |
| §7.3 对比 | `indonesia-intel-compare` | BLOCKED 维度走 Fallback，禁止假分布 |
| §7.4 趋势异常 | `indonesia-intel-signals` | 7 类信号全覆盖或标「非信号」 |

结论一律分三档：数据支持 / 推测 / 待核实。

## 内容生成（PRD §8/§9）

草稿引用的每个 `formal_event_id` 必须 `intel_factcheck_event` 通过，并附 `intel_event_sources`。

## 导出（PRD §11.1）

`intel_export_events_csv` 只导出已确认事件；无 CSV 导入（库质量优先于数量）。
