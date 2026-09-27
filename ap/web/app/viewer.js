// 3D viewer for the demo app: members as one instanced mesh, coloured and sized per view mode.
// Z is up (Engine / ETABS convention). Every instance maps back to its member (frame id) for the info card.
// Members outside the story / group filter are hidden; a faint wireframe of the whole frame stays for context.
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
const REASON = {
  collapse: ["--collapse", "Collapse-driven"],
  propagated: ["--propagated", "Propagated (symmetry copy)"],
  finalize: ["--finalize", "Finalize step-up"],
  strength: ["--strength", "Strength"],
  unchanged: ["--unchanged", "Unchanged"],
};
// idle members pale, working members saturated: pale blue → blue → green → amber → orange → red at 1.0
const RATIO_STOPS = [[0, "#c6d2e3"], [0.3, "#5b8fd9"], [0.5, "#16a34a"], [0.75, "#eab308"], [0.9, "#f97316"], [1.0, "#dc2626"]];
const OVER = "#c026d3";   // over 1.0: magenta, outside the scale
// added steel: light amber → deep red, so the most upsized members are the darkest and thickest
const ADD_STOPS = [[0, "#fdf0c4"], [0.3, "#f6b73c"], [0.65, "#dc2626"], [1, "#5c0a16"]];
const LIGHTER = "#93c5fd";
const PALE = "#dfe2df";
const RULE = "#c0392b", CLAUDE = "#7d4ab0", REJECTED = "#b9a9a6";
const REGION = "#2563eb", BAY = "#60a5fa";

export const MODES = {
  model: "Model",
  locations: "UFC locations",
  influence: "Influence area",
  ratio: "Ratio",
  heat: "Scenario heat map",
  changed: "What changed",
  weight: "Added weight",
  sizes: "Sizes",
};
export const SCENARIO_MODES = new Set(["influence", "heat"]);

function ratioColor(r) {
  if (r > 1.0) return new THREE.Color(OVER);
  return ramp(RATIO_STOPS, r);
}
function ramp(stops, v) {
  for (let k = 1; k < stops.length; k++) {
    const [v1, c1] = stops[k];
    if (v <= v1) {
      const [v0, c0] = stops[k - 1];
      return new THREE.Color(c0).lerp(new THREE.Color(c1), Math.max(0, (v - v0) / (v1 - v0)));
    }
  }
  return new THREE.Color(stops.at(-1)[1]);
}
const gradient = (stops) => `linear-gradient(90deg,${stops.map(([v, c]) => `${c} ${v * 100}%`).join(",")})`;
const ticks = (stops) => `<div class="ticks abs">${stops.map(([r]) => `<span style="left:${r * 100}%">${r === 1 ? "1.0" : r}</span>`).join("")}</div>`;
const wOf = (s) => { const m = /X([\d.]+)$/.exec(s || ""); return m ? +m[1] : 0; };
const fmt = (x, d = 0) => (x == null ? "–" : Number(x).toLocaleString(undefined, { maximumFractionDigits: d, minimumFractionDigits: d }));
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const item = (c, label, extra = "") => `<div class="item"><span class="sw" style="background:${c};${extra}"></span>${label}</div>`;

export class Viewer {
  constructor(el, legend, info) {
    this.el = el; this.legend = legend; this.info = info;
    this.opts = { mode: "model", ratioBasis: "latest", sizesBefore: false, weightBasis: "perft", scenario: null, group: "", storyMin: 0, storyMax: 99 };
    this.members = []; this.extra = {};
    this.renderer = new THREE.WebGLRenderer({ antialias: true });
    this.renderer.setPixelRatio(window.devicePixelRatio);
    this.renderer.setClearColor(new THREE.Color(css("--viewer-bg") || "#f4f5f2"));
    el.appendChild(this.renderer.domElement);
    this.scene = new THREE.Scene();
    this.camera = new THREE.PerspectiveCamera(40, 1, 0.1, 5000);
    this.camera.up.set(0, 0, 1);
    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = true;
    this.scene.add(new THREE.HemisphereLight(0xffffff, 0x8a9290, 1.1));
    const sun = new THREE.DirectionalLight(0xffffff, 1.4); sun.position.set(40, -60, 90); this.scene.add(sun);
    this.lambert = new THREE.MeshLambertMaterial({ color: 0xffffff });
    this.flat = new THREE.MeshBasicMaterial({ color: 0xffffff });   // colour-scale views: unshaded, so the colours stay true
    this.overlay = new THREE.Group(); this.scene.add(this.overlay);
    this.ray = new THREE.Raycaster();
    // a click that is not the end of an orbit drag picks a member
    this.renderer.domElement.addEventListener("pointerdown", (e) => (this._down = [e.clientX, e.clientY]));
    this.renderer.domElement.addEventListener("click", (e) => {
      if (!this._down || Math.hypot(e.clientX - this._down[0], e.clientY - this._down[1]) < 5) this.pick(e);
    });
    new ResizeObserver(() => this.resize()).observe(el);
    this.resize();
    const loop = () => { this.controls.update(); this.renderer.render(this.scene, this.camera); requestAnimationFrame(loop); };
    loop();
  }

