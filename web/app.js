const KEY_STORAGE = "indonesia-intel.apiKey";
const THEME_STORAGE = "indonesia-intel.theme";
const AUTO_FETCH_STORAGE = "indonesia-intel.autoFetch";

const TAB_IDS = ["feed", "stats", "review"];

const els = {
  apiKey: document.getElementById("api-key"),
  saveKey: document.getElementById("btn-save-key"),
  theme: document.getElementById("btn-theme"),
  banner: document.getElementById("banner"),
  tabs: [...document.querySelectorAll(".tab[data-tab]")],
  panels: {
    feed: document.getElementById("panel-feed"),
    stats: document.getElementById("panel-stats"),
    review: document.getElementById("panel-review"),
  },
  feedKpis: document.getElementById("feed-kpis"),
  feedList: document.getElementById("feed-list"),
  feedCount: document.getElementById("feed-count"),
  feedPills: [...document.querySelectorAll("#feed-pills .pill[data-status]")],
  feedRefresh: document.getElementById("btn-feed-refresh"),
  drawer: document.getElementById("feed-drawer"),
  scrim: document.getElementById("drawer-scrim"),
  drawerClose: document.getElementById("btn-drawer-close"),
  drawerTitle: document.getElementById("drawer-title"),
  drawerMeta: document.getElementById("drawer-meta"),
  drawerUnfetchedHint: document.getElementById("drawer-unfetched-hint"),
  drawerUrl: document.getElementById("drawer-url"),
  drawerBody: document.getElementById("drawer-body"),
  drawerTrunc: document.getElementById("drawer-trunc"),
  openArticle: document.getElementById("btn-open-article"),
  statsForm: document.getElementById("stats-form"),
  statsRoot: document.getElementById("stats-root"),
  statsEmpty: document.getElementById("stats-empty"),
  gotoReview: document.getElementById("btn-goto-review"),
  searchForm: document.getElementById("search-form"),
  query: document.getElementById("query"),
  provider: document.getElementById("provider"),
  autoFetch: document.getElementById("auto-fetch"),
  btnSearch: document.getElementById("btn-search"),
  btnFetch: document.getElementById("btn-fetch"),
  btnRefresh: document.getElementById("btn-refresh"),
  list: document.getElementById("list"),
  count: document.getElementById("result-count"),
  pills: [...document.querySelectorAll("#panel-review .pill[data-status]")],
};

let currentStatus = "pending_review";
let feedStatus = "discovered";
let selectedFeedId = null;
let lastFocusedRow = null;

function apiKey() {
  return (els.apiKey.value || "").trim();
}

function showBanner(message, tone = "info") {
  els.banner.hidden = !message;
  els.banner.dataset.tone = tone;
  els.banner.textContent = message || "";
}

function formatDetail(detail) {
  if (detail == null) return "";
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((d) => (typeof d === "object" ? d.msg || JSON.stringify(d) : String(d)))
      .join("; ");
  }
  if (typeof detail === "object") return detail.msg || JSON.stringify(detail);
  return String(detail);
}

async function api(path, options = {}) {
  const key = apiKey();
  if (!key) throw new Error("请先填写并保存 API Key");
  const headers = {
    "X-API-Key": key,
    ...(options.body ? { "Content-Type": "application/json" } : {}),
    ...(options.headers || {}),
  };
  const res = await fetch(path, { ...options, headers });
  let body = null;
  const text = await res.text();
  if (text) {
    try {
      body = JSON.parse(text);
    } catch {
      body = { detail: text };
    }
  }
  if (!res.ok) {
    throw new Error(formatDetail(body?.detail) || res.statusText || `HTTP ${res.status}`);
  }
  return body;
}

