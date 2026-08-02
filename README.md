# Indonesia Intel — China→Indonesia outbound intel ingest MVP

Local FastAPI app. **Search defaults to Exa → Tavily → mock** (Brave optional / not required).

UI tokens follow `site/design-system` (Swiss Ledger).

## Local Ops Dashboard（浏览器看板 — agents 请知悉）

本包内置**本地启动的 Ops 看板**（不是 MCP 替代品；给人看流水/详情/§7.1 汇总）。  
配置到 Cursor / Claude Code / 其他 agent 时，请读本节并告知用户可打开浏览器。

| Item | Value |
|------|--------|
| **URL** | `http://127.0.0.1:8765/app/#feed` |
| **Start** | `uvicorn app.main:app --reload --host 127.0.0.1 --port 8765`（cwd = 本目录） |
| **Auth** | Header / UI 填 `X-API-Key`；默认 `dev-local-key`（见 `.env` `API_KEY`） |
| **Static UI** | `web/`（`index.html` · `app.js` · `app.css` · `tokens.css`） |
| **Design** | `design-system/pages/dashboard.md` + Trellis `08-01-indonesia-intel-local-ops-dashboard` |

**Tabs（hash）**

| Hash | Tab | 数据 |
|------|-----|------|
| `#feed` | 流水（默认） | `GET /pipeline/summary` + `GET /candidates` + `GET /candidates/{id}`；详情抽屉；打开原文 |
| `#stats` | 分析汇总 | **仅** `GET /stats` → 已确认 `formal_events`（页内诚实 banner；不含 pending） |
| `#review` | 审核 | 搜索 / fetch / confirm·ignore（原审核台） |

**相关 REST（同样 `X-API-Key`）**

- `GET /pipeline/summary` — 候选 status / discovery_method 计数  
- `GET /candidates/{id}` — 详情（`extracted_text` 最长 50k）  
- `GET /stats` — PRD §7.1 分析块  

**Smoke**

```bat
python scripts\ops_dash_smoke.py
```

证据示例：`evidence/ops-dash-smoke-20260801.md`。  
Agent 路径仍以 MCP `intel_*` 为主；看板用于人工巡检与演示。

## Setup

```bat
cd /d D:\demo1\indonesia-intel
copy .env.example .env
REM put EXA_API_KEY and/or TAVILY_API_KEY in .env
python -m pip install -e ".[dev]"
python -m pytest -q
uvicorn app.main:app --reload --host 127.0.0.1 --port 8765
```

- Health: `http://127.0.0.1:8765/health`
- Ops Dashboard: `http://127.0.0.1:8765/app/#feed`（见上一节）

## Search + review

```bat
python -m jobs.cli_search --query "China Indonesia investment"
python -m jobs.cli_fetch
```

API (header `X-API-Key`):

- `GET /providers`
- `POST /search` — `{ "query": "...", "provider": "exa"|"tavily"|"mock" }`
- `POST /fetch` — discovered → pending_review
- `GET /candidates?status=pending_review`
- `POST /candidates/manual` — PRD §4.4 人工投喂（链接/粘贴文字/无链接手工事件）→ pending_review
- `POST /candidates/{id}/confirm` — accepts structured PRD §5.2 fields (see below) | `.../ignore`
- `GET /candidates/{id}/dedup-check` — PRD §4.3 likely-duplicate heuristic
- `GET /taxonomy` — PRD §6 controlled vocab (industries / event_types / project_stages)
- `GET /stats` — PRD §7.1 dashboard (legacy five blocks + location/source/partner/investment/new-vs-existing; `location` = contains filter)
- `GET/POST /companies`, `GET/POST /projects` — PRD §5.1/§5.3 entity CRUD
- `GET/POST /formal-events/{id}/sources` — PRD §5.4 multi-source provenance (confirm auto-adds the first one)
- `GET /formal-events/{id}/factcheck` — PRD §9 fact-check panel
- `GET /export/events.csv` — PRD §11.1 Excel 导入导出（confirmed events only; Excel opens the CSV directly）

## Data model (PRD §5) & controlled taxonomy (PRD §6)

Confirming a candidate no longer just writes a thin provenance row — `formal_events`
carries the PRD §5.2 企业动态 fields (`industry`, `event_type`, `project_stage`,
`occurred_date`, `location`, `investment_amount`, `partners`, `summary`, `credibility`,
`is_public`, …) plus optional links to `companies` (§5.1) and `projects` (§5.3, one row
per project timeline — pass `project_id` on confirm/`intel_project_upsert` to append
instead of forking a new project). Confirming a candidate always writes its
`canonical_url` as the event's first `event_sources` row (§5.4); add more with
`intel_event_add_source` / `POST /formal-events/{id}/sources` as corroborating
coverage shows up (企业稿/政府声明/当地媒体/中国媒体转载 …).