  resize() {
    const w = this.el.clientWidth || 800, h = this.el.clientHeight || 600;
    this.renderer.setSize(w, h); this.camera.aspect = w / h; this.camera.updateProjectionMatrix();
  }

  // key: the project id; a different project re-frames the camera and closes the info card
  setData(data, extra = {}, key = null) {
    const fresh = key !== this.key;
    this.key = key; this.data = data; this.extra = extra;
    for (const o of [this.mesh, this.ghost]) if (o) { this.scene.remove(o); o.geometry.dispose(); }
    this.mesh = this.ghost = null;
    this.members = data.members || [];
    this.byId = Object.fromEntries(this.members.map((m) => [m.id, m]));
    this.storyIndex = Object.fromEntries((data.stories || []).map((s, i) => [s, i]));
    this.maxAddedPerFt = Math.max(1, ...this.members.map((m) => m.added_lb_per_ft || 0));
    this.maxAddedLb = Math.max(1, ...this.members.map((m) => m.added_lb || 0));
    this.maxW = Math.max(1, ...this.members.map((m) => Math.max(wOf(m.original), wOf(m.final))));
    if (fresh) { this.picked = null; this.info.classList.add("hidden"); }
    if (this.picked && !this.byId[this.picked]) this.picked = null;
    if (this.members.length) {
      this.mesh = new THREE.InstancedMesh(new THREE.BoxGeometry(1, 1, 1), this.lambert, this.members.length);
      this.mesh.instanceColor = new THREE.InstancedBufferAttribute(new Float32Array(this.members.length * 3), 3);
      this.scene.add(this.mesh);
      const pts = this.members.flatMap((m) => [...m.a, ...m.b]);
      const g = new THREE.BufferGeometry(); g.setAttribute("position", new THREE.Float32BufferAttribute(pts, 3));
      this.ghost = new THREE.LineSegments(g, new THREE.LineBasicMaterial({ color: 0xb9bfbb, transparent: true, opacity: 0.35 }));
      this.scene.add(this.ghost);
      if (this.framedKey !== key) { this.frame(); this.framedKey = key; }   // first data of this project
    }
    this.update();
  }

  frame() {
    const box = new THREE.Box3();
    for (const m of this.members) { box.expandByPoint(new THREE.Vector3(...m.a)); box.expandByPoint(new THREE.Vector3(...m.b)); }
    const c = box.getCenter(new THREE.Vector3()), s = box.getSize(new THREE.Vector3()).length();
    this.controls.target.copy(c);
    this.camera.position.set(c.x - s * 0.55, c.y - s * 0.95, c.z + s * 0.45);
    this.camera.far = s * 20; this.camera.updateProjectionMatrix();
  }

  set(opts) { Object.assign(this.opts, opts); this.update(); }

  storyVisible(story) {
    const si = this.storyIndex[story];
    return si == null || (si >= this.opts.storyMin && si <= this.opts.storyMax);
  }
  visible(m) {
    if (!this.storyVisible(m.story)) return false;
    if (this.opts.group && m.group !== this.opts.group) return false;
    return true;
  }

  scenario() { return (this.extra.scenarios?.scenarios || []).find((s) => s.id === this.opts.scenario) || null; }

