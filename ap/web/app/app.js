// QUIKCOLAPS demo app: landing page, project steps, results, live log.
import { Viewer, MODES, SCENARIO_MODES } from "./viewer.js";

const $ = (s) => document.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const fmt = (x, d = 0) => (x == null ? "–" : Number(x).toLocaleString(undefined, { maximumFractionDigits: d, minimumFractionDigits: d }));
const sign = (x, d = 2) => (x == null ? "–" : (x >= 0 ? "+" : "−") + fmt(Math.abs(x), d));

async function api(path, opts = {}) {
  const r = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts });
  const body = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(body.detail || `${r.status} ${r.statusText}`);
  return body;
}
const post = (path, body = {}) => api(path, { method: "POST", body: JSON.stringify(body) });

const ETABS_STEPS = new Set([0, 1, 3, 4, 5, 6, 7]);
const STEP_HELP = {
  0: "Opens the AP working copy in ETABS and checks it is ready: deck floors, the CS1 template, load patterns, auto-select lists, ETABS version. Read-only.",
  1: "Exports the building, runs the intact gravity case (1.2D+0.5L), reads every column's axial force and finds the UFC removal locations and stories.",
  2: "Builds the condition table and asks Claude to review the rule candidates and add what the UFC judgment conditions call for (about $0.50). You approve the scenario set.",
  3: "Writes one staged construction case, load group and combination per scenario into the AP copy; every write is read back.",
  4: "Runs all scenarios and designs once (composite, then steel). The load check compares each scenario's base reaction with its increment.",
  5: "Redesign rounds: accept the design sections, run, design, until the weight changes by less than 0.5% (max 3 rounds).",
  6: "Copies collapse-driven sizes to the symmetry-equivalent locations. You approve the list; the app fixes those sections and runs finalize until every steel member is at or below 1.0.",
  7: "Computes the strength-only baseline on the baseline copy if it is missing, and the premium. The report comes later (item E).",
};

let S = { project: null, step: null, files: {}, viewer: null, vdata: null, job: null, logLen: 0, poll: null, etabs: false, render: 0 };

// ---------- landing ----------
let PROJECTS = [];
const PREVIEWS = {};
const day = (s) => (s ? s.replace("T", " ").slice(0, 16) : "–");

async function showLanding() {
  stopPlay();
  $("#project").classList.add("hidden");
  $("#landing").classList.remove("hidden");
  S.project = null;
  for (const k in PREVIEWS) delete PREVIEWS[k];   // projects may have moved on since
  PROJECTS = await api("/api/projects");
  $("#project-list").innerHTML = PROJECTS.length ? PROJECTS.map(row).join("") : `<p class="muted">No projects yet.</p>`;
  $("#preview").classList.toggle("hidden", !PROJECTS.length);
  document.querySelectorAll("[data-open]").forEach((b) => (b.onclick = () => openProject(b.dataset.open)));
  document.querySelectorAll("[data-remove]").forEach((b) => (b.onclick = async () => {
    if (!confirm("Remove this project from the list? Its folder and models stay on disk.")) return;
    await api(`/api/projects/${b.dataset.remove}`, { method: "DELETE" });
    showLanding();
  }));
  document.querySelectorAll(".prow").forEach((r) => (r.onmouseenter = () => preview(r.dataset.id)));
  if (PROJECTS.length) preview(PROJECTS[0].id);
}

function row(p) {
  const last = p.last_completed >= 0 ? `step ${p.last_completed} ${esc(p.last_completed_name)}` : "not started";
  return `<div class="prow" data-id="${p.id}">
    <h3>${esc(p.name)}${p.demo ? '<span class="tag">demo</span>' : ""}</h3>
    <div class="sub"><span class="mono">${esc(p.ap_model.split(/[\\/]/).pop())}</span> · ${last}</div>
    <div class="prem">${p.premium ? `${sign(p.premium.percent, 1)}%<small>${sign(p.premium.short_tons, 1)} t premium</small>` : `<small>no premium yet</small>`}</div>
    <div class="acts"><button data-open="${p.id}">Open</button><button class="danger" data-remove="${p.id}" title="Remove from list (files stay)">Remove</button></div>
  </div>`;
}