Candidates fed in manually (`intel_manual_add` / `POST /candidates/manual`, PRD §4.4)
carry `source_attribution` (公开网络/企业官方/活动现场/商务交流/个人观察/待验证) and
`is_public_source`. Confirming without an explicit `is_public` inherits that flag
instead of defaulting to public — a candidate marked non-public at intake stays
non-public in `formal_events` unless a human overrides it at confirm time.

No Alembic here (Phase-1 scaffold) — `init_db()` additively patches an existing
SQLite file with any columns a model gained since it was created (see
`app/db.py::_add_missing_columns`), so pulling this branch onto a populated
`data/intel.db` won't need a manual migration step.

`industry` / `event_type` / `project_stage` are validated against
[`taxonomy/registry.yaml`](taxonomy/registry.yaml) — confirm/upsert calls raise
`ValueError` for values outside it. This is the *only* sanctioned way to extend the
vocabulary (PRD §6: "AI 不得随意创造大量新类"): edit the YAML by hand, same pattern as
`sources/registry.yaml`. There is intentionally no "AI auto-add category" tool.

## MCP (Cursor / WorkBuddy)

```bat
cd /d D:\demo1\indonesia-intel
python -m pip install -e ".[dev]"
python -m mcp_server
```

Cursor / WorkBuddy `mcp.json` fragment:

```json
{
  "mcpServers": {
    "indonesia-intel": {
      "command": "python",
      "args": ["-m", "mcp_server"],
      "cwd": "D:\\demo1\\indonesia-intel"
    }
  }
}
```

Tools (24), grouped by PRD stage:

- **发现 §4**: `intel_providers`, `intel_sources_list` / `add` / `set_enabled`, `intel_poll_sources` (L1 **rss \| sitemap \| listing**), `intel_search` (L2 Exa∪Tavily + query expand), `intel_search_social` (Agent Reach；`INTEL_REACH_ENABLED=1`；默认关), `intel_fetch` (soft-pending + `retry_failed`), `intel_learn_source`
- **人工投喂 §4.4**: `intel_manual_add` (link / pasted text / no-URL), `intel_manual_add_pdf` (local PDF → pending_review)
- **审核 §4.3**: `intel_list`, `intel_dedup_check`, `intel_confirm`, `intel_ignore`, `intel_watch`, `intel_merge` (→ existing formal_event)
- **入库 §5/§6**: `intel_taxonomy_list`, `intel_company_upsert` / `intel_company_list`, `intel_project_upsert` / `intel_project_list`, `intel_event_add_source` / `intel_event_sources` (§5.4 多来源)
- **分析 §7 / 事实检查 §9**: `intel_stats`, `intel_factcheck_event`
- **导出 §11.1**: `intel_export_events_csv` (confirmed events only; CSV opens directly in Excel)

`intel_confirm` / `intel_company_upsert` / `intel_project_upsert` reject any
`industry` / `event_type` / `project_stage` value outside `taxonomy/registry.yaml` —
call `intel_taxonomy_list()` first to see the allowed values. Content generation
and NL analysis (§7.2/§8) intentionally have no dedicated tool: feed `intel_stats`
+ `intel_list` (both carry `canonical_url` for citations) into the host chat model.

Prefer pool: `sources/registry.yaml` + `sources/learned.yaml`. Keys stay in `.env` only.

### L1 discovery coverage (prefer poll)

`intel_poll_sources` now covers **12** configured prefer sources without 广搜:

| Mode | Sources |
|------|---------|
| **RSS** (9) | antara, antara_id, kontan_en, kr36_overseas, tempo_en, cnbc_indonesia, cnn_indonesia, bbc_indonesia, scmp |
| **Sitemap** | kompas (`sitemap.xml`, zero-hit → listing fallback) |
| **Listing** | detik (`news.detik.com/berita`); **bisnis** (homepage `/read/` links) |
| **Watch** | opt-in `INTEL_DISCOVERY_WATCH` (default off) |

Still search-first: reuters, exchanges / BKPM / parks, etc. Lane ownership: SOURCE_LANES in coverage doc.

Snapshot + live evidence: [`evidence/discovery-coverage-20260801.md`](evidence/discovery-coverage-20260801.md).

```bat
python -m jobs.cli_discovery_live_smoke --limit 3
python scripts\live_crawl_demo.py
```

### Getting the agent to follow PRD logic, not just call tools

**Plugin = MCP + Skill.** Tool schemas encode capability, not sequencing or red
lines. Loadable skill (Awesome-style process gate):

| Layer | Path | Role |
|-------|------|------|
| **Skill (primary)** | `.cursor/skills/indonesia-intel/SKILL.md` | Hard-gates + checklists A–E; Cursor auto-discover |
| Package copy | `indonesia-intel/.cursor/skills/indonesia-intel/` | Ships with the plugin |
| Playbook twin | `docs/agent_playbook.md` | Human / WorkBuddy paste when skills unavailable |
| MCP `instructions` | `mcp_server/server.py` | Handshake condensed red lines |
| Cursor rule | `.cursor/rules/indonesia-intel.mdc` | Always-on reminder in this repo |