  // Per-mode lookups, computed once per update
  prepare() {
    const o = this.opts, sc = SCENARIO_MODES.has(o.mode) ? this.scenario() : null;
    this.sc = sc;
    this.removed = new Set(sc ? [...sc.removed_columns, ...(sc.simultaneous_columns || [])] : []);
    this.regionBeams = new Set(sc?.region?.beams || []);
    this.loc = null;
    if (o.mode === "locations") {
      // location → {colour, removal stories}; rule candidates, Claude additions, and the approval status once approved
      const L = {};
      for (const c of this.extra.scenarios?.candidates || []) {
        const claude = (c.source || "rule") !== "rule";
        const col = c.status === "rejected" ? REJECTED : claude ? CLAUDE : RULE;
        L[c.location_id] = { col, stories: new Set((c.stories || []).map((x) => x.story)), label: c.status || (claude ? "suggested" : "rule") };
      }
      for (const d of this.extra.review?.review?.decisions || []) {
        if (d.decision === "add" && !L[d.location_id]) L[d.location_id] = { col: CLAUDE, stories: new Set(), label: "suggested" };
      }
      this.loc = L;
    }
  }

  // Ratio colour, and thickness growing with the ratio, so the members working hardest stand out;
  // members without a ratio (composite beams, or none computed) stay thin and pale.
  ratioStyle(m, r) {
    if (r == null) return [new THREE.Color(PALE), 0.045];
    const col = m.kind === "column", k = Math.min(r, 1.1) ** 2;   // quadratic: members near 1.0 get most of the thickness
    return [ratioColor(r), (col ? 0.07 : 0.05) + (col ? 0.46 : 0.38) * k];
  }

  style(m) {
    const o = this.opts;
    const base = m.kind === "column" ? 0.16 : 0.11;
    switch (o.mode) {
      case "model": return [new THREE.Color(m.kind === "column" ? "#58646a" : "#8d989c"), base * 0.8];
      case "locations": {
        const l = m.kind === "column" && this.loc[m.location];
        if (!l) return [new THREE.Color("#c9cec9"), base * 0.5];
        return l.stories.has(m.story) ? [new THREE.Color(l.col), 0.46] : [new THREE.Color(l.col).lerp(new THREE.Color("#ffffff"), 0.45), 0.2];
      }
      case "influence": {
        if (this.removed.has(m.id)) return [new THREE.Color("#111"), 0];
        if (this.regionBeams.has(m.id)) return [new THREE.Color(REGION), 0.3];
        return [new THREE.Color("#c9cec9"), base * 0.5];
      }
      case "ratio": return this.ratioStyle(m, o.ratioBasis === "first" ? m.ratio_original : m.ratio);
      case "heat": {
        if (this.removed.has(m.id)) return [new THREE.Color("#111"), 0];
        const sr = this.extra.scenarioRatios?.ratios?.[o.scenario];
        return this.ratioStyle(m, sr ? sr[m.id] : null);
      }
      case "changed": {
        const [v] = REASON[m.reason] || REASON.unchanged;
        const t = m.added_lb_per_ft > 0 ? base + 0.34 * Math.sqrt(m.added_lb_per_ft / this.maxAddedPerFt) : base * 0.8;
        return [new THREE.Color(css(v)), t];
      }
      case "weight": {
        const tot = o.weightBasis === "total";
        const v = tot ? m.added_lb : m.added_lb_per_ft, mx = tot ? this.maxAddedLb : this.maxAddedPerFt;
        if (!(v > 0)) return v < 0 ? [new THREE.Color(LIGHTER), base * 0.7] : [new THREE.Color("#d3d7d3"), 0.05];
        const f = v / mx;   // linear, so small increases stay pale and the big upsizes stand out
        return [ramp(ADD_STOPS, f), (m.kind === "column" ? 0.08 : 0.06) + 0.46 * f];
      }
      case "sizes": {
        const s = o.sizesBefore ? m.original : m.final;
        const t = 0.05 + 0.42 * Math.sqrt(wOf(s) / this.maxW);
        const col = o.sizesBefore ? "#7a868b" : wOf(m.final) > wOf(m.original) ? "#2d5d8f" : wOf(m.final) < wOf(m.original) ? "#8fb3d6" : "#7a868b";
        return [new THREE.Color(col), t];
      }
    }
    return [new THREE.Color("#888"), base];
  }

