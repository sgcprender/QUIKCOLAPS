// 3D viewer for the demo app: members as one instanced mesh, coloured and sized per view mode.
// Z is up (ETABS). Every instance maps back to its member (ETABS frame id) for the info card.
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
const FADED = new THREE.Color("#dde0dc");

function ratioColor(r) {
  if (r == null) return new THREE.Color("#c9cdca");
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
const wOf = (s) => { const m = /X([\d.]+)$/.exec(s || ""); return m ? +m[1] : 0; };
const fmt = (x, d = 0) => (x == null ? "–" : Number(x).toLocaleString(undefined, { maximumFractionDigits: d, minimumFractionDigits: d }));

export class Viewer {
  constructor(el, legend, info) {
    this.el = el; this.legend = legend; this.info = info;
    this.opts = { mode: "changed", ratioOriginal: false, sizesBefore: false, scenario: null, group: "", storyMin: 0, storyMax: 99, highlight: null };
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

  setData(data, extra = {}) {
    this.data = data; this.extra = extra;
    if (this.mesh) { this.scene.remove(this.mesh); this.mesh.geometry.dispose(); }
    this.members = data.members || [];
    this.storyIndex = Object.fromEntries((data.stories || []).map((s, i) => [s, i]));
    this.maxAddedPerFt = Math.max(1, ...this.members.map((m) => m.added_lb_per_ft || 0));
    this.maxAddedLb = Math.max(1, ...this.members.map((m) => m.added_lb || 0));
    this.maxW = Math.max(1, ...this.members.map((m) => Math.max(wOf(m.original), wOf(m.final))));
    const geo = new THREE.BoxGeometry(1, 1, 1);
    const mat = new THREE.MeshLambertMaterial({ color: 0xffffff });
    this.lambert = mat;
    this.flat = new THREE.MeshBasicMaterial({ color: 0xffffff });   // ratio views: unshaded, so the colours stay true
    this.mesh = new THREE.InstancedMesh(geo, mat, Math.max(1, this.members.length));
    this.mesh.instanceColor = new THREE.InstancedBufferAttribute(new Float32Array(Math.max(1, this.members.length) * 3), 3);
    this.scene.add(this.mesh);
    if (this.members.length && !this._framed) this.frame();
    this.update();
  }

  frame() {
    const box = new THREE.Box3();
    for (const m of this.members) { box.expandByPoint(new THREE.Vector3(...m.a)); box.expandByPoint(new THREE.Vector3(...m.b)); }
    const c = box.getCenter(new THREE.Vector3()), s = box.getSize(new THREE.Vector3()).length();
    this.controls.target.copy(c);
    this.camera.position.set(c.x - s * 0.55, c.y - s * 0.95, c.z + s * 0.45);
    this.camera.far = s * 20; this.camera.updateProjectionMatrix();
    this._framed = true;
  }

  set(opts) { Object.assign(this.opts, opts); this.update(); }

  visible(m) {
    const o = this.opts, si = this.storyIndex[m.story] ?? 0;
    if (si < o.storyMin || si > o.storyMax) return false;
    if (o.group && m.group !== o.group) return false;
    return true;
  }

  style(m) {
    const o = this.opts;
    const base = m.kind === "column" ? 0.16 : 0.11;
    if (o.highlight) {   // steps 1-2: the UFC locations stand out, everything else light grey
      return m.kind === "column" && o.highlight[m.location]
        ? [new THREE.Color(o.highlight[m.location]), 0.42] : [new THREE.Color("#c3c8c4"), base * 0.6];
    }
    switch (o.mode) {
      case "changed": {
        const [v] = REASON[m.reason] || REASON.unchanged;
        const t = m.added_lb_per_ft > 0 ? base + 0.34 * Math.sqrt(m.added_lb_per_ft / this.maxAddedPerFt) : base * 0.8;
        return [new THREE.Color(css(v)), t];
      }
      case "ratio": return this.ratioStyle(m, o.ratioOriginal ? m.ratio_original : m.ratio);
      case "heat": {
        if (this.removedSet?.has(m.id)) return [new THREE.Color("#111"), 0.06];
        const sr = this.extra.scenarioRatios?.ratios?.[o.scenario];
        return this.ratioStyle(m, sr ? sr[m.id] : null);
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
        const col = o.sizesBefore ? new THREE.Color("#7a868b")
          : (wOf(m.final) > wOf(m.original) ? new THREE.Color("#2d5d8f") : wOf(m.final) < wOf(m.original) ? new THREE.Color("#8fb3d6") : new THREE.Color("#7a868b"));
        return [col, t];
      }
    }
    return [new THREE.Color("#888"), base];
  }

  // Ratio colour, and thickness growing with the ratio, so the members working hardest stand out;
  // members without a ratio (composite beams, or none computed) stay thin and pale.
  ratioStyle(m, r) {
    if (r == null) return [new THREE.Color("#dfe2df"), 0.045];
    const col = m.kind === "column";
    const k = Math.min(r, 1.1) ** 2;   // quadratic: members near 1.0 get most of the thickness
    return [ratioColor(r), (col ? 0.07 : 0.05) + (col ? 0.46 : 0.38) * k];
  }

  update() {
    if (!this.mesh) return;
    this.mesh.material = !this.opts.highlight && (this.opts.mode === "ratio" || this.opts.mode === "heat") ? this.flat : this.lambert;
    const sc = (this.extra.scenarios?.scenarios || []).find((s) => s.id === this.opts.scenario);
    this.removedSet = new Set(this.opts.mode === "heat" && sc ? sc.removed_columns : []);
    const M = new THREE.Matrix4(), q = new THREE.Quaternion(), X = new THREE.Vector3(1, 0, 0);
    this.members.forEach((m, i) => {
      const a = new THREE.Vector3(...m.a), b = new THREE.Vector3(...m.b);
      const d = b.clone().sub(a), len = d.length();
      q.setFromUnitVectors(X, d.clone().normalize());
      let [col, t] = this.style(m);
      if (!this.visible(m)) { col = FADED.clone(); t = 0.03; }
      M.compose(a.clone().add(b).multiplyScalar(0.5), q, new THREE.Vector3(len, t, t));
      this.mesh.setMatrixAt(i, M);
      this.mesh.setColorAt(i, col);
    });
    this.mesh.instanceMatrix.needsUpdate = true;
    this.mesh.instanceColor.needsUpdate = true;
    this.drawOverlay(sc);
    this.drawLegend();
  }

  drawOverlay(sc) {
    this.overlay.clear();
    if (this.opts.mode !== "heat" || this.opts.highlight || !sc || !this.data) return;
    const bays = new Set(sc.region?.bays || []);
    const mat = new THREE.MeshBasicMaterial({ color: new THREE.Color(css("--accent")), transparent: true, opacity: 0.16, side: THREE.DoubleSide, depthWrite: false });
    for (const bay of this.data.bays || []) {
      if (!bays.has(bay.id)) continue;
      const shape = new THREE.Shape(bay.polygon.map(([x, y]) => new THREE.Vector2(x, y)));
      const mesh = new THREE.Mesh(new THREE.ShapeGeometry(shape), mat);
      mesh.position.z = bay.z + 0.02;
      this.overlay.add(mesh);
    }
    for (const m of this.members.filter((x) => this.removedSet.has(x.id))) {
      const pts = [new THREE.Vector3(...m.a), new THREE.Vector3(...m.b)];
      const line = new THREE.Line(new THREE.BufferGeometry().setFromPoints(pts),
        new THREE.LineDashedMaterial({ color: 0x111111, dashSize: 0.3, gapSize: 0.2 }));
      line.computeLineDistances();
      this.overlay.add(line);
    }
  }

  drawLegend() {
    const o = this.opts, L = [];
    this.legend.classList.toggle("hidden", !this.members?.length);
    if (!this.members?.length) return;
    if (o.highlight) {
      L.push(`<h4>Locations</h4>`);
      for (const [label, c] of this.extra.highlightKey || []) L.push(`<div class="item"><span class="sw" style="background:${c}"></span>${label}</div>`);
      L.push(`<div class="muted">Other members grey while a step shows locations.</div>`);
    } else if (o.mode === "changed") {
      L.push(`<h4>What changed</h4>`);
      for (const [, [v, label]] of Object.entries(REASON)) L.push(`<div class="item"><span class="sw" style="background:var(${v})"></span>${label}</div>`);
      L.push(`<div class="muted">Thickness grows with the weight increase (lb/ft).</div>`);
    } else if (o.mode === "ratio" || o.mode === "heat") {
      L.push(`<h4>${o.mode === "ratio" ? `Worst ratio, ${o.ratioOriginal ? "original" : "final"} design` : `Ratio under ${o.scenario || "–"}`}</h4>`);
      L.push(`<div class="bar" style="background:${gradient(RATIO_STOPS)}"></div>`);
      L.push(`<div class="ticks abs">${RATIO_STOPS.map(([r]) => `<span style="left:${r * 100}%">${r === 1 ? "1.0" : r}</span>`).join("")}</div>`);
      L.push(`<div class="item"><span class="sw" style="background:${OVER}"></span>over 1.0</div>`);
      L.push(`<div class="muted">Thicker as the ratio rises. Composite beams pale (steel design only).</div>`);
      if (o.mode === "heat") {
        const sc = (this.extra.scenarios?.scenarios || []).find((s) => s.id === o.scenario);
        const sr = this.extra.scenarioRatios?.ratios?.[o.scenario];
        if (sc) L.push(`<div style="margin-top:4px"><b>${sc.id}</b>: ${sc.location_id} removed at ${sc.story}${sc.removed_columns.length > 1 ? ` (${sc.removed_columns.length} columns)` : ""}</div>`);
        if (sr) {
          const vals = Object.values(sr), over = vals.filter((v) => v > 1).length;
          L.push(`<div class="muted">max ${fmt(Math.max(...vals), 3)}; ${vals.filter((v) => v > 0.9).length} members over 0.9${over ? `, ${over} over 1.0` : ""}</div>`);
        }
        L.push(`<div class="item"><span class="sw" style="background:#111"></span>removed column (dashed)</div>`);
        L.push(`<div class="item"><span class="sw" style="background:var(--accent);opacity:.4"></span>amplified bays</div>`);
      }
    } else if (o.mode === "weight") {
      const tot = o.weightBasis === "total", mx = tot ? this.maxAddedLb : this.maxAddedPerFt, u = tot ? "lb" : "lb/ft";
      L.push(`<h4>${tot ? "Added steel per member" : "Size increase per member"}</h4><div class="bar" style="background:${gradient(ADD_STOPS)}"></div>`);
      L.push(`<div class="ticks"><span>0</span><span>${fmt(mx / 2)}</span><span>${fmt(mx)} ${u}</span></div>`);
      L.push(`<div class="muted">${tot ? "(final − original lb/ft) × length" : "final − original section weight"}; darker and thicker = more upsized; unchanged pale grey, lighter section light blue.</div>`);
      const key = tot ? "added_lb" : "added_lb_per_ft";
      const top = this.members.filter((m) => m[key] > 0 && this.visible(m)).sort((a, b) => b[key] - a[key]).slice(0, 5);
      if (top.length) {
        L.push(`<h4 style="margin-top:8px">Most upsized</h4><div class="top">`);
        for (const m of top) L.push(`<span>${m.id}</span><span>${m.story}</span><span class="mono">${m.original} → ${m.final}</span><span>+${fmt(m[key])}</span>`);
        L.push(`</div>`);
      }
      const per = {};
      for (const m of this.members) per[m.story] = (per[m.story] || 0) + Math.max(0, m.added_lb || 0) / 2000;
      const stories = (this.data.stories || []).slice().reverse();
      const pmx = Math.max(1e-9, ...Object.values(per));
      L.push(`<h4 style="margin-top:8px">Added per story (short tons)</h4>`);
      for (const s of stories) L.push(`<div class="item"><span class="mono" style="width:56px">${s}</span><span style="height:8px;width:${(120 * (per[s] || 0)) / pmx}px;background:#b91c1c;border-radius:2px"></span><span class="mono">${fmt(per[s] || 0, 1)}</span></div>`);
    } else if (o.mode === "sizes") {
      L.push(`<h4>Sizes: ${o.sizesBefore ? "before (original)" : "after (final)"}</h4><div class="muted">Thickness ∝ √(lb/ft).</div>`);
      if (!o.sizesBefore) {
        L.push(`<div class="item"><span class="sw" style="background:#2d5d8f"></span>heavier than original</div>`);
        L.push(`<div class="item"><span class="sw" style="background:#8fb3d6"></span>lighter than original</div>`);
      }
      L.push(`<div class="item"><span class="sw" style="background:#7a868b"></span>${o.sizesBefore ? "original section" : "unchanged"}</div>`);
    }
    if (o.group || o.storyMin > 0 || o.storyMax < (this.data?.stories?.length ?? 99) - 1) L.push(`<div class="muted" style="margin-top:4px">Filtered members shown faded.</div>`);
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
    this.members.forEach((m, i) => {
      if (!this.visible(m)) return;
      pa.set(...m.a); pb.set(...m.b);
      const d2 = ray.distanceSqToSegment(pa, pb, onRay, onSeg);
      const depth = onRay.distanceTo(ray.origin);
      const tol = 8 * px * depth;
      if (d2 <= tol * tol && depth < bestScore) { bestScore = depth; best = i; }
    });
    if (best == null) { this.info.classList.add("hidden"); return; }
    const m = this.members[best];
    const heat = this.extra.scenarioRatios?.ratios?.[this.opts.scenario]?.[m.id];
    const reason = { collapse: "collapse-driven", propagated: "propagated (symmetry copy)", finalize: "finalize step-up", strength: "strength", unchanged: "unchanged" }[m.reason];
    const src = m.source && m.source.member !== m.id ? `<span>copied from</span><span>${m.source.member} (${m.source.scenario}, ${m.source.symmetry})</span>` : "";
    this.info.innerHTML = `<h4>${m.kind === "column" ? "Column" : "Beam"} ${m.id}${m.location ? ` · ${m.location}` : ""} · ${m.story}</h4>
      <div class="kv">
        <span>section</span><span class="mono">${m.original} → <b>${m.final}</b></span>
        <span>added</span><span>${fmt(m.added_lb_per_ft)} lb/ft · ${fmt(m.added_lb)} lb</span>
        <span>ratio</span><span>${fmt(m.ratio, 3)} final · ${fmt(m.ratio_original, 3)} original</span>
        ${heat != null ? `<span>${this.opts.scenario}</span><span>${fmt(heat, 3)}</span>` : ""}
        <span>governing</span><span>${m.governing || "–"}</span>
        <span>reason</span><span>${reason}</span>
        ${src}
        <span>group</span><span>${m.group || "–"}</span>
      </div>`;
    this.info.classList.remove("hidden");
  }
}