function escapeHtml(s) {
  return String(s)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function escapeAttr(s) {
  return escapeHtml(s).replaceAll("'", "&#39;");
}

function safeHref(url) {
  const raw = String(url || "").trim();
  if (!raw) return "";
  try {
    const u = new URL(raw);
    if (u.protocol === "http:" || u.protocol === "https:") return u.href;
  } catch {
    /* ignore */
  }
  return "";
}

function isUnfetchedItem(item) {
  return Boolean(
    item?.unfetched ||
      item?.fetch_status === "failed" ||
      item?.status === "fetch_failed"
  );
}

function openUrlForItem(item) {
  return String(item?.open_url || item?.url || item?.canonical_url || item?.original_url || "").trim();
}

function statusBadge(status) {
  if (status === "pending_review") return "badge-pending";
  if (status === "confirmed") return "badge-ok";
  if (status === "discovered") return "badge-info";
  if (status === "fetch_failed" || status === "ignored") return "badge-danger";
  return "";
}

/* ---------- Tabs ---------- */

function currentTab() {
  const h = (location.hash || "#feed").replace(/^#/, "");
  return TAB_IDS.includes(h) ? h : "feed";
}

function setTab(name, { pushHash = true } = {}) {
  const tab = TAB_IDS.includes(name) ? name : "feed";
  els.tabs.forEach((btn) => {
    const on = btn.dataset.tab === tab;
    btn.setAttribute("aria-selected", String(on));
  });
  Object.entries(els.panels).forEach(([key, panel]) => {
    if (!panel) return;
    panel.hidden = key !== tab;
  });
  if (pushHash && location.hash !== `#${tab}`) {
    history.replaceState(null, "", `#${tab}`);
  }
  if (tab === "feed") {
    refreshFeed().catch((err) => showBanner(err.message, "error"));
  } else if (tab === "stats") {
    loadStats().catch((err) => showBanner(err.message, "error"));
  } else if (tab === "review") {
    loadList().catch((err) => showBanner(err.message, "error"));
  }
}

els.tabs.forEach((btn) => {
  btn.addEventListener("click", () => setTab(btn.dataset.tab));
});

document.querySelector(".tablist")?.addEventListener("keydown", (e) => {
  const i = els.tabs.findIndex((t) => t.getAttribute("aria-selected") === "true");
  if (e.key === "ArrowRight") {
    e.preventDefault();
    setTab(els.tabs[(i + 1) % els.tabs.length].dataset.tab);
    els.tabs[(i + 1) % els.tabs.length].focus();
  } else if (e.key === "ArrowLeft") {
    e.preventDefault();
    const j = (i - 1 + els.tabs.length) % els.tabs.length;
    setTab(els.tabs[j].dataset.tab);
    els.tabs[j].focus();
  }
});

window.addEventListener("hashchange", () => setTab(currentTab(), { pushHash: false }));

els.gotoReview?.addEventListener("click", () => setTab("review"));

/* ---------- Feed ---------- */

function setFeedFilter(status) {
  feedStatus = status;
  els.feedPills.forEach((p) => p.setAttribute("aria-pressed", String(p.dataset.status === status)));
}

async function loadPipelineKpis() {
  const data = await api("/pipeline/summary");
  const order = [
    ["total", "合计"],
    ["discovered", "已发现"],
    ["pending_review", "待审"],
    ["confirmed", "已确认"],
    ["ignored", "已忽略"],
    ["fetch_failed", "抓取失败"],
  ];
  const counts = data.counts_by_status || {};
  els.feedKpis.innerHTML = order
    .map(([key, label]) => {
      const n = key === "total" ? data.total || 0 : counts[key] || 0;
      const clickable = key !== "total";
      return `<button type="button" class="kpi" data-status="${clickable ? key : ""}" ${clickable ? "" : "disabled"}>
        <span class="kpi-label">${escapeHtml(label)}</span>
        <span class="kpi-value ui-data">${n}</span>
      </button>`;
    })
    .join("");
}

els.feedKpis.addEventListener("click", async (e) => {
  const kpi = e.target.closest(".kpi[data-status]");
  if (!kpi || !kpi.dataset.status) return;
  setFeedFilter(kpi.dataset.status);
  try {
    await loadFeedList();
  } catch (err) {
    showBanner(err.message, "error");
  }
});

function renderFeedItems(items) {
  els.feedCount.textContent = `${items.length} 条`;
  if (!items.length) {
    els.feedList.innerHTML = `<div class="empty">当前筛选下没有候选。</div>`;
    return;
  }
  els.feedList.innerHTML = items
    .map((item) => {
      const sel = item.id === selectedFeedId ? " is-selected" : "";
      return `<article class="item item-compact${sel}" data-id="${item.id}" tabindex="0">
        <div class="item-head">
          <h3 class="item-title">${escapeHtml(item.title || "(untitled)")}</h3>
          <div style="display:flex;gap:0.35rem;flex-wrap:wrap">
            <span class="badge badge-provider ui-data">${escapeHtml(item.provider || "?")}</span>
            <span class="badge ${statusBadge(item.status)}">${escapeHtml(item.status)}</span>
          </div>
        </div>
        <p class="item-snippet">${escapeHtml(item.source_id || "")} · ${escapeHtml(item.discovery_method || "")}</p>
      </article>`;
    })
    .join("");
}

async function loadFeedList() {
  els.feedList.classList.add("is-loading");
  els.feedList.innerHTML = `<div class="skeleton" aria-hidden="true"></div>`;
  try {
    const data = await api(`/candidates?status=${encodeURIComponent(feedStatus)}`);
    els.feedList.classList.remove("is-loading");
    renderFeedItems(data.items || []);
  } catch (err) {
    els.feedList.classList.remove("is-loading");
    els.feedList.innerHTML = `<div class="empty">加载失败：${escapeHtml(err.message)}</div>`;
    throw err;
  }
}

async function refreshFeed() {
  await loadPipelineKpis();
  await loadFeedList();
}

function closeDrawer() {
  els.drawer.hidden = true;
  els.scrim.hidden = true;
  selectedFeedId = null;
  [...els.feedList.querySelectorAll(".item")].forEach((el) => el.classList.remove("is-selected"));
  if (lastFocusedRow) lastFocusedRow.focus();
}

async function openDrawer(id, rowEl) {
  selectedFeedId = id;
  lastFocusedRow = rowEl || null;
  [...els.feedList.querySelectorAll(".item")].forEach((el) => {
    el.classList.toggle("is-selected", Number(el.dataset.id) === Number(id));
  });
  const detail = await api(`/candidates/${id}`);
  // XSS: textContent / createTextNode only — never innerHTML for body
  els.drawerTitle.textContent = detail.title || "(untitled)";
  els.drawerMeta.textContent = "";
  const chips = [
    detail.status,
    detail.fetch_status,
    detail.provider,
    detail.source_id,
    detail.discovery_method,
  ].filter(Boolean);
  chips.forEach((c) => {
    const span = document.createElement("span");
    span.className = `badge ${statusBadge(c)}`;
    span.textContent = c;
    els.drawerMeta.appendChild(span);
  });
  const openUrl = openUrlForItem(detail);
  const href = safeHref(openUrl);
  const unfetched = isUnfetchedItem(detail);
  if (els.drawerUnfetchedHint) {
    if (unfetched) {
      els.drawerUnfetchedHint.hidden = false;
      els.drawerUnfetchedHint.textContent =
        detail.user_hint ||
        "正文未能自动抓取。请自行打开下方完整链接阅读；如需入库，可用人工投喂粘贴正文后再确认。";
    } else {
      els.drawerUnfetchedHint.hidden = true;
      els.drawerUnfetchedHint.textContent = "";
    }
  }
  els.drawerUrl.textContent = "";
  if (href) {
    const a = document.createElement("a");
    a.href = href;
    a.target = "_blank";
    a.rel = "noopener noreferrer";
    a.textContent = openUrl || href;
    els.drawerUrl.appendChild(a);
  } else {
    els.drawerUrl.textContent = openUrl || "（无有效链接）";
  }
  const body = detail.extracted_text || detail.snippet || "";
  els.drawerBody.textContent =
    body || (unfetched ? "（无正文 — 请打开上方完整链接自行阅读）" : "（无正文）");
  els.drawerTrunc.hidden = !detail.extracted_text_truncated;
  if (href) {
    els.openArticle.href = href;
    els.openArticle.textContent = unfetched ? "打开完整链接" : "打开原文";
    els.openArticle.removeAttribute("aria-disabled");
    els.openArticle.classList.remove("is-disabled");
  } else {
    els.openArticle.href = "#";
    els.openArticle.textContent = "打开原文";
    els.openArticle.setAttribute("aria-disabled", "true");
    els.openArticle.classList.add("is-disabled");
  }
  els.drawer.hidden = false;
  const narrow = window.matchMedia("(max-width: 1023px)").matches;
  els.scrim.hidden = !narrow;
  els.drawerClose.focus();
}

els.feedList.addEventListener("click", async (e) => {
  const card = e.target.closest(".item[data-id]");
  if (!card) return;
  try {
    await openDrawer(card.dataset.id, card);
    showBanner("", "info");
  } catch (err) {
    showBanner(err.message, "error");
  }
});

els.feedList.addEventListener("keydown", async (e) => {
  if (e.key !== "Enter" && e.key !== " ") return;
  const card = e.target.closest(".item[data-id]");
  if (!card) return;
  e.preventDefault();
  try {
    await openDrawer(card.dataset.id, card);
  } catch (err) {
    showBanner(err.message, "error");
  }
});

els.drawerClose.addEventListener("click", closeDrawer);
els.scrim.addEventListener("click", closeDrawer);
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && !els.drawer.hidden) closeDrawer();
});

