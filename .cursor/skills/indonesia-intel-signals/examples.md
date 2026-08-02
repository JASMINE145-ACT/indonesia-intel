# Examples — indonesia-intel-signals (§7.4)

## Example 1 — anomaly scan

**User:**「最近有没有异常信号？」

**Tool sequence:**
1. `intel_stats()` wide window (baseline)
2. `intel_stats(date_from=recent, date_to=...)` focus window
3. Walk probes 1–7 from `data/probes.json` (hit / 非信号 / 无法测)
4. `intel_project_list` for type #3 长期无后续
5. Output 信号列表 with tiers + 建议复核 ids

**Evidence path:** `evidence/analysis-YYYYMMDD-signals.md`

**Fail if:** 把地区扎堆标成「数据直接支持」且带假 %；或漏掉某 type 不说明

---

## Example 2 — single type focus

**User:**「有没有行业突发激增？」

**Tool sequence:** focus probe #1 with two `intel_stats` windows; still list other types under 非信号 if not evaluated in depth
