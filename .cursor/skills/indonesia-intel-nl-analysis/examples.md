# Examples — indonesia-intel-nl-analysis (§7.2)

## Example 1 — layout analysis

**User:**「分析 2026 年上半年中资汽车企业在印尼的布局」

**Tool sequence:**
1. `intel_taxonomy_list()` — map「汽车」→ controlled industry
2. `intel_stats(industry=..., date_from="2026-01-01", date_to="2026-06-30")`
3. Read `company_ranking` → pick top firms
4. `intel_project_list(company_id=...)` for timelines
5. Optional 2nd `intel_stats` for 2025 H1 change
6. If 初稿: draft → each cite `intel_factcheck_event(formal_event_id)` → `intel_event_sources`

**Qualified sections:** 筛选 → 汇总占比 → 代表企业 → 时间线 → 变化 → 数据局限 → 图 → 初稿  
**Tiers:** 数据直接支持 / 基于数据的推测 / 需进一步核实

**Evidence path:** `evidence/analysis-YYYYMMDD-nl.md`

**Fail if:** 跳过数据局限；数字无法追溯到 tool 结果

---

## Example 2 — draft with factcheck gate

**User:**「根据上面分析写 800 字初稿并引用事件」

**Tool sequence:** after stats/projects → draft → `intel_factcheck_event` per id → only ok:true claims stay as 数据直接支持