els.openArticle.addEventListener("click", (e) => {
  if (els.openArticle.classList.contains("is-disabled")) {
    e.preventDefault();
    showBanner("无有效 http(s) 原文链接", "error");
  }
});

els.feedPills.forEach((pill) => {
  pill.addEventListener("click", async () => {
    setFeedFilter(pill.dataset.status);
    try {
      await loadFeedList();
    } catch (err) {
      showBanner(err.message, "error");
    }
  });
});

els.feedRefresh.addEventListener("click", async () => {
  try {
    await refreshFeed();
    showBanner("流水已刷新", "ok");
  } catch (err) {
    showBanner(err.message, "error");
  }
});

/* ---------- Stats ---------- */

function barBlock(title, rows, labelKey, countKey) {
  if (!rows?.length) return "";
  const max = Math.max(...rows.map((r) => Number(r[countKey]) || 0), 1);
  const bars = rows
    .slice(0, 12)
    .map((r) => {
      const label = r[labelKey] || "—";
      const n = Number(r[countKey]) || 0;
      const pct = Math.round((n / max) * 100);
      return `<div class="bar-row">
        <span class="bar-label">${escapeHtml(String(label))}</span>
        <div class="bar-track"><div class="bar-fill" style="width:${pct}%"></div></div>
        <span class="bar-n ui-data">${n}</span>
      </div>`;
    })
    .join("");
  const table = rows
    .slice(0, 12)
    .map(
      (r) =>
        `<tr><td>${escapeHtml(String(r[labelKey] || "—"))}</td><td class="ui-data">${Number(r[countKey]) || 0}</td></tr>`
    )
    .join("");
  return `<section class="panel stats-card">
    <h3 class="panel-title">${escapeHtml(title)}</h3>
    <div class="bar-chart">${bars}</div>
    <table class="data-table"><thead><tr><th>项</th><th>数量</th></tr></thead><tbody>${table}</tbody></table>
  </section>`;
}

