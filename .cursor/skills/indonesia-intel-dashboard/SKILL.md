---
name: indonesia-intel-dashboard
description: "PRD §7.1 fixed analytics dashboard for indonesia-intel. Use intel_stats for industry/event_type/project_stage distributions, monthly trend, company ranking. Triggers: 看板, 分布, 统计, dashboard, intel_stats, 行业分布, 月度趋势, 活跃企业."
---

# Indonesia Intel — Fixed Dashboard (§7.1)

Companion to skill `indonesia-intel`. **Data only from confirmed `formal_events`.**

## HARD-GATE

```text
<HARD-GATE>
Do NOT include pending_review / discovered in dashboard numbers.
Do NOT invent metrics the MCP does not return — say "DEFERRED / not in intel_stats".
If filters the user asked for are DEFERRED: still run intel_stats with supported
filters, then list unsupported dimensions under 数据局限 (partial output + disclaimer).
Do NOT refuse the whole answer solely because a deferred filter is missing.
</HARD-GATE>
```

## Scope lock (PRD §7.1)

Machine-readable: [data/scope.json](data/scope.json). Human table:

| Item | Status |
|------|--------|
| 行业 / 动态类型 / 项目阶段 / 月度趋势 / 活跃企业排名 | **IN-SCOPE** |
| 地区分布 + `location` contains 筛选 | **IN-SCOPE** |
| 来源 / 合作方 / 投资有无+原文 TopN / 新增vs存量 | **IN-SCOPE** |
| 筛选：时间、行业、企业、动态类型、项目阶段、是否可公开 | **IN-SCOPE** |
| verified 筛选、金额换算求和、爪哇/园区/品牌本体 | **DEFERRED** |

## When to Apply / Skip

- Apply: 看板数字、分布、排名、月度趋势  
- Skip → narrative / compare / signals skills

## Checklist

1. Map filters → IN-SCOPE; record DEFERRED  
2. `intel_stats(...)`  
3. Present every returned block  
4. **数据局限**  
5. Host chart from JSON  
6. Write evidence file (below)

## Scripts

From package root `indonesia-intel/`:

```bat
python .cursor\skills\indonesia-intel-dashboard\scripts\smoke.py
```

Expect: `OK dashboard` then `OK smoke_section7`.

## Evidence output

Save a short run note to:

`evidence/analysis-YYYYMMDD-dashboard.md`

(template key in `data/scope.json`).

## Handoff

- User wants 叙事/布局分析 → load **`indonesia-intel-nl-analysis`**  
- User wants A vs B → **`indonesia-intel-compare`**  
- User wants 异常/趋势 → **`indonesia-intel-signals`**

## Examples

See [examples.md](examples.md).

## Rollback

Delete/rename this skill folder; MCP unchanged.