async function preview(id) {
  const p = PROJECTS.find((x) => x.id === id);
  if (!p) return;
  document.querySelectorAll(".prow").forEach((r) => r.classList.toggle("active", r.dataset.id === id));
  const info = `<h3>${esc(p.name)}</h3><div class="muted mono" style="word-break:break-all">${esc(p.ap_model)}</div>`;
  const kv = `<div class="kv">
      <span>created</span><span>${day(p.created)}</span>
      <span>updated</span><span>${day(p.updated)}</span>
      <span>last step</span><span>${p.last_completed >= 0 ? `${p.last_completed} ${esc(p.last_completed_name)} (${esc(p.last_status)})` : "not started"}</span>
      ${p.finalize ? `<span>finalize</span><span>${esc(p.finalize)}</span>` : ""}
      ${p.tonnage ? `<span>tonnage</span><span>${fmt(p.tonnage, 1)}${p.baseline ? ` vs ${fmt(p.baseline, 1)}` : ""} short tons</span>` : ""}
      ${p.premium ? `<span>premium</span><span><b>${sign(p.premium.short_tons, 1)} t (${sign(p.premium.percent, 1)}%)</b></span>` : ""}
    </div>`;
  if (!(id in PREVIEWS)) {
    $("#preview").innerHTML = info + `<div class="ph">loading…</div>` + kv;
    try { PREVIEWS[id] = previewSvg(await api(`/api/projects/${id}/viewer`)); } catch { PREVIEWS[id] = ""; }
    if (!document.querySelector(`.prow.active[data-id="${id}"]`)) return;   // the mouse moved on
  }
  $("#preview").innerHTML = info + (PREVIEWS[id] || `<div class="ph">No building yet (step 1)</div>`) + kv;
}

// Axonometric wireframe of the members, coloured by reason once there is a final design.
function previewSvg(v) {
  const ms = v.members || [];
  if (!ms.length) return "";
  const c30 = Math.cos(Math.PI / 6), s30 = 0.5;
  const P = ([x, y, z]) => [(x - y) * c30, -(z * 1.0) - (x + y) * s30 * 0.6];
  let x0 = Infinity, x1 = -Infinity, y0 = Infinity, y1 = -Infinity;
  const segs = ms.map((m) => { const a = P(m.a), b = P(m.b); for (const [x, y] of [a, b]) { x0 = Math.min(x0, x); x1 = Math.max(x1, x); y0 = Math.min(y0, y); y1 = Math.max(y1, y); } return [a, b, m]; });
  const col = { collapse: "var(--collapse)", propagated: "var(--propagated)", finalize: "var(--finalize)", strength: "var(--strength)" };
  const pad = 0.04 * Math.max(x1 - x0, y1 - y0);
  segs.sort((p, q) => (q[2].reason === "unchanged") - (p[2].reason === "unchanged"));   // changed members on top
  const lines = segs.map(([a, b, m]) => `<line x1="${a[0].toFixed(1)}" y1="${a[1].toFixed(1)}" x2="${b[0].toFixed(1)}" y2="${b[1].toFixed(1)}" stroke="${col[m.reason] || "#9aa3a6"}" stroke-width="${col[m.reason] ? 0.5 : 0.22}" stroke-opacity="${col[m.reason] ? 1 : 0.8}"/>`).join("");
  return `<svg viewBox="${(x0 - pad).toFixed(1)} ${(y0 - pad).toFixed(1)} ${(x1 - x0 + 2 * pad).toFixed(1)} ${(y1 - y0 + 2 * pad).toFixed(1)}" preserveAspectRatio="xMidYMid meet" style="aspect-ratio:4/3">${lines}</svg>`;
}

$("#pick").onclick = async () => {
  $("#create-msg").textContent = "A file dialog opened on this computer…";
  const r = await post("/api/pick-model");
  $("#create-msg").textContent = "";
  if (r.path) $("#model-path").value = r.path;
};
$("#create").onclick = async () => {
  const msg = $("#create-msg");
  msg.className = "msg";
  try {
    const p = await post("/api/projects", { model_path: $("#model-path").value, name: $("#project-name").value || null });
    msg.textContent = p.notes.join("\n");
    await openProject(p.id, 0);
  } catch (e) { msg.className = "msg bad"; msg.textContent = e.message; }
};

// ---------- project ----------
async function openProject(id, step) {
  stopPlay();
  $("#landing").classList.add("hidden");
  $("#project").classList.remove("hidden");
  if (!S.viewer) initViewer();
  S.files = {}; S.vdata = null; S.render++;
  $("#log").textContent = ""; S.jobId = undefined;
  // nothing of the previous project stays clickable while this one loads
  $("#stepbar").innerHTML = ""; $("#tab-step").innerHTML = `<p class="muted">Loading…</p>`; $("#tab-results").innerHTML = "";
  $("#p-name").textContent = "…"; $("#p-model").textContent = "";
  await refresh(id);
  const p = S.project;
  S.step = step ?? (p.steps.find((s) => s.status === "awaiting" || s.status === "failed" || s.status === "running")?.n ?? Math.min(p.last_completed + 1, 7));
  switchTab(p.last_completed >= 6 ? "results" : "step");
  await loadViewer(true);
  showStepView(S.step);
  renderAll();
  startPolling();
}