  update() {
    this.prepare();
    if (this.mesh) {
      this.mesh.material = ["ratio", "heat", "weight"].includes(this.opts.mode) ? this.flat : this.lambert;
      const M = new THREE.Matrix4(), q = new THREE.Quaternion(), X = new THREE.Vector3(1, 0, 0), Z0 = new THREE.Vector3(0, 0, 0);
      this.members.forEach((m, i) => {
        const a = new THREE.Vector3(...m.a), b = new THREE.Vector3(...m.b);
        const d = b.clone().sub(a), len = d.length();
        q.setFromUnitVectors(X, d.clone().normalize());
        const [col, t] = this.style(m);
        M.compose(a.clone().add(b).multiplyScalar(0.5), q, this.visible(m) && t > 0 ? new THREE.Vector3(len, t, t) : Z0);
        this.mesh.setMatrixAt(i, M);
        this.mesh.setColorAt(i, col);
      });
      this.mesh.instanceMatrix.needsUpdate = true;
      this.mesh.instanceColor.needsUpdate = true;
      this.mesh.computeBoundingSphere();
    }
    this.drawOverlay();
    this.drawLegend();
    this.drawInfo();
  }

  // Scenario views: amplified bays, the removed column(s) dashed, and the 30% radius at the removal story.
  drawOverlay() {
    for (const c of [...this.overlay.children]) { c.geometry?.dispose(); }
    this.overlay.clear();
    const sc = this.sc;
    if (!sc || !this.data) return;
    const bays = new Set(sc.region?.bays || []);
    const mat = new THREE.MeshBasicMaterial({ color: new THREE.Color(BAY), transparent: true, opacity: this.opts.mode === "influence" ? 0.6 : 0.35, side: THREE.DoubleSide, depthWrite: false });
    for (const bay of this.data.bays || []) {
      if (!bays.has(bay.id) || !this.storyVisible(bay.story)) continue;
      const shape = new THREE.Shape(bay.polygon.map(([x, y]) => new THREE.Vector2(x, y)));
      const mesh = new THREE.Mesh(new THREE.ShapeGeometry(shape), mat);
      mesh.position.z = bay.z + 0.02;
      this.overlay.add(mesh);
    }
    // removed column(s): thick black dashes along the axis (the member itself is not drawn)
    const dashMat = new THREE.MeshBasicMaterial({ color: 0x111111 });
    for (const id of this.removed) {
      const m = this.byId[id];
      if (!m || !this.storyVisible(m.story)) continue;
      const a = new THREE.Vector3(...m.a), b = new THREE.Vector3(...m.b), len = a.distanceTo(b), n = Math.max(2, Math.round(len / 0.6));
      for (let k = 0; k < n; k++) {
        const box = new THREE.Mesh(new THREE.BoxGeometry(0.2, 0.2, len / n * 0.55), dashMat);
        box.position.copy(a.clone().lerp(b, (k + 0.5) / n));
        this.overlay.add(box);
      }
    }
    const main = this.byId[sc.removed_columns[0]];
    if (this.opts.mode === "influence" && main && sc.simultaneous_radius_m && this.storyVisible(main.story)) {
      const r = sc.simultaneous_radius_m, pts = [];
      for (let k = 0; k <= 64; k++) { const t = (k / 64) * Math.PI * 2; pts.push(new THREE.Vector3(main.b[0] + r * Math.cos(t), main.b[1] + r * Math.sin(t), main.b[2] + 0.03)); }
      const ring = new THREE.Line(new THREE.BufferGeometry().setFromPoints(pts), new THREE.LineDashedMaterial({ color: 0xb45309, dashSize: 0.25, gapSize: 0.15 }));
      ring.computeLineDistances();
      this.overlay.add(ring);
    }
  }

