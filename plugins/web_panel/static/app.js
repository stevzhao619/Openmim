// Openmim Web Panel — enhanced UI client
const TOKEN_KEY = "openmim_web_token";
const THEME_KEY = "openmim_theme";

function getToken() {
  // URL token must win over stale sessionStorage, otherwise opening
  // /?token=<new-token> can still send an old token and get 401.
  const urlToken = (new URLSearchParams(location.search)).get("token") || "";
  if (urlToken) {
    sessionStorage.setItem(TOKEN_KEY, urlToken);
    return urlToken;
  }
  return sessionStorage.getItem(TOKEN_KEY) || "";
}
function setToken(v) { sessionStorage.setItem(TOKEN_KEY, v); }

function authHeaders() {
  const t = getToken();
  const scheme = "Bear" + "er ";
  return t ? { Authorization: scheme + t } : {};
}
function jsonHeaders() { return { ...authHeaders(), "Content-Type": "application/json" }; }

async function api(path, opts = {}) {
  // Don't even try the network if no token is known — avoids the 401 toast storm
  // when the dashboard first loads before the user has entered a token.
  if (!getToken()) {
    throw new Error("\u8bf7\u5148\u8f93\u5165 Access Token");
  }
  const resp = await fetch(path, { headers: opts.body ? jsonHeaders() : authHeaders(), ...opts });
  if (resp.status === 401) {
    // Only show the toast when a token was actually sent (real mismatch); the
    // empty-token case is handled inline by each loader.
    toast("\u672a\u6388\u6743 (401) \u2014 Token \u9519\u8bef\u6216\u5df2\u8fc7\u671f", "error");
    throw new Error("\u672a\u6388\u6743 (401)");
  }
  if (resp.status === 503) {
    toast("\u670d\u52a1\u672a\u914d\u7f6e Token (503)", "warn");
    throw new Error("\u670d\u52a1\u672a\u914d\u7f6e Token");
  }
  if (!resp.ok) { let detail = ""; try { detail = (await resp.json()).detail || ""; } catch (_) {} throw new Error(`HTTP ${resp.status} ${detail}`); }
  return resp.json();
}

function $(id) { return document.getElementById(id); }
function el(tag, attrs = {}, ...children) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v == null || v === false) continue;
    if (k === "class") e.className = v;
    else if (k === "html") e.innerHTML = v;
    else if (k === "onclick" || k === "onchange") e.addEventListener(k.slice(2), v);
    else e.setAttribute(k, v);
  }
  for (const c of children) {
    if (c == null || c === false) continue;
    e.appendChild(typeof c === "string" || typeof c === "number" ? document.createTextNode(String(c)) : c);
  }
  return e;
}

// ─── Toast ─────────────────────────────────────────────────
function toast(msg, kind = "ok", timeout = 3200) {
  const wrap = $("toasts");
  const t = el("div", { class: "toast " + kind });
  const icon = kind === "ok" ? "\u2714" : kind === "error" ? "\u2716" : kind === "warn" ? "\u26a0" : "\u2139";
  t.appendChild(el("span", { style: "font-size:16px" }, icon));
  t.appendChild(el("span", {}, String(msg)));
  wrap.appendChild(t);
  setTimeout(() => { t.classList.add("leaving"); setTimeout(() => t.remove(), 320); }, timeout);
}

// ─── Theme ─────────────────────────────────────────────────
function initTheme() {
  const btn = $("theme-toggle");
  btn.addEventListener("click", () => {
    const cur = document.documentElement.getAttribute("data-theme");
    const prefersDark = matchMedia("(prefers-color-scheme: dark)").matches;
    const isDark = cur ? cur === "dark" : prefersDark;
    const next = isDark ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", next);
    localStorage.setItem(THEME_KEY, next);
    toast(`\u5df2\u5207\u6362\u5230 ${next === "dark" ? "\u6df1\u8272" : "\u6d45\u8272"} \u6a21\u5f0f`, "ok", 1600);
  });
}

// ─── Button ripple + loading ───────────────────────────────
function ripple(e) {
  const b = e.currentTarget;
  const r = b.getBoundingClientRect();
  b.style.setProperty("--rx", ((e.clientX - r.left) / r.width) * 100 + "%");
  b.style.setProperty("--ry", ((e.clientY - r.top) / r.height) * 100 + "%");
}
function withLoading(btn, fn) {
  return async (...args) => {
    if (btn.classList.contains("loading")) return;
    btn.classList.add("loading");
    try { return await fn(...args); }
    finally { btn.classList.remove("loading"); }
  };
}

