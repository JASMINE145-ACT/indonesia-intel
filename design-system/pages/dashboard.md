# Design overrides — Indonesia Intel Ops Dashboard (tabs)

> Parent product lock: Swiss Ledger / `web/tokens.css`  
> Full IA + wireframes: `.trellis/tasks/查资料/08-01-indonesia-intel-local-ops-dashboard/research/ops-dashboard-design.md`  
> ui-ux-pro-max Financial-blue dump under `design-system-ops/` is **reference only**.

## Overrides vs ui-ux-pro-max MASTER

| Token | ui-ux-pro-max | This product |
|-------|---------------|--------------|
| Primary / Accent | Blue `#1E40AF` / amber CTA | `#0f1b2d` / gold `#c9a227` |
| Fonts | Fira | Inter + IBM Plex Mono |
| Default theme | often dark ops | **light** first |
| Charts | mixed | **CSS bar + table**; no pie-only |
| Pattern | marketing ops | **Tabs: 审核 · 流水 · 分析汇总** |

## Page contract (ops)

1. Topbar: brand + API Key + theme  
2. Tablist default **`#feed`（流水）**  
3. 流水: KPI strip → filters → list → detail drawer；打开原文 http(s) only  
4. 分析汇总: honesty banner → `/stats` only → bars/tables  
5. 审核: existing confirm loop preserved  
6. XSS: never `innerHTML` for body/snippet  