async function refresh(id) {
  S.project = await api(`/api/projects/${id || S.project.id}`);
  S.etabs = S.project.etabs;
}

async function file(name, force = false) {
  if (!force && name in S.files) return S.files[name];
  if (!S.project.files.includes(name)) return (S.files[name] = null);
  try { S.files[name] = await api(`/api/projects/${S.project.id}/file/${name}`); } catch { S.files[name] = null; }
  return S.files[name];
}

// ---------- viewer ----------
// Which views have data, and the one each step opens with (so the 3D view matches the step).
const has = (...names) => names.some((n) => S.project.files.includes(n));
function available() {
  const b = S.vdata?.members.length > 0, sc = S.viewer.extra.scenarios;
  return {
    model: b ? "" : "after step 1",
    locations: b && sc?.candidates?.length ? "" : "after step 1",
    influence: b && sc?.scenarios?.length ? "" : "after step 1",
    ratio: b && has("results.json", "results_original.json") ? "" : "after step 4",
    heat: b && has("scenario_ratios.json") ? "" : "compute ratios in step 6",
    changed: b && has("building_final.json", "building_current.json") ? "" : "after step 6",
    weight: b && has("building_final.json", "building_current.json") ? "" : "after step 6",
    sizes: b && has("building_final.json", "building_current.json") ? "" : "after step 6",
  };
}
const STEP_VIEW = { 0: ["model"], 1: ["locations"], 2: ["locations"], 3: ["influence"], 4: ["ratio", "first"], 5: ["ratio", "latest"], 6: ["changed"], 7: ["weight"] };
const FALLBACK = ["changed", "ratio", "influence", "locations", "model"];

function fillModes() {
  const av = available(), cur = $("#mode").value;
  $("#mode").innerHTML = Object.entries(MODES).map(([k, label]) =>
    `<option value="${k}" ${av[k] ? "disabled" : ""}>${label}${av[k] ? ` (${av[k]})` : ""}</option>`).join("");
  if (cur && !av[cur]) $("#mode").value = cur;
  else $("#mode").value = FALLBACK.find((k) => !av[k]) || "model";
}

// Clicking a step shows its view; the user can switch views freely afterwards.
function showStepView(n) {
  const [mode, basis] = STEP_VIEW[n] || ["model"];
  const av = available();
  if (!av[mode]) {
    $("#mode").value = mode;
    if (basis) $("#ratio-basis").value = basis === "first" && !has("results_original.json") ? "latest" : basis;
  }
  if (!SCENARIO_MODES.has($("#mode").value)) stopPlay();
  applyViewerControls();
}

// Reloads the member data; keeps the view, scenario and story filter unless the project changed.
async function loadViewer(fresh = false) {
  S.vdata = await api(`/api/projects/${S.project.id}/viewer`);
  const [scenarios, ratios, review] = [await file("scenarios.json", true), await file("scenario_ratios.json", true), await file("review_conditions.json", true)];
  $("#viewer-empty").classList.toggle("hidden", S.vdata.members.length > 0);
  S.viewer.setData(S.vdata, { scenarios, scenarioRatios: ratios, review }, S.project.id);

  const stories = S.vdata.stories || [], keep = !fresh && S.storyList === stories.join("|");
  const [lo, hi] = [$("#story-min").value, $("#story-max").value];
  const opts = stories.map((s, i) => `<option value="${i}">${s}</option>`).join("");
  $("#story-min").innerHTML = opts; $("#story-max").innerHTML = opts;
  $("#story-min").value = keep ? lo : 0;
  $("#story-max").value = keep ? hi : Math.max(0, stories.length - 1);
  S.storyList = stories.join("|");

  const sc = $("#scenario").value, g = $("#group").value;
  $("#scenario").innerHTML = (scenarios?.scenarios || []).map((s) => `<option value="${s.id}">${s.id} · ${s.location_id} ${s.story}</option>`).join("");
  if (!fresh && [...$("#scenario").options].some((o) => o.value === sc)) $("#scenario").value = sc;
  $("#group").innerHTML = `<option value="">all</option>` + Object.entries(S.vdata.groups || {}).map(([k, l]) => `<option value="${k}">${k}: ${l.join(" ")}</option>`).join("");
  if (!fresh && [...$("#group").options].some((o) => o.value === g)) $("#group").value = g;
  if (fresh) $("#mode").value = "";
  fillModes();
  applyViewerControls();
}

