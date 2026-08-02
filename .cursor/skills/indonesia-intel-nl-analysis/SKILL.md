---
name: indonesia-intel-nl-analysis
description: "PRD §7.2 natural-language analysis for indonesia-intel. Runs filter→share→firms→timelines→changes→limits→charts→draft. Triggers: 分析布局, 自然语言分析, 上半年, 中资汽车, 印尼布局, analyze topic, NL analysis."
---

# Indonesia Intel — NL Analysis (§7.2)

Example:「分析 2026 年上半年中资汽车企业在印尼的布局。」

## HARD-GATE

```text
<HARD-GATE>
1. Only formal_events / intel_stats / confirmed-backed lists.
2. Every numeric claim → cite the tool result that produced it.
3. Conclusions MUST use three tiers.
4. Do NOT skip 数据局限.
5. Factcheck ok:false → refuse final claim; partial draft only if user asks, mark 需核实.
</HARD-GATE>
```

## PRD pipeline → MCP

| # | PRD step | MCP / action |
|---|----------|----------------|
| 1 | 筛选 | filters + `intel_taxonomy_list` |
| 2 | 汇总占比 | `intel_stats` |
| 3 | 代表企业 | ranking / `intel_company_list` |
| 4 | 项目时间线 | `intel_project_list` |
| 5 | 提炼变化 | 2nd `intel_stats` or 推测 |
| 6 | 数据局限 | always |
| 7 | 出图 | host charts |
| 8 | 文章初稿 | draft → `intel_factcheck_event` → `intel_event_sources` |

## Checklist

Tick steps 1–8 above in order.

## Three-tier labels (MUST)

- **数据直接支持 / 基于数据的推测 / 需进一步核实**

## Scripts

```bat
python .cursor\skills\indonesia-intel-nl-analysis\scripts\smoke.py
```

## Evidence output

`evidence/analysis-YYYYMMDD-nl.md`

## Handoff

- Need raw 看板 first → **`indonesia-intel-dashboard`** then return here  
- Pure 对比 → **`indonesia-intel-compare`**  
- 异常信号 → **`indonesia-intel-signals`**  
- 定稿写作加深 → parent Checklist D（content + factcheck）

## Examples

See [examples.md](examples.md).

## Rollback

Remove this skill folder only.
