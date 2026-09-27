"""Viewer data for the app's 3D modes: one row per member with geometry, original and final
section, reason, added weight, worst ratio (original and final design), governing scenario,
story and symmetry group. Built from the project's files; missing files just leave fields empty.

Reason: finalize (stepped up by finalize or a check step-up) > collapse (its own design under an
AP scenario, from propagation) > propagated (copied to a symmetry image) > strength (changed,
not assigned) > unchanged.
"""
from __future__ import annotations

import math
import re

from .projects import Project

M_TO_FT = 3.28084


def _w(section: str | None) -> float:
    m = re.search(r"X([\d.]+)$", section or "")
    return float(m.group(1)) if m else 0.0


def build(p: Project) -> dict:
    b = p.load("building.json")
    if not b:
        return {"members": [], "levels": [], "bays": []}
    final_b = p.load("building_final.json") or p.load("building_current.json") or b
    final_sec = {c["id"]: c["section"] for c in final_b["columns"]} | {m["id"]: m["section"] for m in final_b["beams"]}
    res = p.load("results.json") or {"members": {}}
    res0 = p.load("results_original.json") or {"members": {}}
    prop = p.load("propagation.json") or {}
    fin = p.load("finalize.json") or {}
    cond = p.load("conditions.json") or {}
    group_of = {loc: g for g, locs in (cond.get("symmetry", {}).get("groups") or {}).items() for loc in locs}

    collapse = {r["member"] for r in prop.get("rows", []) if r.get("symmetry") == "identity"}
    assigned = {a["frame"] for a in prop.get("assignments", [])}
    stepped = {r["counterpart"] for r in prop.get("check_rows", []) if r.get("from") != r.get("to")}
    for run in [fin] + fin.get("history", []):
        for rd in run.get("rounds", []):
            stepped |= {a["counterpart"] for a in rd.get("applied", [])}
    source_of = {}
    for r in prop.get("rows", []):
        if r.get("governs") and r.get("counterpart"):
            source_of[r["counterpart"]] = {"member": r["member"], "scenario": r["source_scenario"], "symmetry": r["symmetry"]}

    loc_xy = {}
    for c in b["columns"]:
        loc_xy.setdefault((round(c["x"], 2), round(c["y"], 2)), c["location_id"])
    level_z = {lv["name"]: lv["z"] for lv in b["levels"]}
    story_of_level = {s["top_level"]: s["name"] for s in b["stories"]}

    def reason(f: str, orig: str, fs: str) -> str:
        if f in stepped:
            return "finalize"
        if f in collapse:
            return "collapse"
        if f in assigned:
            return "propagated" if fs != orig else "unchanged"
        return "strength" if fs != orig else "unchanged"

    members = []

    def add(f, kind, a, bpt, story, orig, loc):
        fs = final_sec.get(f, orig)
        length_ft = math.dist(a, bpt) * M_TO_FT
        r1, r0 = res["members"].get(f, {}), res0["members"].get(f, {})
        members.append({
            "id": f, "kind": kind, "a": [round(x, 3) for x in a], "b": [round(x, 3) for x in bpt], "story": story,
            "location": loc, "group": group_of.get(loc) if loc else None,
            "original": orig, "final": fs, "reason": reason(f, orig, fs),
            "added_lb_per_ft": _w(fs) - _w(orig), "added_lb": round((_w(fs) - _w(orig)) * length_ft, 1),
            "length_ft": round(length_ft, 2),
            "ratio": r1.get("max_ratio"), "ratio_original": r0.get("max_ratio"),
            "governing": r1.get("governing_scenario") or (r1.get("governing_combo") or "").split("(")[0] or None,
            "design_kind": r1.get("kind"), "source": source_of.get(f),
        })

    for c in b["columns"]:
        add(c["id"], "column", (c["x"], c["y"], c["bottom_z"]), (c["x"], c["y"], c["top_z"]), c["story"], c["section"], c["location_id"])
    for m in b["beams"]:
        z = m.get("z", level_z.get(m["level"], 0))
        ends = [loc_xy.get((round(m["i"][0], 2), round(m["i"][1], 2))), loc_xy.get((round(m["j"][0], 2), round(m["j"][1], 2)))]
        loc = next((e for e in ends if e in group_of), None)
        add(m["id"], "beam", (m["i"][0], m["i"][1], z), (m["j"][0], m["j"][1], z), story_of_level.get(m["level"], m["level"]),
            m["section"], loc)

    return {
        "members": members,
        "levels": b["levels"],
        "stories": [s["name"] for s in sorted(b["stories"], key=lambda s: s["bottom_z"])],
        "bays": [{"id": a["id"], "level": a["level"], "z": a["z"], "polygon": a["polygon"]} for a in b["bays"]],
        "groups": cond.get("symmetry", {}).get("groups", {}),
    }