function initViewer() {
  S.viewer = new Viewer($("#viewer"), $("#legend"), $("#info"));
  for (const id of ["#ratio-basis", "#sizes-before", "#weight-basis", "#scenario", "#group"]) $(id).oninput = applyViewerControls;
  // the story range stays ordered: moving one end past the other moves both
  $("#story-min").oninput = () => { if (+$("#story-min").value > +$("#story-max").value) $("#story-max").value = $("#story-min").value; applyViewerControls(); };
  $("#story-max").oninput = () => { if (+$("#story-max").value < +$("#story-min").value) $("#story-min").value = $("#story-max").value; applyViewerControls(); };
  $("#mode").oninput = () => { if (!SCENARIO_MODES.has($("#mode").value)) stopPlay(); applyViewerControls(); };
  $("#scenario").addEventListener("input", () => stopPlay());
  $("#sc-prev").onclick = () => { stopPlay(); stepScenario(-1); };
  $("#sc-next").onclick = () => { stopPlay(); stepScenario(1); };
  $("#sc-play").onclick = () => (S.play ? stopPlay() : startPlay());
}

// Step through the scenarios. They show in the scenario views: the heat map when its ratios exist,
// otherwise the influence area.
function stepScenario(d) {
  const sel = $("#scenario"), n = sel.options.length;
  if (!n) return;
  sel.selectedIndex = (sel.selectedIndex + d + n) % n;
  if (!SCENARIO_MODES.has($("#mode").value)) $("#mode").value = available().heat ? "influence" : "heat";
  applyViewerControls();
}
function startPlay() {
  if (!$("#scenario").options.length) return;
  stepScenario(0);
  S.play = setInterval(() => stepScenario(1), 1600);
  $("#sc-play").textContent = "❚❚"; $("#sc-play").classList.add("on"); $("#sc-play").title = "Stop";
}
function stopPlay() {
  clearInterval(S.play); S.play = null;
  $("#sc-play").textContent = "▶"; $("#sc-play").classList.remove("on"); $("#sc-play").title = "Step through all scenarios";
}

function applyViewerControls() {
  if (!S.viewer || !S.vdata) return;
  const mode = $("#mode").value || "model";
  $("#ratio-toggle-wrap").classList.toggle("hidden", mode !== "ratio");
  $("#sizes-toggle-wrap").classList.toggle("hidden", mode !== "sizes");
  $("#weight-toggle-wrap").classList.toggle("hidden", mode !== "weight");
  $("#scenario-wrap").classList.toggle("dim", !SCENARIO_MODES.has(mode));
  $("#ratio-basis").querySelector('[value="first"]').disabled = !has("results_original.json");
  S.viewer.set({ mode, ratioBasis: $("#ratio-basis").value, sizesBefore: $("#sizes-before").checked,
    weightBasis: $("#weight-basis").value, scenario: $("#scenario").value, group: $("#group").value,
    storyMin: +$("#story-min").value || 0, storyMax: $("#story-max").value === "" ? 99 : +$("#story-max").value });
  viewerNote(mode);
}

// The per-scenario ratios are one design per scenario at the time they were computed: say when,
// and flag them when the design has changed since.
function viewerNote(mode) {
  let t = "";
  const ft = S.project.file_times || {};
  if (mode === "heat" && ft["scenario_ratios.json"] && ft["results.json"] > ft["scenario_ratios.json"])
    t = `Per-scenario ratios computed ${day(ft["scenario_ratios.json"])}, before the latest design (${day(ft["results.json"])}): they show the design at that time. Recompute in step 6.`;
  $("#viewer-note").innerHTML = t;
  $("#viewer-note").classList.toggle("hidden", !t);
}

function renderAll() {
  const p = S.project;
  $("#p-name").textContent = p.name;
  $("#p-model").textContent = p.ap_model;
  const e = $("#etabs-status");
  e.textContent = S.etabs ? "ETABS running" : "ETABS not running: viewing saved results";
  e.className = "pill " + (S.etabs ? "ok" : "bad");
  $("#stepbar").innerHTML = p.steps.map((s) => {
    const locked = s.n > 0 && p.steps[s.n - 1].status !== "done" && s.status === "todo";
    return `<div class="step ${s.status} ${locked ? "locked" : ""} ${s.n === S.step ? "selected" : ""}" data-step="${s.n}" title="${esc(s.message || "")}">
      <span class="n">${s.status === "done" ? "✓" : s.status === "failed" ? "!" : s.n}</span><span class="t">${esc(s.name)}</span></div>`;
  }).join("");
  document.querySelectorAll(".step").forEach((el) => (el.onclick = () => { S.step = +el.dataset.step; switchTab("step"); showStepView(S.step); renderAll(); }));
  const token = ++S.render;
  renderStep(token);
  renderResults(token);
}

document.querySelectorAll(".tab").forEach((b) => (b.onclick = () => switchTab(b.dataset.tab)));
function switchTab(t) {
  document.querySelectorAll(".tab").forEach((b) => b.classList.toggle("active", b.dataset.tab === t));
  $("#tab-step").classList.toggle("hidden", t !== "step");
  $("#tab-results").classList.toggle("hidden", t !== "results");
}