Invoke: ask the agent to use skill `indonesia-intel`, or trigger via keywords
(搜印尼情报 / 待审核 / `intel_confirm` / 中企出海…). Details: skill
`workflows.md`.

**PRD §7 analysis skills** (split; parent routes to them):

| Skill | PRD | Extras |
|-------|-----|--------|
| `indonesia-intel-dashboard` | §7.1 | `data/scope.json`, `examples.md`, `scripts/smoke.py` |
| `indonesia-intel-nl-analysis` | §7.2 | `examples.md`, smoke |
| `indonesia-intel-compare` | §7.3 | `examples.md`, smoke |
| `indonesia-intel-signals` | §7.4 | `data/probes.json`, `examples.md`, smoke |

Smoke all §7 contracts (from `indonesia-intel/`):

```bat
python .cursor\skills\indonesia-intel\scripts\smoke_section7.py
```

Evidence notes: `evidence/analysis-YYYYMMDD-<dashboard|nl|compare|signals>.md`.

Plus 3 MCP **prompts** (`review_pending_candidates`, `analyze_topic`,
`generate_content_with_factcheck`) — canned sequences for clients that support
MCP prompts.

## Add a new prefer source (extension kit)

Do **not** write a per-site crawler. Extend via config + the same search→fetch→blob path.

1. Copy fields from [`sources/SOURCE_TEMPLATE.yaml`](sources/SOURCE_TEMPLATE.yaml) into `sources/registry.yaml` (or use MCP `intel_sources_add` → `learned.yaml`).
2. Smoke one source:

```bat
REM unit/mock path is covered by pytest; live smoke needs a real provider:
python -m jobs.cli_source_smoke --source-id antara --provider exa --out evidence\smoke-antara.json
python -m jobs.cli_source_smoke --source-id antara --provider tavily --out evidence\smoke-antara-tavily.json
```

3. Interpret `pipeline` / `outcomes`: `ok` | `empty` | `cert` | `dns` | `waf` | `paywall` | `fetch_fail` | `no_hits`.
4. If L1 often fails on CF/WAF/JS: set `fetch_l2: true` and `fetch_l2_mode` (`http`|`dynamic`|`stealthy`).
5. If `*.go.id` cert/geo issues: set `PROXY_URL` (Indonesian SOCKS/HTTP). **Never** `verify=False`.

Contract: `WANd.INTEL.SOURCE_EXTEND.001`.

## Fetch ladder (failure-reason routing)

| Layer | Stack | When |
|-------|--------|------|
| **Social stub** | hostname policy | Instagram / Facebook → `social_unsupported` (no escalate) |
| **L1** | httpx + Trafilatura + SSRF + status reclass | Default |
| **L1.5** | Scrapling `Fetcher` (curl_cffi) | L1 eligible fail; **no** L2 allowlist; `INTEL_FETCH_L15` (default on) |
| **L2** | Scrapling `Dynamic` / `Stealthy` (or `http` if L1.5 skipped) | L1.5 fail **and** source `fetch_l2: true` + allowlist |
| **Jina** | `r.jina.ai` markdown (no Trafilatura) | Fail-only after L1→L1.5→L2; eligible typed errors; **once per URL**; `INTEL_FETCH_JINA_FALLBACK` (**default off**); optional `JINA_API_KEY` |
| **PDF queue** | async native extract (no OCR) | Sync `pdf_too_large` → `pdf_queued` when `INTEL_PDF_QUEUE_ENABLED` (default on); `python -m jobs.cli_pdf_queue` |
| **Breaker** | in-batch per-host | After N escalation fails → `circuit_open` (fetch_failed; retryable next run) |

```bat
python -m pip install -e ".[dev,fetch-l2]"
scrapling install
REM disable layers:
set INTEL_FETCH_L15=0
set INTEL_FETCH_L2=0
set INTEL_FETCH_CIRCUIT_BREAKER=0
set INTEL_FETCH_HTTP_RECLASS=0
set INTEL_FETCH_JINA_FALLBACK=0
python scripts\live_fetch_smoke.py
```

Flags are env-first (no restart needed for the reader helpers). L1.5/L2 never use `verify=False`; browser modes remain allowlist-only. Redirect control on L1.5 is **fail-closed**. Jina never runs for `http_401` / social / `pdf_too_large` / SSRF / robots; 429 → `jina_rate_limited` (still marks `jina_attempted`). With `run_id`, diagnostics append to `evidence/fetch-diagnostics-{run_id}.jsonl` (includes `jina` step). Ops `GET /pipeline/summary` exposes `lanes.discovery` / `lanes.fetch` / `lanes.document` (document_jobs from `document_jobs` table; PDF queue via `INTEL_PDF_QUEUE_ENABLED`).

Evidence: `evidence/live-fetch-smoke.json`, `evidence/ai-market-fetch-failure-analysis-20260801.md`.

## Design

- Tokens: `web/tokens.css` ← `site/design-system/tokens.css`
- Page notes: `design-system/pages/dashboard.md` (ui-ux-pro-max density; Swiss Ledger colors)
