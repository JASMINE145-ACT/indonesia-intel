# Examples — indonesia-intel-dashboard (§7.1)

## Example 1 — in-scope only

**User:**「给我当前库的行业分布和活跃企业 Top10」

**Tool sequence:**
1. `intel_stats(company_limit=10)`

**Qualified output excerpt:**
```markdown
## 看板摘要
- 筛选：（无）
- 行业分布：…（来自 industry_distribution）
- 活跃企业 Top N：…（来自 company_ranking）
## 数据局限
- 未请求 DEFERRED 维度
```

**Evidence path:** `evidence/analysis-YYYYMMDD-dashboard.md`

**Fail if:** 编造投资金额分布；或用 pending_review 计数

---

## Example 2 — deferred filter asked

**User:**「按爪哇地区筛一下行业分布」

**Tool sequence:**
1. `intel_stats()` （无 region 参数 — 不存在）
2. 在 数据局限 写明 `filters.project_location` = DEFERRED

**Fail if:** 假装已按爪哇过滤并给出假占比