// ---------- step panels ----------
async function renderStep(token) {
  const n = S.step, p = S.project, s = p.steps[n];
  const locked = n > 0 && p.steps[n - 1].status !== "done";
  const running = S.job?.status === "running";
  const needsEtabs = ETABS_STEPS.has(n) && !S.etabs;
  const head = `<h3>${n} · ${esc(s.name)}</h3><p class="muted">${STEP_HELP[n]}</p>
    <div class="status-line ${s.status}">${statusText(s)}</div>
    <div class="actions">
      <button id="run-step" ${locked || running || needsEtabs ? "disabled" : ""}>${s.status === "done" ? "Run again" : "Run"}</button>
      <button id="cached-step" class="secondary" ${locked || running ? "disabled" : ""}>Use cached results</button>
    </div>
    ${locked ? `<p class="muted">Unlocks when step ${n - 1} is done.</p>` : needsEtabs ? `<p class="muted">Needs ETABS running with the model open.</p>` : ""}`;
  const body = await stepBody(n);
  if (token !== S.render) return;
  $("#tab-step").innerHTML = head + body;
  $("#run-step").onclick = () => runStep(n, false);
  $("#cached-step").onclick = () => runStep(n, true);
  bindStepActions(n);
}

function statusText(s) {
  const label = { todo: "Not run yet", running: "Running…", done: "Done", failed: "Failed", awaiting: "Waiting for your approval" }[s.status] || s.status;
  return `<b>${label}</b>${s.cached ? " (cached)" : ""}${s.message ? ` · ${esc(s.message)}` : ""}`;
}

async function runStep(n, cached) {
  if (n === 2 && !cached && !confirm("This calls Claude (about $0.50). Continue?")) return;
  if (!cached && S.project.steps[n].status === "done" && n < 7 && !confirm("Running this step again marks the later steps as not run. Continue?")) return;
  try {
    await post(`/api/projects/${S.project.id}/steps/${n}/run`, { cached });
  } catch (e) { alert(e.message); }
  await afterAction();
}

async function afterAction() {
  await refresh();
  S.files = {};
  await loadViewer();
  renderAll();
  pollNow();
}