function rankingTable(title, rows) {
  if (!rows?.length) return "";
  const body = rows
    .slice(0, 15)
    .map((r, i) => {
      const name = r.company_name || r.company || r.name || r.label || "—";
      const n = r.count ?? r.event_count ?? 0;
      return `<tr><td class="ui-data">${i + 1}</td><td>${escapeHtml(String(name))}</td><td class="ui-data">${n}</td></tr>`;
    })
    .join("");
  return `<section class="panel stats-card stats-card-wide">
    <h3 class="panel-title">${escapeHtml(title)}</h3>
    <table class="data-table"><thead><tr><th>#</th><th>名称</th><th>数量</th></tr></thead><tbody>${body}</tbody></table>
  </section>`;
}

function trendBlock(rows) {
  if (!rows?.length) return "";
  const max = Math.max(...rows.map((r) => Number(r.count) || 0), 1);
  const cols = rows
    .map((r) => {
      const n = Number(r.count) || 0;
      const h = Math.max(4, Math.round((n / max) * 80));
      return `<div class="col-bar" title="${escapeAttr(String(r.month))}: ${n}">
        <div class="col-fill" style="height:${h}px"></div>
        <span class="col-label ui-data">${escapeHtml(String(r.month || "").slice(2))}</span>
      </div>`;
    })
    .join("");
  const table = rows
    .map((r) => `<tr><td class="ui-data">${escapeHtml(String(r.month))}</td><td class="ui-data">${r.count}</td></tr>`)
    .join("");
  return `<section class="panel stats-card stats-card-wide">
    <h3 class="panel-title">月度趋势</h3>
    <div class="col-chart">${cols}</div>
    <table class="data-table"><thead><tr><th>月</th><th>数量</th></tr></thead><tbody>${table}</tbody></table>
  </section>`;
}

