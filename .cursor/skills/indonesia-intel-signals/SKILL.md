---
name: indonesia-intel-signals
description: "PRD §7.4 trend and anomaly signals for indonesia-intel. Heuristics over intel_stats monthly_trend, rankings, and project timelines. Triggers: 趋势, 异常, 激增, 扎堆, 长期无后续, 扩产, 退出, anomaly, signal, spike."
---

# Indonesia Intel — Trends & Anomaly Signals (§7.4)

Heuristic probes; machine list in [data/probes.json](data/probes.json) (7 PRD types).

## HARD-GATE

```text
<HARD-GATE>
Every signal tagged 数据直接支持 | 基于数据的推测 | 需进一步核实.
No pending_review spikes. Untestable probes → 非信号 / 需核实 — never fabricate.
</HARD-GATE>
```

## Probe map

Types 1–7 in `data/probes.json` MUST each appear as 信号 or 非信号 in the run.

## Checklist

1. Wide `intel_stats`  2. Focus `intel_stats`  3. Walk probes 1–7  
4. `intel_project_list` for stalled projects  5. Tiered list + 建议复核  6. Evidence file

## Scripts

```bat
python .cursor\skills\indonesia-intel-signals\scripts\smoke.py
```

## Evidence output

`evidence/analysis-YYYYMMDD-signals.md`

## Handoff

- Need distributions first → **`indonesia-intel-dashboard`**  
- Expand into full 布局文 → **`indonesia-intel-nl-analysis`**  
- Quantify A vs B around a signal → **`indonesia-intel-compare`**

## Examples

See [examples.md](examples.md).

## Rollback

Remove this skill folder only.