async function stepBody(n) {
  const T = (rows, head) => `<table><tr>${head.map((h) => `<th${h.startsWith("#") ? ' class="num"' : ""}>${h.replace("#", "")}</th>`).join("")}</tr>${rows.join("")}</table>`;
  if (n === 0) {
    const c = await file("check_model.json");
    if (!c) return "";
    return T(c.items.map((i) => `<tr><td class="s-${i.status}">${i.status}</td><td><b>${esc(i.name)}</b><br>${esc(i.message)}</td></tr>`), ["", "check"]);
  }
  if (n === 1) {
    const s = await file("scenarios.json"), ax = await file("intact_axial.json");
    if (!s) return "";
    const rule = s.candidates.filter((c) => (c.source || "rule") === "rule");
    return `<p>${rule.length} rule locations, ${s.scenarios.length} scenarios${ax ? `; intact axial check: columns ${fmt(ax.check.lowest_columns_sum_kn ?? ax.check.story1_sum_kn, 1)} kN vs base reaction ${fmt(ax.check.base_reaction_fz_kn ?? ax.check.expected_kn, 1)} kN` : ""}.</p>` +
      T(rule.map((c) => `<tr><td><b>${c.location_id}</b></td><td>${c.reasons.map((r) => r.code.replace(/_/g, " ")).join(", ")}</td><td>${c.stories.map((x) => x.story.replace("Story", "S")).join(" ")}</td></tr>`), ["loc", "UFC reason", "stories"]);
  }
  if (n === 2) {
    const r = await file("review_conditions.json");
    if (!r) return "";
    const adds = r.review.decisions.filter((d) => d.decision === "add");
    const others = r.review.decisions.filter((d) => d.decision !== "add");
    const ev = (d) => d.evidence.map((e) => `${e.location_id} ${e.story} ${e.field} = ${e.value}`).join("<br>");
    const ok = r.evidence.filter((e) => e.status === "ok").length;
    const appr = await file("approved_candidates.json");
    const accepted = (loc) => !appr || appr.candidates.some((c) => c.location_id === loc && c.status !== "rejected");
    const dec = (d, add) => `<div class="decision ${add ? "add" : ""}"><h4>${add ? `<input type="checkbox" class="accept" value="${d.location_id}" ${accepted(d.location_id) ? "checked" : ""}>` : ""}${d.location_id} · ${d.decision} · ${d.condition.replace(/_/g, " ")} <span class="muted">${d.confidence}</span></h4>${esc(d.reason)}<div class="evidence">${ev(d)}</div></div>`;
    return `<p>Claude ${esc(r.meta.model)} · $${fmt(r.meta.cost_usd, 2)} · cited values checked: ${ok}/${r.evidence.length} match the condition table${r.issues.length ? ` · ${r.issues.length} validation issues` : ""}.</p>
      <h3>Suggested additions</h3>${adds.length ? adds.map((d) => dec(d, true)).join("") : `<p class="muted">none</p>`}
      <div class="actions"><button id="approve-scenarios" ${S.job?.status === "running" ? "disabled" : ""}>Approve scenario set</button></div>
      <h3>Rule candidates</h3>${others.map((d) => dec(d, false)).join("")}
      ${r.review.model_observations?.length ? `<h3>Observations</h3><ul class="notes">${r.review.model_observations.map((o) => `<li>${esc(o)}</li>`).join("")}</ul>` : ""}`;
  }
  if (n === 3) {
    const a = await file("apply.json");
    return a ? `<p class="big">${a.written} / ${a.total}</p><p>scenarios written and verified: one staged case, load group and combination each (${a.written * 3} objects); composite selection ${a.composite_selection_matches ? "matches steel" : "DIFFERS"}.</p>` : "";
  }
  if (n === 4) {
    const r = await file("results_original.json") || await file("results.json");
    if (!r) return "";
    const cases = Object.values(r.cases);
    const bad = Object.values(r.members).filter((m) => !m.passes).length;
    return `<p>${cases.filter((c) => c.reaction_check_ok).length}/${cases.length} pass the load check (base reaction increment vs expected, within 1%). First design: ${Object.keys(r.members).length} members, ${bad} over 1.0.</p>` +
      T(cases.map((c) => { const d = (100 * (c.increment_from_reactions_kn - c.increment_expected_kn)) / c.increment_expected_kn; return `<tr><td>${c.scenario}</td><td class="num">${fmt(c.increment_expected_kn)}</td><td class="num">${fmt(c.increment_from_reactions_kn)}</td><td class="num ${c.reaction_check_ok ? "s-ok" : "s-bad"}">${sign(d)}%</td></tr>`; }), ["scenario", "#expected kN", "#reactions kN", "#diff"]);
  }
  if (n === 5) {
    const rd = await file("rounds.json");
    if (!rd) return "";
    const R = rd.rounds;
    const mn = Math.min(...R.map((r) => r.tons)) * 0.98, mx = Math.max(...R.map((r) => r.tons)) * 1.01;
    const x = (i) => 30 + (i * 240) / Math.max(1, R.length - 1), y = (t) => 110 - ((t - mn) / (mx - mn)) * 90;
    const svg = `<svg viewBox="0 0 300 130"><polyline fill="none" stroke="var(--accent)" stroke-width="2" points="${R.map((r, i) => `${x(i)},${y(r.tons)}`).join(" ")}"/>${R.map((r, i) => `<circle cx="${x(i)}" cy="${y(r.tons)}" r="3.5" fill="var(--accent)"/><text x="${x(i)}" y="${y(r.tons) - 8}" font-size="10" text-anchor="middle">${fmt(r.tons, 1)}</text><text x="${x(i)}" y="126" font-size="10" text-anchor="middle">round ${r.number}</text>`).join("")}</svg>`;
    return `<p>${R.length} round(s), ${rd.converged ? "converged" : "not converged"} (weight change under ${fmt((rd.weight_tolerance || 0) * 100, 1)}% and nothing over 1.0).</p><div class="chart">${svg}</div>` +
      T(R.map((r) => `<tr><td>${r.number}</td><td class="num">${fmt(r.tons, 2)}</td><td class="num">${r.change_percent == null ? "–" : sign(r.change_percent) + "%"}</td><td class="num">${r.frames_differing}</td><td class="num">${fmt(r.steel_max_ratio, 3)}</td></tr>`), ["round", "#short tons", "#change", "#members changing", "#steel max"]);
  }
  if (n === 6) {
    const pr = await file("propagation.json"), fin = await file("finalize.json"), cond = await file("conditions.json");
    if (!pr) return "";
    const grp = {};
    for (const [g, locs] of Object.entries(cond?.symmetry?.groups || {})) for (const l of locs) grp[l] = g;
    const own = new Set(pr.rows.filter((r) => r.symmetry === "identity").map((r) => r.member));
    const by = {};
    for (const r of pr.rows) {
      const g = grp[r.removed.split(" ")[0]] || "?";
      by[g] = by[g] || { src: new Set(), copies: new Set() };
      if (r.symmetry === "identity") by[g].src.add(r.member);
      else if (r.governs && !own.has(r.counterpart)) by[g].copies.add(r.counterpart);
    }
    const s = pr.summary;
    let out = `<p>${s.frames_assigned} frames to fix: ${s.collapse_driven} collapse-driven, ${s.propagated_only} propagated; ${s.flagged_rows} flagged rows.</p>` +
      T(Object.entries(by).sort().map(([g, v]) => `<tr><td>${g}</td><td>${(cond?.symmetry?.groups?.[g] || []).join(" ")}</td><td class="num">${v.src.size}</td><td class="num">${v.copies.size}</td></tr>`), ["group", "locations", "#collapse-driven", "#copies"]) +
      (pr.flags?.length ? `<h3>Flags</h3><ul class="notes">${pr.flags.map((f) => `<li>${esc(f)}</li>`).join("")}</ul>` : `<p class="s-ok">No flags: every counterpart matched type, direction and original section.</p>`);
    const st = S.project.steps[6].status;
    out += `<div class="actions"><button id="approve-prop" ${S.job?.status === "running" || !S.etabs || st === "done" ? "disabled" : ""}>Approve: assign sections and finalize</button><button id="ratios" class="secondary" ${S.job?.status === "running" || !S.etabs ? "disabled" : ""}>Compute per-scenario ratios (≈5 min)</button></div>`;
    if (fin) out += finalizeSummary(fin);
    return out;
  }
  if (n === 7) {
    const b = await file("baseline_tonnage.json");
    return (b ? `<p>Baseline (${esc(b.model)}): <b>${fmt(b.tonnage.total, 2)} short tons</b>, ${b.design.rounds} round(s), ${b.design.converged ? "converged" : "not converged"}; ${b.changed_from_original.frames} members differ from the original sizes.</p>` : "<p>No baseline yet: running this step computes it on the baseline copy.</p>") +
      `<h3>Report</h3><p class="muted">The submittal report is plan item E; it will be generated here.</p>`;
  }
  return "";
}

