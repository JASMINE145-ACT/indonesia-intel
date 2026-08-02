# Indonesia Intel — Workflow Details

Companion to [SKILL.md](SKILL.md). Read when executing a specific checklist.

## Discovery cascade

```text
prefer registry (L0)
  → intel_poll_sources   # L1 rss | sitemap | listing | watch (12: + bisnis; watch flag-off)
  → intel_search         # L2 Exa → Tavily → mock (no-feed / non-L1 sources)
  → intel_fetch          # L1 httpx → L1.5 curl_cffi → optional L2 Scrapling → optional Jina (flag off) (+ breaker)
  → pending_review
```

- Coverage snapshot: `indonesia-intel/evidence/discovery-coverage-20260801.md`.
- Do not pass API keys in tool args; keys live in `.env` only.
- Prefer `source_id` on search when targeting one domain.
- After fetch, report ok / empty / waf / cert / fetch_fail style outcomes if present.
- Detik listing must use article cards + `/berita/d-` filter (never bare `li` in `item_selector`).

## Review card (what to show the user)

1. `intel_list(status="pending_review")` — default **excludes** `watching` / `merged`
2. Prefill for **shown ids only** (cap ≤10; **not persisted**):
   - call `intel_taxonomy_list()` once
   - per id: `intel_dedup_check`
   - propose industry / event_type / project_stage from title+snippet — mark「建议非落库」
3. For each card present at least:
   - `id`, title, **full `open_url`** (prefer over truncated display), source / provider, snippet
   - if `unfetched` / `fetch_status=failed`: paste the complete URL + `user_hint`
     (user opens the link themselves; do not invent body text)
   - dedup hits (formal_event / pending)
   - draft structured suggestions (never auto-confirm)
4. User actions:
   - confirm → `intel_confirm` with **user-approved** fields
   - ignore → `intel_ignore`
   - watch → `intel_watch` (retrieve via `intel_list(status="watching")`)
   - merge into existing event → `intel_merge(candidate_id, target_formal_event_id)`

Wait for explicit user decision per item or approved batch.

## Confirm field notes

From PRD §5.2 — pass what you know; empty strings ok for unknowns:

- `company_name` or `company_id`
- `industry` / `event_type` / `project_stage` — **taxonomy only**
- `occurred_date` / `published_date` / `location`
- `investment_amount` / `planned_capacity` / `partners`
- `summary` / `credibility` / `notes`
- `is_public` — leave unset to inherit intake flag

## Analyze (§7) — child skills

| PRD | Skill | Scope note |
|-----|--------|------------|
| §7.1 固定看板 | `indonesia-intel-dashboard` | IN-SCOPE vs DEFERRED locked in that skill |
| §7.2 自然语言分析 | `indonesia-intel-nl-analysis` | Each PRD step → named `intel_*` |
| §7.3 对比分析 | `indonesia-intel-compare` | BLOCKED cohorts → Fallback policy |
| §7.4 趋势与异常 | `indonesia-intel-signals` | All 7 PRD types must be hit or 非信号 |

Three-tier labels mandatory in nl-analysis / compare / signals.
Never invent DEFERRED series — partial + 数据局限.
Parent HARD-GATE §6 = failure triage (partial vs refuse).

Smoke: `python .cursor/skills/indonesia-intel/scripts/smoke_section7.py`  
Evidence: `evidence/analysis-YYYYMMDD-<kind>.md`  
Examples + handoff: each child skill `examples.md` / Handoff section.

## Content factcheck loop

```text
draft → for each formal_event_id:
          intel_factcheck_event
          if not ok → fix data or wording → re-check
      → intel_event_sources for citations
      → deliver
```

## Export

`intel_export_events_csv` = confirmed only. No CSV import by design (quality > volume).

## Human-readable twin

`indonesia-intel/docs/agent_playbook.md` mirrors this skill for hosts that cannot load Cursor skills (e.g. paste into WorkBuddy system prompt). Prefer this skill when available; keep both in sync when changing red lines.