  drawLegend() {
    const o = this.opts, L = [];
    this.legend.classList.toggle("hidden", !this.members.length);
    if (!this.members.length) return;
    const sc = this.sc;
    const scLine = sc ? `<div style="margin-top:4px"><b>${sc.id}</b>: ${esc(sc.location_id)} removed at ${esc(sc.story)}${this.removed.size > 1 ? ` (${this.removed.size} columns)` : ""}</div>` : "";
    if (o.mode === "model") {
      L.push(`<h4>Model</h4>`, item("#58646a", "column"), item("#8d989c", "beam"));
    } else if (o.mode === "locations") {
      L.push(`<h4>UFC removal locations</h4>`, item(RULE, "UFC rule location"));
      if (Object.values(this.loc).some((l) => l.col === CLAUDE)) L.push(item(CLAUDE, "Claude suggestion"));
      if (Object.values(this.loc).some((l) => l.col === REJECTED)) L.push(item(REJECTED, "rejected"));
      L.push(`<div class="muted">Thick: the removal stories; light: the rest of the column line.</div>`);
      const ids = Object.keys(this.loc);
      if (ids.length) L.push(`<div class="muted" style="margin-top:4px">${ids.map((k) => `${esc(k)} ${esc(this.loc[k].label)}`).join(" · ")}</div>`);
    } else if (o.mode === "influence") {
      L.push(`<h4>Influence area</h4>`);
      if (sc) {
        L.push(scLine);
        const inc = sc.increment?.increment_total_kn;
        L.push(`<div class="muted">${(sc.region?.bays || []).length} bays over ${(sc.region?.levels || []).length} floors, ${this.regionBeams.size} beams${inc ? `; increment ${fmt(+inc)} kN` : ""}</div>`);
        L.push(`<div class="muted">${(sc.location_reasons || []).map((r) => r.code.replace(/_/g, " ")).join(", ")}; ${(sc.story_reasons || []).map((r) => r.replace(/_/g, " ")).join(", ")}</div>`);
      } else L.push(`<div class="muted">No scenarios yet (step 1).</div>`);
      L.push(item("#111", "removed column (dashed)"), item(REGION, "amplified region: beams", ""), item(BAY, "amplified bays (load × 2.0)", "opacity:.6"));
      if (sc?.simultaneous_radius_m) L.push(item("#b45309", `30% radius, ${fmt(sc.simultaneous_radius_m, 2)} m`, "height:2px"));
    } else if (o.mode === "ratio" || o.mode === "heat") {
      L.push(`<h4>${o.mode === "ratio" ? `Worst ratio, ${o.ratioBasis === "first" ? "first design (step 4)" : "latest design"}` : `Ratio under ${esc(o.scenario || "–")}`}</h4>`);
      L.push(`<div class="bar" style="background:${gradient(RATIO_STOPS)}"></div>`, ticks(RATIO_STOPS));
      L.push(item(OVER, "over 1.0"));
      L.push(`<div class="muted">Thicker as the ratio rises. Composite beams pale (steel design only).</div>`);
      if (o.mode === "heat") {
        L.push(scLine);
        const sr = this.extra.scenarioRatios?.ratios?.[o.scenario];
        if (sr) {
          const vals = Object.values(sr), over = vals.filter((v) => v > 1).length;
          L.push(`<div class="muted">max ${fmt(Math.max(...vals), 3)}; ${vals.filter((v) => v > 0.9).length} members over 0.9${over ? `, ${over} over 1.0` : ""}</div>`);
        }
        L.push(item("#111", "removed column (dashed)"), item(BAY, "amplified bays", "opacity:.35"));
      }
    } else if (o.mode === "changed") {
      L.push(`<h4>What changed</h4>`);
      for (const [, [v, label]] of Object.entries(REASON)) L.push(item(`var(${v})`, label));
      L.push(`<div class="muted">Thickness grows with the weight increase (lb/ft).</div>`);
    } else if (o.mode === "weight") {
      const tot = o.weightBasis === "total", mx = tot ? this.maxAddedLb : this.maxAddedPerFt, u = tot ? "lb" : "lb/ft";
      L.push(`<h4>${tot ? "Added steel per member" : "Size increase per member"}</h4><div class="bar" style="background:${gradient(ADD_STOPS)}"></div>`);
      L.push(`<div class="ticks"><span>0</span><span>${fmt(mx / 2)}</span><span>${fmt(mx)} ${u}</span></div>`);
      L.push(`<div class="muted">${tot ? "(final − original lb/ft) × length" : "final − original section weight"}; darker and thicker = more upsized; unchanged pale grey, lighter section light blue.</div>`);
      const key = tot ? "added_lb" : "added_lb_per_ft";
      const top = this.members.filter((m) => m[key] > 0 && this.visible(m)).sort((a, b) => b[key] - a[key]).slice(0, 5);
      if (top.length) {
        L.push(`<h4 style="margin-top:8px">Most upsized (shown)</h4><div class="top">`);
        for (const m of top) L.push(`<span>${m.id}</span><span>${m.story}</span><span class="mono">${m.original} → ${m.final}</span><span>+${fmt(m[key])}</span>`);
        L.push(`</div>`);
      }
      const per = {};
      for (const m of this.members) per[m.story] = (per[m.story] || 0) + Math.max(0, m.added_lb || 0) / 2000;
      const pmx = Math.max(1e-9, ...Object.values(per));
      L.push(`<h4 style="margin-top:8px">Added per story (short tons)</h4>`);
      for (const s of (this.data.stories || []).slice().reverse()) {
        L.push(`<div class="item" style="opacity:${this.storyVisible(s) ? 1 : 0.4}"><span class="mono" style="width:56px">${s}</span><span style="height:8px;width:${(120 * (per[s] || 0)) / pmx}px;background:#b91c1c;border-radius:2px"></span><span class="mono">${fmt(per[s] || 0, 1)}</span></div>`);
      }
    } else if (o.mode === "sizes") {
      L.push(`<h4>Sizes: ${o.sizesBefore ? "before (original)" : "after (final)"}</h4><div class="muted">Thickness ∝ √(lb/ft).</div>`);
      if (!o.sizesBefore) L.push(item("#2d5d8f", "heavier than original"), item("#8fb3d6", "lighter than original"));
      L.push(item("#7a868b", o.sizesBefore ? "original section" : "unchanged"));
    }
    const nStories = this.data?.stories?.length ?? 0;
    if (o.group || o.storyMin > 0 || o.storyMax < nStories - 1) {
      const shown = this.members.filter((m) => this.visible(m)).length;
      L.push(`<div class="muted" style="margin-top:4px">Filter: ${shown} of ${this.members.length} members shown; the rest as a faint outline.</div>`);
    }
    this.legend.innerHTML = L.join("");
  }