function finalizeSummary(fin) {
  const moves = (fin.rounds || []).flatMap((r) => r.moves.map((m) => ({ ...m, round: r.round })));
  return `<h3>Finalize: <span class="${fin.status === "passed" ? "s-ok" : "s-bad"}">${esc(fin.status)}</span></h3>
    <p>steel max ${fmt(fin.steel_max, 3)}, composite max ${fmt(fin.composite_max, 3)}; ${(fin.rounds || []).length} round(s) this run${fin.history?.length ? `, ${fin.history.length} earlier run(s)` : ""}.</p>` +
    (moves.length ? `<table><tr><th>round</th><th>member</th><th>from → to</th><th class="num">ratio</th><th>how</th></tr>${moves.map((m) => `<tr><td>${m.round}</td><td>${m.frame}</td><td class="mono">${m.from} → ${m.to}</td><td class="num">${fmt(m.ratio_before, 3)}</td><td>${esc(m.reason)}</td></tr>`).join("")}</table>` : "") +
    ((fin.history || []).length ? `<p class="muted">Earlier runs: ${fin.history.map((h) => `${h.status}, ${(h.rounds || []).length} round(s): ${(h.rounds || []).flatMap((r) => r.moves.map((m) => `${m.frame} ${m.from}→${m.to}`)).join(", ") || "no moves"}`).join("; ")}</p>` : "");
}

function bindStepActions(n) {
  if (n === 2 && $("#approve-scenarios")) $("#approve-scenarios").onclick = async () => {
    const accepted = [...document.querySelectorAll(".accept:checked")].map((x) => x.value);
    try { await post(`/api/projects/${S.project.id}/approve/scenarios`, { accepted }); } catch (e) { alert(e.message); }
    await afterAction();
  };
  if (n === 6 && $("#approve-prop")) $("#approve-prop").onclick = async () => {
    if (!confirm("Fix these sections in the AP copy and run finalize (several analyses)?")) return;
    try { await post(`/api/projects/${S.project.id}/approve/propagation`); } catch (e) { alert(e.message); }
    await afterAction();
  };
  if (n === 6 && $("#ratios")) $("#ratios").onclick = async () => {
    try { await post(`/api/projects/${S.project.id}/scenario-ratios`); } catch (e) { alert(e.message); }
    await afterAction();
  };
}