// ─── Token UI ──────────────────────────────────────────────
function initTokenUI() {
  const input = $("token-input");
  const status = $("auth-status");
  input.value = getToken();
  $("token-save").addEventListener("click", withLoading($("token-save"), () => {
    setToken(input.value.trim());
    status.textContent = "\u2714 \u5df2\u4fdd\u5b58";
    toast("Token \u5df2\u4fdd\u5b58", "ok", 1500);
    return loadDashboard();
  }));
}

// ─── Tabs ──────────────────────────────────────────────────
function initTabs() {
  const buttons = $("tabs").querySelectorAll("button");
  buttons.forEach(btn => {
    btn.addEventListener("click", ripple, true);
    btn.addEventListener("click", () => {
      buttons.forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      const tab = btn.dataset.tab;
      document.querySelectorAll(".tab-panel").forEach(p => p.classList.remove("active"));
      $(`tab-${tab}`).classList.add("active");
      const loader = LOADERS[tab];
      if (loader) loader().catch(e => { $(`tab-${tab}`).innerHTML = ""; $(`tab-${tab}`).appendChild(el("p", { class: "error" }, e.message)); });
    });
  });
}

// ─── Loading placeholder ───────────────────────────────────
function shimmer(n = 1) {
  const frag = document.createDocumentFragment();
  for (let i = 0; i < n; i++) {
    const s = el("div", { class: "shimmer" });
    frag.appendChild(s);
  }
  return frag;
}

function noTokenCard() {
  return el("div", { class: "card" },
    el("h2", {}, "\u9700\u8981 Access Token"),
    el("p", { class: "muted" }, "\u8bf7\u5728\u53f3\u4e0a\u89d2\u8f93\u5165 Access Token \u5e76\u70b9 \u201c\u4fdd\u5b58 Token\u201d\uff0c\u6216\u6253\u5f00 "),
    el("code", {}, "/?token=<\u4f60\u7684 token>"),
    el("p", { class: "muted" }, "\u8bbf\u95ee\u9700\u8981 Token \u662f\u4e3a\u4e86\u907f\u514d\u672a\u6388\u6743\u7528\u6237\u4fee\u6539\u914d\u7f6e\u3002"),
  );
}

// ─── Dashboard ─────────────────────────────────────────────
async function loadDashboard() {
  const root = $("tab-dashboard");
  root.innerHTML = "";
  if (!getToken()) {
    root.appendChild(noTokenCard());
    return;
  }
  root.appendChild(shimmer(2));
  try {
    const status = await api("/api/status");
    const tu = await api("/api/token-usage").catch(() => ({ available: false }));
    root.innerHTML = "";

    // Stat tiles
    const grid = el("div", { class: "stat-grid" });
    grid.appendChild(statTile("\u767d\u540d\u5355\u7fa4\u6570", status.whitelist_count || 0));
    grid.appendChild(statTile("\u5df2\u88c5\u63d2\u4ef6", status.plugin_count || 0));
    grid.appendChild(statTile("\u8fd0\u884c\u72b6\u6001", status.ok ? "\u5728\u7ebf" : "\u79bb\u7ebf"));
    grid.appendChild(statTile("Business", status.business_enabled ? "\u542f\u7528" : "\u5173\u95ed"));
    root.appendChild(grid);

    root.appendChild(el("div", { class: "card" }, el("h2", {}, "\u8fd0\u884c\u72b6\u6001"),
      el("p", {}, el("span", { class: "tag " + (status.ok ? "" : "off") }, status.ok ? "ONLINE" : "OFFLINE")),
      tu.available ? el("pre", {}, JSON.stringify(tu, null, 2)) : el("p", { class: "muted" }, "Token usage: \u4e0d\u53ef\u7528")));
  } catch (e) { root.innerHTML = ""; root.appendChild(el("p", { class: "error" }, e.message)); }
}
function statTile(label, value) {
  return el("div", { class: "stat" },
    el("div", { class: "label" }, label),
    el("div", { class: "value" }, String(value)));
}