function statsHasData(data) {
  const keys = [
    "industry_distribution",
    "event_type_distribution",
    "project_stage_distribution",
    "monthly_trend",
    "company_ranking",
  ];
  return keys.some((k) => Array.isArray(data[k]) && data[k].length > 0);
}

async function loadStats() {
  const fd = new FormData(els.statsForm);
  const params = new URLSearchParams();
  for (const [k, v] of fd.entries()) {
    if (k === "public_only") {
      if (els.statsForm.public_only?.checked || document.getElementById("stats-public")?.checked) {
        params.set("public_only", "true");
      }
      continue;
    }
    if (String(v).trim()) params.set(k, String(v).trim());
  }
  if (document.getElementById("stats-public")?.checked) params.set("public_only", "true");
  const q = params.toString();
  const data = await api(`/stats${q ? `?${q}` : ""}`);
  if (!statsHasData(data)) {
    els.statsEmpty.hidden = false;
    els.statsRoot.innerHTML = "";
    return;
  }
  els.statsEmpty.hidden = true;
  els.statsRoot.innerHTML = [
    barBlock("行业分布", data.industry_distribution, "industry", "count"),
    barBlock("动态类型", data.event_type_distribution, "event_type", "count"),
    barBlock("项目阶段", data.project_stage_distribution, "project_stage", "count"),
    trendBlock(data.monthly_trend),
    rankingTable("活跃企业", data.company_ranking),
    barBlock("地区分布", data.location_distribution, "location", "count"),
    barBlock("来源分布", data.source_distribution, "source", "count"),
    barBlock("合作方", data.partner_distribution, "partner", "count"),
  ]
    .filter(Boolean)
    .join("");
}

els.statsForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    await loadStats();
    showBanner("分析已更新", "ok");
  } catch (err) {
    showBanner(err.message, "error");
  }
});

/* ---------- Review (existing) ---------- */

function showLoading() {
  els.list.classList.add("is-loading");
  els.list.innerHTML = `<div class="skeleton" aria-hidden="true"></div><div class="skeleton" aria-hidden="true"></div>`;
  els.count.textContent = "…";
}