  pick(e) {
    if (!this.mesh) return;
    const r = this.renderer.domElement.getBoundingClientRect();
    this.ray.setFromCamera(new THREE.Vector2(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1), this.camera);
    // nearest member axis to the ray, within ~8 px at its distance (members are too thin to hit)
    const ray = this.ray.ray, px = (2 * Math.tan((this.camera.fov * Math.PI) / 360)) / r.height;
    let best = null, bestScore = Infinity;
    const pa = new THREE.Vector3(), pb = new THREE.Vector3(), onRay = new THREE.Vector3(), onSeg = new THREE.Vector3();
    for (const m of this.members) {
      if (!this.visible(m)) continue;
      pa.set(...m.a); pb.set(...m.b);
      const d2 = ray.distanceSqToSegment(pa, pb, onRay, onSeg);
      const depth = onRay.distanceTo(ray.origin);
      const tol = 8 * px * depth;
      if (d2 <= tol * tol && depth < bestScore) { bestScore = depth; best = m.id; }
    }
    this.picked = best;
    this.drawInfo();
  }

  // The info card follows the view: it is redrawn when the mode, scenario or data change.
  drawInfo() {
    const m = this.picked && this.byId?.[this.picked];
    if (!m || !this.visible(m)) { this.info.classList.add("hidden"); return; }
    const o = this.opts;
    const inRegion = !!this.sc && this.regionBeams.has(m.id);
    const heat = o.mode === "heat" ? this.extra.scenarioRatios?.ratios?.[o.scenario]?.[m.id] : null;
    const reason = { collapse: "collapse-driven", propagated: "propagated (symmetry copy)", finalize: "finalize step-up", strength: "strength", unchanged: "unchanged" }[m.reason];
    const src = m.source && m.source.member !== m.id ? `<span>copied from</span><span>${m.source.member} (${m.source.scenario}, ${m.source.symmetry})</span>` : "";
    const changed = m.final && m.final !== m.original;
    this.info.innerHTML = `<button class="link close" title="Close">×</button><h4>${m.kind === "column" ? "Column" : "Beam"} ${m.id}${m.location ? ` · ${m.location}` : ""} · ${m.story}</h4>
      <div class="kv">
        <span>section</span><span class="mono">${changed ? `${m.original} → <b>${m.final}</b>` : m.original}</span>
        ${changed ? `<span>added</span><span>${fmt(m.added_lb_per_ft)} lb/ft · ${fmt(m.added_lb)} lb</span>` : ""}
        <span>ratio</span><span>${fmt(m.ratio_original, 3)} first · ${fmt(m.ratio, 3)} latest</span>
        ${heat != null || inRegion ? `<span>${esc(o.scenario)}</span><span>${heat != null ? `<b>${fmt(heat, 3)}</b>` : ""}${heat != null && inRegion ? " · " : ""}${inRegion ? "in the amplified region" : ""}</span>` : ""}
        <span>governing</span><span>${m.governing || "–"}</span>
        <span>reason</span><span>${reason}</span>
        ${src}
        <span>group</span><span>${m.group || "–"}</span>
      </div>`;
    this.info.querySelector(".close").onclick = () => { this.picked = null; this.info.classList.add("hidden"); };
    this.info.classList.remove("hidden");
  }
}