// ─── Whitelist ─────────────────────────────────────────────
async function loadWhitelist() {
  const root = $("tab-whitelist");
  root.innerHTML = "";
  root.appendChild(shimmer(1));
  const data = await api("/api/whitelist");
  root.innerHTML = "";
  const card = el("div", { class: "card" }, el("h2", {}, "\u767d\u540d\u5355"));
  const list = data.whitelist || [];
  if (list.length === 0) card.appendChild(el("p", { class: "muted" }, "\u65e0\u767d\u540d\u5355\u7fa4"));
  else card.appendChild(el("ul", {}, ...list.map(id => {
    const li = el("li", {}, el("code", {}, id),
      el("button", { class: "danger", onclick: withLoadingFn(async () => {
        await api(`/api/whitelist/${id}`, { method: "DELETE" });
        toast(`\u5df2\u5220\u9664 ${id}`, "ok");
        loadWhitelist();
      }) }, "\u5220\u9664"));
    return li;
  })));
  const inp = el("input", { placeholder: "-1001234567890" });
  const addBtn = el("button", { onclick: withLoadingFn(async () => {
    if (!inp.value.trim()) return;
    await api("/api/whitelist", { method: "POST", body: JSON.stringify({ chat_id: inp.value.trim() }) });
    toast(`\u5df2\u6dfb\u52a0 ${inp.value.trim()}`, "ok");
    inp.value = "";
    loadWhitelist();
  }) }, "\u6dfb\u52a0");
  card.appendChild(el("div", { class: "row" }, inp, addBtn));
  root.appendChild(card);
}

// ─── Access lists ──────────────────────────────────────────
async function loadAccess() {
  const root = $("tab-access");
  root.innerHTML = "";
  const data = await api("/api/access-lists");
  const card = el("div", { class: "card" }, el("h2", {}, "\u8bbf\u95ee\u5141\u8bb8\u5217\u8868"));
  for (const [key, ids] of Object.entries(data)) {
    const ta = el("textarea", { rows: "2", style: "width:100%" });
    ta.value = ids.join(", ");
    card.appendChild(el("div", { class: "row" },
      el("label", { style: "min-width:240px" }, key),
      el("div", { style: "flex:1" }, ta),
      el("button", { onclick: withLoadingFn(async () => {
        const payload = ta.value.split(/[\s,\uff0c;\uff1b]+/).filter(Boolean).map(String);
        await api(`/api/access-lists/${key}`, { method: "PUT", body: JSON.stringify({ user_ids: payload }) });
        toast(`${key} \u5df2\u4fdd\u5b58`, "ok");
        loadAccess();
      }) }, "\u4fdd\u5b58")));
  }
  root.appendChild(card);
}

// ─── Plugins ───────────────────────────────────────────────
async function loadPlugins() {
  const root = $("tab-plugins");
  root.innerHTML = "";
  root.appendChild(shimmer(1));
  const data = await api("/api/plugins");
  root.innerHTML = "";
  const card = el("div", { class: "card" }, el("h2", {}, "\u63d2\u4ef6"));
  if (!data.plugins.length) { card.appendChild(el("p", { class: "muted" }, "\u65e0\u63d2\u4ef6")); root.appendChild(card); return; }
  const tbl = el("table", {},
    el("thead", {}, el("tr", {},
      el("th", {}, "\u540d\u79f0"), el("th", {}, "\u72b6\u6001"), el("th", {}, "\u4f18\u5148\u7ea7"), el("th", {}, "\u5de5\u5177"), el("th", {}, "\u64cd\u4f5c"))),
    el("tbody", {}));
  const tb = tbl.querySelector("tbody");
  for (const p of data.plugins) {
    tb.appendChild(el("tr", {},
      el("td", {}, el("code", {}, p.name)),
      el("td", {}, el("span", { class: "tag " + (p.enabled ? "" : "off") }, p.enabled ? "enabled" : "disabled")),
      el("td", {}, String(p.priority)),
      el("td", {}, String(p.tool_count)),
      el("td", {}, el("button", { class: "ghost", onclick: withLoadingFn(async () => {
        const r = await api(`/api/plugins/${p.name}/toggle`, { method: "POST" });
        toast(`${p.name} \u2192 ${r.enabled ? "enabled" : "disabled"}`, "ok");
        loadPlugins();
      }) }, "\u5207\u6362"))));
  }
  card.appendChild(tbl);
  root.appendChild(card);
}

// ─── Group settings ────────────────────────────────────────
async function loadGroupSettings() {
  const root = $("tab-group-settings");
  root.innerHTML = "";
  const wl = await api("/api/whitelist");
  const card = el("div", { class: "card" }, el("h2", {}, "\u7fa4\u8bbe\u7f6e"));
  const sel = el("select", {});
  sel.appendChild(el("option", { value: "" }, "\u2014 \u9009\u62e9\u7fa4 \u2014"));
  for (const id of wl.whitelist) sel.appendChild(el("option", { value: id }, id));
  card.appendChild(el("div", { class: "row" }, sel));
  const out = el("div", {});
  sel.addEventListener("change", async () => {
    out.innerHTML = ""; if (!sel.value) return;
    out.appendChild(shimmer(1));
    const data = await api(`/api/group-settings/${sel.value}`);
    out.innerHTML = "";
    for (const [k, v] of Object.entries(data.settings || {})) {
      out.appendChild(el("div", { class: "row" }, el("code", {}, k), el("input", { value: v, style: "flex:1" })));
    }
  });
  card.appendChild(out);
  root.appendChild(card);
}

