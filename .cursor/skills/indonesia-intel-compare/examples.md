# Examples — indonesia-intel-compare (§7.3)

## Example 1 — SUPPORTED (H1 vs H1)

**User:**「对比 2025 H1 与 2026 H1 汽车行业事件量」

**Tool sequence:**
1. `intel_taxonomy_list` if needed
2. `intel_stats(industry=..., date_from="2025-01-01", date_to="2025-06-30")`
3. `intel_stats(industry=..., date_from="2026-01-01", date_to="2026-06-30")`
4. Diff table on shared keys

**Evidence path:** `evidence/analysis-YYYYMMDD-compare.md`

**Fail if:** 两侧指标字段不一致却硬比

---

## Example 2 — BLOCKED (region / park)

**User:**「对比爪哇与苏门答腊园区」

**Tool sequence:** **no fake region stats**
1. State BLOCKED: no region/park dimension in `intel_stats`
2. Offer SUPPORTED proxy（行业 / 阶段 / 时间窗）
3. If user insists on qualitative: scan confirmed `location` text only → all claims 需进一步核实

**Fail if:** 编造园区分布百分比
