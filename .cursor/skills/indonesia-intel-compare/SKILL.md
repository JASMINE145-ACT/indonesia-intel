---
name: indonesia-intel-compare
description: "PRD §7.3 comparative analysis for indonesia-intel via paired intel_stats calls. Triggers: 对比, 同比, 环比, 上下半年, 行业对比, 签约vs投产, 爪哇vs, compare, YoY, vs."
---

# Indonesia Intel — Comparative Analysis (§7.3)

Paired `intel_stats` + agent diff. No compare MCP.

## HARD-GATE

```text
<HARD-GATE>
Same metrics both sides. Never invent region/park/brand/size series.
Three-tier labels required. BLOCKED → Fallback policy (no silent fake %).
</HARD-GATE>
```

## Cohort support

| Type | Support |
|------|---------|
| 年同比、上下半年、行业、签约vs投产、企业vs企业 | **SUPPORTED** |
| 爪哇vs其他、园区、中外品牌、大中小 | **BLOCKED** |

## Fallback (BLOCKED)

1. Say blocked  2. Offer SUPPORTED proxy  3. Qualitative only → all 需核实  4. Never invent %

## Checklist

1. Classify A/B  2. Fallback if BLOCKED  3. Two `intel_stats`  4. Diff + tiers  5. Evidence file

## Scripts

```bat
python .cursor\skills\indonesia-intel-compare\scripts\smoke.py
```

## Evidence output

`evidence/analysis-YYYYMMDD-compare.md`

## Handoff

- Need baseline numbers → **`indonesia-intel-dashboard`**  
- Open narrative after compare → **`indonesia-intel-nl-analysis`**  
- Spikes in one side → **`indonesia-intel-signals`**

## Examples

See [examples.md](examples.md).

## Rollback

Remove this skill folder only.