// ─── JSON editor ───────────────────────────────────────────
async function loadJsonEditor() {
  const root = $("tab-json");
  root.innerHTML = "";
  const files = await api("/api/json-files");
  const card = el("div", { class: "card" }, el("h2", {}, "JSON \u7f16\u8f91\u5668"),
    el("div", { class: "notice" }, "\u654f\u611f\u5b57\u6bb5\u4f1a\u88ab\u8131\u654f\u663e\u793a\uff1b\u4fdd\u5b58\u65f6\u5408\u5e76\u5230\u539f\u6587\u4ef6\u5e76\u81ea\u52a8\u5907\u4efd\u3002\u5982\u9700\u4fee\u6539\u654f\u611f\u503c\uff0c\u8bf7\u8f93\u5165\u5b8c\u6574\u5185\u5bb9\uff08\u4e0d\u8981\u4fdd\u5b58 **** \u5360\u4f4d\u7b26\uff09\u3002"));
  const sel = el("select", {}); sel.appendChild(el("option", { value: "" }, "\u2014 \u9009\u62e9\u6587\u4ef6 \u2014"));
  for (const f of files.files) sel.appendChild(el("option", { value: f.name }, f.name));
  card.appendChild(el("div", { class: "row" }, sel));
  const ta = el("textarea", { rows: "20", style: "width:100%;font-family:var(--mono)" });
  const info = el("p", { class: "muted" }, "");
  const actions = el("div", { class: "row" });
  const fmt = el("button", { class: "ghost" }, "\u683c\u5f0f\u5316");
  const save = el("button", {}, "\u4fdd\u5b58");
  const reload = el("button", { class: "ghost" }, "\u91cd\u65b0\u52a0\u8f7d");
  fmt.addEventListener("click", () => { try { ta.value = JSON.stringify(JSON.parse(ta.value), null, 2); info.textContent = "\u5df2\u683c\u5f0f\u5316"; info.className = "muted"; } catch (e) { info.textContent = "JSON \u65e0\u6548: " + e.message; info.className = "error"; } });
  reload.addEventListener("click", () => sel.dispatchEvent(new Event("change")));
  save.addEventListener("click", withLoading(save, async () => {
    if (!sel.value) { toast("\u8bf7\u5148\u9009\u62e9\u6587\u4ef6", "warn"); return; }
    if (!confirm(`\u786e\u8ba4\u8986\u76d6\u4fdd\u5b58 ${sel.value} \u5417\uff1f\u539f\u6587\u4ef6\u4f1a\u81ea\u52a8\u5907\u4efd\u3002`)) return;
    let data; try { data = JSON.parse(ta.value); } catch (e) { info.textContent = "JSON \u65e0\u6548: " + e.message; info.className = "error"; return; }
    try {
      await api(`/api/json-files/${sel.value}`, { method: "PUT", body: JSON.stringify({ data }) });
      info.textContent = "\u5df2\u4fdd\u5b58\uff08\u5df2\u81ea\u52a8\u5907\u4efd\uff09"; info.className = "ok";
      toast(`${sel.value} \u4fdd\u5b58\u6210\u529f`, "ok");
    } catch (e) { info.textContent = e.message; info.className = "error"; toast(e.message, "error"); }
  }));
  actions.appendChild(fmt); actions.appendChild(reload); actions.appendChild(save);
  sel.addEventListener("change", async () => { if (!sel.value) { ta.value = ""; return; } ta.value = "\u52a0\u8f7d\u4e2d\u2026"; const data = await api(`/api/json-files/${sel.value}`); ta.value = JSON.stringify(data.data, null, 2); info.textContent = ""; });
  card.appendChild(ta); card.appendChild(actions); card.appendChild(info); root.appendChild(card);
}