function renderItems(items) {
  els.list.classList.remove("is-loading");
  els.count.textContent = `${items.length} 条`;
  if (!items.length) {
    els.list.innerHTML = `<div class="empty">当前筛选下没有候选。可先搜索，或切换状态。</div>`;
    return;
  }
  els.list.innerHTML = items
    .map((item) => {
      const canIgnore = item.status === "pending_review";
      const canDecide = canIgnore && item.fetch_status !== "failed";
      const openUrl = openUrlForItem(item);
      const href = safeHref(openUrl);
      const unfetched = isUnfetchedItem(item);
      const hint = unfetched
        ? `<p class="item-unfetched-hint">${escapeHtml(
            item.user_hint ||
              "正文未能自动抓取。请自行打开下方完整链接阅读；如需入库，可用人工投喂粘贴正文后再确认。"
          )}</p>`
        : "";
      const urlBlock = href
        ? `<p class="item-url ui-data"><a href="${escapeAttr(href)}" target="_blank" rel="noopener noreferrer">${escapeHtml(openUrl)}</a></p>`
        : `<p class="item-url ui-data">${escapeHtml(openUrl || "")}</p>`;
      const fetchBadge =
        item.fetch_status && item.fetch_status !== "ok"
          ? `<span class="badge badge-danger ui-data">${escapeHtml(item.fetch_status)}${item.fetch_error_type ? ":" + item.fetch_error_type : ""}</span>`
          : "";
      return `
      <article class="item" data-id="${item.id}">
        <div class="item-head">
          <h3 class="item-title">${escapeHtml(item.title || "(untitled)")}</h3>
          <div style="display:flex;gap:0.35rem;flex-wrap:wrap">
            <span class="badge badge-provider ui-data">${escapeHtml(item.provider || "?")}</span>
            <span class="badge ${statusBadge(item.status)}">${escapeHtml(item.status)}</span>
            ${fetchBadge}
          </div>
        </div>
        ${hint}
        ${urlBlock}
        <p class="item-snippet">${escapeHtml(item.snippet || "")}</p>
        <div class="item-actions">
          <button type="button" class="btn btn-primary" data-action="confirm" ${canDecide ? "" : "disabled"}>确认</button>
          <button type="button" class="btn btn-danger" data-action="ignore" ${canIgnore ? "" : "disabled"}>忽略</button>
        </div>
      </article>`;
    })
    .join("");
}

function setStatusFilter(status) {
  currentStatus = status;
  els.pills.forEach((p) => p.setAttribute("aria-pressed", String(p.dataset.status === status)));
}

async function loadProviders() {
  const data = await api("/providers");
  const available = data.available || [];
  els.provider.innerHTML = "";
  const auto = document.createElement("option");
  auto.value = "";
  auto.textContent = "自动（Exa→Tavily→mock）";
  els.provider.appendChild(auto);
  for (const name of available) {
    if (name === "brave_mock") continue;
    const opt = document.createElement("option");
    opt.value = name;
    opt.textContent = name;
    els.provider.appendChild(opt);
  }
  const hasLive = available.includes("exa") || available.includes("tavily");
  if (!hasLive) {
    const mock = document.createElement("option");
    mock.value = "mock";
    mock.textContent = "mock";
    els.provider.appendChild(mock);
  }
}

async function loadList() {
  showLoading();
  try {
    const data = await api(`/candidates?status=${encodeURIComponent(currentStatus)}`);
    renderItems(data.items || []);
  } catch (err) {
    els.list.classList.remove("is-loading");
    els.list.innerHTML = `<div class="empty">加载失败：${escapeHtml(err.message)}</div>`;
    els.count.textContent = "—";
    throw err;
  }
}

async function runFetch(limit = 20) {
  return api("/fetch", { method: "POST", body: JSON.stringify({ limit }) });
}

function setBusy(btn, busy, labelIdle) {
  btn.disabled = busy;
  if (busy) btn.dataset.label = btn.textContent;
  btn.textContent = busy ? "…" : labelIdle || btn.dataset.label || btn.textContent;
}

els.saveKey.addEventListener("click", async () => {
  localStorage.setItem(KEY_STORAGE, apiKey());
  try {
    await loadProviders();
    await setTab(currentTab(), { pushHash: false });
    showBanner("API Key 已保存", "ok");
  } catch (err) {
    showBanner(err.message, "error");
  }
});

els.theme.addEventListener("click", () => {
  const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
  document.documentElement.dataset.theme = next;
  localStorage.setItem(THEME_STORAGE, next);
});

els.autoFetch.addEventListener("change", () => {
  localStorage.setItem(AUTO_FETCH_STORAGE, els.autoFetch.checked ? "1" : "0");
});

els.pills.forEach((pill) => {
  pill.addEventListener("click", async () => {
    setStatusFilter(pill.dataset.status);
    try {
      await loadList();
      showBanner("", "info");
    } catch (err) {
      showBanner(err.message, "error");
    }
  });
});