// ---------- results ----------
async function renderResults(token) {
  const ct = await file("collapse_tonnage.json"), base = await file("baseline_tonnage.json"), fin = await file("finalize.json");
  if (token !== S.render) return;
  if (!ct) { $("#tab-results").innerHTML = `<p class="muted">Results appear after step 6.</p>` + notes(); return; }
  const t = ct.tonnage.total, b = ct.baseline_total ?? base?.tonnage?.total, mx = Math.max(t, b || 0);
  const sp = ct.split_of_premium_over_baseline || {};
  const parts = [["Collapse-driven", sp.collapse_driven, "var(--collapse)"], ["Propagated", sp.propagated, "var(--propagated)"], ["Strength", sp.strength, "var(--strength)"]];
  const pos = parts.filter((p) => (p[1] || 0) > 0), tot = pos.reduce((a, p) => a + p[1], 0);
  $("#tab-results").innerHTML = `
    ${ct.premium ? `<div class="big">${sign(ct.premium.short_tons)} t</div><p class="muted" style="margin-top:0">${sign(ct.premium.percent, 1)}% steel over the strength-only design (short tons)</p>` : `<p>No baseline yet (step 7).</p>`}
    ${b ? `<div class="bar-row"><span>Strength design</span><div class="hbar" style="width:${(100 * b) / mx}%;background:var(--unchanged)"></div><span class="mono">${fmt(b, 1)}</span></div>` : ""}
    <div class="bar-row"><span>With collapse</span><div class="hbar" style="width:${(100 * t) / mx}%;background:var(--ink)"></div><span class="mono">${fmt(t, 1)}</span></div>
    ${ct.premium ? `<h3 style="margin-top:14px">Where the premium comes from</h3>
      <div class="stack">${pos.map(([, v, c]) => `<div style="width:${(100 * v) / tot}%;background:${c}"></div>`).join("")}</div>
      <div class="keys">${parts.map(([l, v, c]) => `<span style="--c:${c}">${l} ${sign(v, 1)} t</span>`).join("")}</div>` : ""}
    <p class="muted">Columns ${fmt(ct.tonnage.columns, 1)} t, steel girders ${fmt(ct.tonnage.steel_beams, 1)} t, composite beams ${fmt(ct.tonnage.composite_beams, 1)} t.</p>
    ${fin ? finalizeSummary(fin) : ""}
    ${reactionNote(ct)}
    ${notes()}`;
}

function reactionNote(ct) {
  const r = ct.reactions_vs_fresh_export;
  if (!r) return "";
  const bad = r.filter((x) => !x.ok);
  return `<h3>Load check (final model)</h3><p>${r.length - bad.length}/${r.length} scenarios within 1%${bad.length ? `; outside: ${bad.map((x) => `${x.scenario} ${sign(x.diff_percent)}%`).join(", ")}` : ""}.</p>`;
}

function notes() {
  return `<h3>Open notes</h3><ul class="notes">
    ${(S.project.notes || []).map((n) => `<li>${esc(n)}</li>`).join("")}
    <li>Simplifications: every m-factor 1.0; amplification 2.0 on every member; deck load at shared region edges counted conservatively (the neighbour's strip is amplified too); collapse sizes copied to every location in the symmetry group; gravity strength only (no connections, no wind).</li>
  </ul>`;
}

// ---------- log ----------
function startPolling() {
  clearInterval(S.poll);
  S.poll = setInterval(pollNow, 1500);
  pollNow();
  clearInterval(S.etabsPoll);
  S.etabsPoll = setInterval(checkEtabs, 5000);
}

// ETABS may be started or closed while a project is open: follow it, so the Run buttons unlock.
async function checkEtabs() {
  if (!S.project) return;
  let running;
  try { running = (await api("/api/etabs")).running; } catch { return; }
  if (running === S.etabs || !S.project) return;
  S.etabs = running;
  renderAll();
}
async function pollNow() {
  let j;
  try { j = await api(`/api/jobs/current?since=${S.job && S.job.id === S.jobId ? S.logLen : 0}`); } catch { return; }
  if (j.id !== S.jobId) { S.jobId = j.id; S.logLen = 0; $("#log").textContent = ""; if (j.id) j = await api(`/api/jobs/current?since=0`); }
  const was = S.job?.status;
  S.job = j;
  if (j.log?.length) {
    const el = $("#log");
    const atEnd = el.scrollTop + el.clientHeight >= el.scrollHeight - 30;
    el.textContent += j.log.join("\n") + "\n";
    if (atEnd) el.scrollTop = el.scrollHeight;
  }
  S.logLen = j.log_len || 0;
  const other = j.project && S.project && j.project !== S.project.id ? " (another project)" : "";
  $("#job-status").textContent = j.status === "idle" ? "idle" : `${j.step}${other}: ${j.status}${j.seconds != null ? ` (${j.seconds} s)` : ""}${j.error ? ` — ${j.error}` : ""}`;
  if (!S.project || was === j.status) return;
  if (was === "running") {   // a job just ended: its files and the step states changed
    await refresh(); S.files = {};
    await loadViewer();
  }
  renderAll();   // buttons follow the job state (disabled while one runs)
}
$("#log-toggle").onclick = () => {
  const bar = document.querySelector(".logbar");
  bar.classList.toggle("collapsed");
  $("#log-toggle").textContent = bar.classList.contains("collapsed") ? "show" : "hide";
  S.viewer?.resize();
};
$("#back").onclick = () => showLanding();

showLanding();