// ─── Skill upload ──────────────────────────────────────────
async function loadSkills() {
  const root = $("tab-skills");
  root.innerHTML = "";
  const card = el("div", { class: "card" }, el("h2", {}, "Skill \u4e0a\u4f20"),
    el("p", { class: "muted" }, "\u652f\u6301\u5355\u4e2a SKILL.md \u6216\u5305\u542b SKILL.md \u7684 .zip \u5305\uff1bfrontmatter \u5fc5\u987b\u5305\u542b name \u4e0e description\u3002"));
  const fileInp = el("input", { type: "file", accept: ".md,.zip,application/zip" });
  const overwrite = el("input", { type: "checkbox" });
  const result = el("pre", {});
  const upload = el("button", {}, "\u4e0a\u4f20\u5e76\u5b89\u88c5");
  upload.addEventListener("click", withLoading(upload, async () => {
    const f = fileInp.files[0];
    if (!f) { result.textContent = "\u8bf7\u9009\u62e9\u6587\u4ef6"; toast("\u8bf7\u5148\u9009\u62e9\u6587\u4ef6", "warn"); return; }
    const buf = await f.arrayBuffer();
    const b64 = btoa(String.fromCharCode(...new Uint8Array(buf)));
    try {
      const r = await api("/api/skills/upload", { method: "POST", body: JSON.stringify({ filename: f.name, content: b64, overwrite: overwrite.checked })});
      result.textContent = JSON.stringify(r, null, 2);
      toast(`Skill "${r.name}" \u5b89\u88c5\u6210\u529f`, "ok");
    } catch (e) { result.textContent = e.message; toast(e.message, "error"); }
  }));
  card.appendChild(el("div", { class: "row" }, fileInp, el("label", {}, overwrite, " \u8986\u76d6\u5df2\u5b58\u5728")));
  card.appendChild(el("div", { class: "row" }, upload)); card.appendChild(result); root.appendChild(card);
}

// ─── Diagnostics ───────────────────────────────────────────
async function loadDiagnostics() {
  const root = $("tab-diagnostics");
  root.innerHTML = "";
  root.appendChild(shimmer(1));
  try {
    const status = await api("/api/status");
    const health = await fetch("/healthz").then(r => r.json());
    root.innerHTML = "";
    root.appendChild(el("div", { class: "card" }, el("h2", {}, "\u8bca\u65ad"), el("pre", {}, JSON.stringify({ status, health }, null, 2))));
  } catch (e) { root.innerHTML = ""; root.appendChild(el("p", { class: "error" }, e.message)); }
}

// ─── Restart ───────────────────────────────────────────────
async function loadRestart() {
  const root = $("tab-restart");
  root.innerHTML = "";
  const card = el("div", { class: "card" }, el("h2", {}, "\u91cd\u542f"),
    el("p", {}, "\u6b64\u64cd\u4f5c\u5c06\u6267\u884c\u914d\u7f6e\u597d\u7684\u91cd\u542f\u547d\u4ee4\u3002\u4ec5\u5728 WEB_PANEL_RESTART_ENABLED=true \u4e14 WEB_PANEL_RESTART_COMMAND \u5df2\u8bbe\u7f6e\u65f6\u53ef\u7528\u3002"));
  const btn = el("button", { class: "danger" }, "\u89e6\u53d1\u91cd\u542f");
  const out = el("p", {});
  btn.addEventListener("click", withLoading(btn, async () => {
    if (!confirm("\u786e\u8ba4\u8981\u89e6\u53d1\u91cd\u542f\u5417\uff1f")) return;
    try {
      const r = await api("/api/restart", { method: "POST", body: JSON.stringify({ reason: "web" }) });
      out.textContent = JSON.stringify(r);
      toast("\u91cd\u542f\u5df2\u89e6\u53d1", r.ok ? "warn" : "error");
    } catch (e) { out.textContent = e.message; out.className = "error"; toast(e.message, "error"); }
  }));
  card.appendChild(el("div", { class: "row" }, btn)); card.appendChild(out); root.appendChild(card);
}

// Helper: wrap an async handler so the triggering button shows a spinner while it runs.
function withLoadingFn(fn) {
  return async function(evt) {
    const btn = (evt && evt.currentTarget) || null;
    if (btn && btn.classList && btn.classList.contains("loading")) return;
    if (btn && btn.classList) btn.classList.add("loading");
    try { return await fn(evt); }
    finally { if (btn && btn.classList) btn.classList.remove("loading"); }
  };
}

const LOADERS = { dashboard: loadDashboard, whitelist: loadWhitelist, access: loadAccess, plugins: loadPlugins, "group-settings": loadGroupSettings, json: loadJsonEditor, skills: loadSkills, diagnostics: loadDiagnostics, restart: loadRestart };

// ── boot ───────────────────────────────────────────────────
initTheme();
initTokenUI();
initTabs();
document.addEventListener("pointerdown", e => { if (e.target.closest("button")) ripple({ currentTarget: e.target.closest("button"), clientX: e.clientX, clientY: e.clientY }); }, { passive: true });
loadDashboard();