els.searchForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  setBusy(els.btnSearch, true, "搜索");
  try {
    const body = { query: els.query.value.trim() };
    if (els.provider.value) body.provider = els.provider.value;
    const summary = await api("/search", { method: "POST", body: JSON.stringify(body) });
    let fetchPart = "";
    let fetchFailed = null;
    if (els.autoFetch.checked && summary.inserted > 0) {
      setBusy(els.btnFetch, true, "抓取正文");
      try {
        const fetched = await runFetch(Math.min(50, Math.max(Number(summary.inserted) || 1, 1)));
        fetchPart = ` · 自动抓取 fetched=${fetched.fetched} failed=${fetched.failed}`;
        setStatusFilter("pending_review");
      } catch (fetchErr) {
        fetchFailed = fetchErr;
        fetchPart = ` · 自动抓取失败：${fetchErr.message}`;
        setStatusFilter("discovered");
      } finally {
        setBusy(els.btnFetch, false, "抓取正文");
      }
    } else {
      setStatusFilter(summary.inserted > 0 ? "discovered" : currentStatus);
    }
    try {
      await loadList();
    } catch {
      /* keep banner */
    }
    showBanner(
      `搜索完成 · provider=${summary.provider} · hits=${summary.hits} · inserted=${summary.inserted}${fetchPart}`,
      fetchFailed ? "error" : "ok"
    );
  } catch (err) {
    showBanner(err.message, "error");
  } finally {
    setBusy(els.btnSearch, false, "搜索");
  }
});

els.btnFetch.addEventListener("click", async () => {
  setBusy(els.btnFetch, true, "抓取正文");
  try {
    const summary = await runFetch(20);
    setStatusFilter("pending_review");
    await loadList();
    const failedRows = summary.unfetched_for_user || [];
    let msg = `抓取完成 · fetched=${summary.fetched} · failed=${summary.failed}`;
    if (failedRows.length) {
      const lines = failedRows
        .slice(0, 8)
        .map((r) => `· ${r.title || r.candidate_id}: ${r.open_url || "(no url)"}`)
        .join("\n");
      msg += `\n未能抓取正文的条目（请自行打开完整链接）：\n${lines}`;
    }
    showBanner(msg, failedRows.length ? "info" : "ok");
  } catch (err) {
    showBanner(err.message, "error");
  } finally {
    setBusy(els.btnFetch, false, "抓取正文");
  }
});

els.btnRefresh.addEventListener("click", async () => {
  try {
    await loadList();
    showBanner("已刷新", "ok");
  } catch (err) {
    showBanner(err.message, "error");
  }
});

els.list.addEventListener("click", async (e) => {
  const btn = e.target.closest("[data-action]");
  if (!btn || btn.disabled) return;
  const card = btn.closest("[data-id]");
  const id = card?.dataset.id;
  if (!id) return;
  const action = btn.dataset.action;
  btn.disabled = true;
  try {
    await api(`/candidates/${id}/${action}`, { method: "POST", body: "{}" });
    await loadList();
    showBanner(`已${action === "confirm" ? "确认" : "忽略"} #${id}`, "ok");
  } catch (err) {
    showBanner(err.message, "error");
    btn.disabled = false;
  }
});

function boot() {
  const theme = localStorage.getItem(THEME_STORAGE) || "light";
  document.documentElement.dataset.theme = theme;
  els.apiKey.value = localStorage.getItem(KEY_STORAGE) || "dev-local-key";
  const auto = localStorage.getItem(AUTO_FETCH_STORAGE);
  els.autoFetch.checked = auto === null ? true : auto === "1";
  setFeedFilter("discovered");
  if (!location.hash) history.replaceState(null, "", "#feed");
  if (apiKey()) {
    loadProviders()
      .then(() => setTab(currentTab(), { pushHash: false }))
      .then(() => {
        if (!els.banner.textContent) showBanner("就绪 · 默认「流水」Tab", "info");
      })
      .catch((err) => showBanner(err.message, "error"));
  } else {
    showBanner("填写 API Key 后点保存", "info");
    setTab(currentTab(), { pushHash: false });
  }
}

boot();
