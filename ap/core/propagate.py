"""Similarity propagation: copy collapse-driven section increases to equivalent locations.

UFC 2-2.3.1 (RC III/IV, applied here as good practice): when an element fails, the fix is
applied to similar elements too, not only the one analysed. Only the four removal locations
are analysed; the other columns of each symmetry group (core/conditions.py, G1..G5) would see
the same removal by symmetry, so the members that had to get heavier around an analysed removal
get the same size around every equivalent location.

    python -m core.propagate --results web/data/results.json --out web/data/propagation.json

Method (deterministic, no ETABS):
1. Source members: every frame in results.json whose design section is heavier than its current
   analysis section and whose governing combination belongs to an AP scenario.
2. Its position relative to the removed column of that scenario: offsets in grid bays along x
   and y (fractional for a beam: its midpoint), story offset, member type, beam direction (x/y).
3. For every other location in the removed column's symmetry group, the plan symmetry that maps
   the removed column there is applied to the member; the frame found at the image, same story
   (or level), is the counterpart. It must match: same type, same direction, same original
   section. Otherwise the row is flagged and nothing is copied.
4. Each frame's section: the heaviest required (its own design section as a source, every copy
   onto it), never lighter than its own design section or its current analysis section.

Output: `assignments` in the format `bridge assign-sections` reads ({frame, section, from}; from
= current analysis section), one per frame whose section changes, plus the detailed `rows`
(member, counterpart, from, to, source scenario, reason, flags) and the flags.

Weights: lb/ft from the AISC name (W14X145 -> 145). Anything else is flagged, not guessed.
"""
from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path

from .conditions import _plan_ops, _r
from .model import load_building


def weight(section: str) -> float | None:
    m = re.fullmatch(r"W\d+X(\d+(?:\.\d+)?)", section or "")
    return float(m.group(1)) if m else None


def _grid_index(coords: list[float], v: float) -> float:
    """Position of v along the grid lines, in bays (fractional between lines)."""
    cs = sorted(coords)
    if v <= cs[0]:
        return 0.0 if len(cs) < 2 else (v - cs[0]) / (cs[1] - cs[0])
    for k in range(len(cs) - 1):
        if cs[k] - 1e-6 <= v <= cs[k + 1] + 1e-6:
            return k + (v - cs[k]) / (cs[k + 1] - cs[k])
    return len(cs) - 1 + (v - cs[-1]) / (cs[-1] - cs[-2])


class Frames:
    """Columns and beams of a building, looked up by id and by position."""

    def __init__(self, b: dict):
        self.b = b
        order = [s["name"] for s in sorted(b["stories"], key=lambda s: s["bottom_z"])]
        self.story_index = {n: k for k, n in enumerate(order)}
        self.level_story = {s["top_level"]: s["name"] for s in b["stories"]}
        gx = [g["coord"] for g in b["grids"]["x"]]
        gy = [g["coord"] for g in b["grids"]["y"]]
        self.gx, self.gy = gx, gy
        self.info: dict[str, dict] = {}
        self.col_at: dict[tuple, str] = {}
        self.beam_at: dict[tuple, str] = {}
        for c in b["columns"]:
            self.info[c["id"]] = {"type": "column", "story": c["story"], "p": (c["x"], c["y"]),
                                  "section": c["section"], "direction": "z", "location_id": c["location_id"]}
            self.col_at[(c["story"], _r((c["x"], c["y"])))] = c["id"]
        for bm in b["beams"]:
            (xi, yi), (xj, yj) = bm["i"], bm["j"]
            d = "x" if abs(yj - yi) < 1e-6 else "y" if abs(xj - xi) < 1e-6 else "skew"
            self.info[bm["id"]] = {"type": "beam", "story": self.level_story.get(bm["level"], bm["level"]),
                                   "level": bm["level"], "i": (xi, yi), "j": (xj, yj),
                                   "p": ((xi + xj) / 2, (yi + yj) / 2), "section": bm["section"], "direction": d}
            self.beam_at[(bm["level"], frozenset({_r((xi, yi)), _r((xj, yj))}))] = bm["id"]

    def image(self, frame: str, op) -> str | None:
        f = self.info[frame]
        if f["type"] == "column":
            return self.col_at.get((f["story"], _r(op(*f["p"]))))
        return self.beam_at.get((f["level"], frozenset({_r(op(*f["i"])), _r(op(*f["j"]))})))

    def offset(self, frame: str, origin: tuple[float, float], origin_story: str) -> dict:
        f = self.info[frame]
        return {"bays_x": round(_grid_index(self.gx, f["p"][0]) - _grid_index(self.gx, origin[0]), 2),
                "bays_y": round(_grid_index(self.gy, f["p"][1]) - _grid_index(self.gy, origin[1]), 2),
                "stories": self.story_index.get(f["story"], 0) - self.story_index.get(origin_story, 0)}


def propagate(b: dict, results: dict, scenarios: dict, conditions: dict,
              current: dict[str, str] | None = None) -> dict:
    """current: frame -> current analysis section (default: the sections in b, the export)."""
    fr = Frames(b)
    cur = dict(current or {k: v["section"] for k, v in fr.info.items()})
    ops = _plan_ops(b)
    op_names = list(conditions["symmetry"]["framing_ops"])
    group_of = {loc: g for g, locs in conditions["symmetry"]["groups"].items() for loc in locs}
    members_of = conditions["symmetry"]["groups"]
    loc_xy = {c["location_id"]: (c["x"], c["y"]) for c in b["columns"]}
    scen = {s["id"]: s for s in scenarios["scenarios"]}
    design = {f: m["section"] for f, m in results["members"].items()}

    flags: list[str] = []
    rows: list[dict] = []
    need: dict[str, list[tuple[float, str, dict]]] = {}   # frame -> [(weight, section, row)]

    def require(frame: str, section: str, row: dict) -> None:
        need.setdefault(frame, []).append((weight(section) or 0.0, section, row))

    sources = []
    for f, m in sorted(results["members"].items(), key=lambda kv: (len(kv[0]), kv[0])):
        sid = m.get("governing_scenario")
        if not sid or f not in fr.info:
            continue
        wd, wa = weight(m["section"]), weight(cur.get(f, ""))
        if wd is None or wa is None:
            flags.append(f"{f}: section name not a W shape ({cur.get(f)} -> {m['section']}); not used")
            continue
        if wd > wa:
            sources.append((f, sid))

    for f, sid in sources:
        s = scen.get(sid)
        if s is None:
            flags.append(f"{f}: governing scenario {sid} not in scenarios.json")
            continue
        loc0, st0 = s["location_id"], s["story"]
        if len(s["removed_columns"]) > 1:
            flags.append(f"{sid}: {len(s['removed_columns'])} removed columns; offsets taken from {loc0}")
        p0 = loc_xy[loc0]
        off = fr.offset(f, p0, st0)
        info = fr.info[f]
        base = {"member": f, "type": info["type"], "direction": info["direction"], "story": info["story"],
                "source_scenario": sid, "removed": f"{loc0} {st0}", "offset": off}
        own = {**base, "counterpart": f, "location": loc0, "symmetry": "identity",
               "from": cur[f], "to": design[f], "reason": "collapse-driven: own design section", "flags": []}
        rows.append(own)
        require(f, design[f], own)

        g = group_of.get(loc0)
        if g is None:
            flags.append(f"{sid}: removed column {loc0} is in no symmetry group; {f} not propagated")
            continue
        for loc in members_of[g]:
            if loc == loc0:
                continue
            maps = [n for n in op_names if _r(ops[n](*p0)) == _r(loc_xy[loc])]
            if not maps:
                flags.append(f"{f}: no symmetry maps {loc0} to {loc}")
                continue
            for n in maps:
                cp = fr.image(f, ops[n])
                row = {**base, "counterpart": cp, "location": loc, "symmetry": n,
                       "from": cur.get(cp) if cp else None, "to": None,
                       "reason": f"propagated from {f} ({sid}, removal {loc0} {st0}) by {n}", "flags": []}
                if cp is None:
                    row["flags"].append("no frame at the mirrored position")
                else:
                    ci = fr.info[cp]
                    row["counterpart_offset"] = fr.offset(cp, loc_xy[loc], st0)
                    if ci["type"] != info["type"]:
                        row["flags"].append(f"type differs ({ci['type']} vs {info['type']})")
                    if ci["direction"] != info["direction"]:
                        row["flags"].append(f"direction differs ({ci['direction']} vs {info['direction']})")
                    if ci["section"] != info["section"]:
                        row["flags"].append(f"original section differs ({ci['section']} vs {info['section']})")
                if row["flags"]:
                    flags.append(f"{f} -> {cp or '?'} at {loc} ({n}): {'; '.join(row['flags'])}; not copied")
                else:
                    row["to"] = design[f]
                    require(cp, design[f], row)
                rows.append(row)

    assignments, final = [], {}
    for frame, reqs in need.items():
        floor = [(weight(x) or 0.0, x) for x in (design.get(frame), cur.get(frame)) if x]
        cands = [(w, s) for w, s, _ in reqs] + floor
        top = max(w for w, _ in cands)
        winners = sorted({s for w, s in cands if w == top})
        if len(winners) > 1:
            flags.append(f"{frame}: sections of equal weight {winners}; took {winners[0]}")
        to = winners[0]
        final[frame] = to
        by = [r for w, s, r in reqs if s == to]
        for w, s, r in reqs:
            r["governs"] = s == to and r is by[0]
        if to != cur.get(frame):
            assignments.append({"frame": frame, "section": to, "from": cur.get(frame)})
    for r in rows:
        r["final"] = final.get(r["counterpart"]) if r["counterpart"] else None
        r.setdefault("governs", False)

    order = lambda f: (len(f), f)
    assignments.sort(key=lambda a: order(a["frame"]))
    kind = {}
    for r in rows:
        if r["counterpart"] and r["to"]:
            k = "collapse" if r["symmetry"] == "identity" else "propagated"
            if kind.get(r["counterpart"]) != "collapse":
                kind[r["counterpart"]] = k
    changed = {a["frame"] for a in assignments}
    return {
        "method": __doc__.split("Method (deterministic, no ETABS):")[1].split("Output:")[0].strip(),
        "symmetry_ops": op_names,
        "summary": {
            "sources": len(sources),
            "frames_changed": len(assignments),
            "collapse_driven": sum(1 for f in changed if kind.get(f) == "collapse"),
            "propagated_only": sum(1 for f in changed if kind.get(f) == "propagated"),
            "rows": len(rows),
            "flagged_rows": sum(1 for r in rows if r["flags"]),
            "added_weight_lb_per_ft": sum((weight(a["section"]) or 0) - (weight(a["from"]) or 0) for a in assignments),
        },
        "assignments": assignments,
        "rows": rows,
        "flags": flags,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--building", default="web/data/building.json",
                    help="current analysis sections and geometry (re-export after a redesign round)")
    ap.add_argument("--original", default=None,
                    help="building.json with the original sections, for the counterpart check (default: --building)")
    ap.add_argument("--results", default="web/data/results.json")
    ap.add_argument("--scenarios", default="web/data/scenarios.json")
    ap.add_argument("--conditions", default="web/data/conditions.json")
    ap.add_argument("--out", default="web/data/propagation.json")
    args = ap.parse_args()
    cur_b = load_building(args.building)
    b = load_building(args.original) if args.original else cur_b
    current = {c["id"]: c["section"] for c in cur_b["columns"]} | {m["id"]: m["section"] for m in cur_b["beams"]}
    out = propagate(b, json.loads(Path(args.results).read_text()), json.loads(Path(args.scenarios).read_text()),
                    json.loads(Path(args.conditions).read_text()), current)
    Path(args.out).write_text(json.dumps(out, indent=1))
    s = out["summary"]
    print(f"{s['sources']} collapse-driven members, {s['rows']} rows ({s['flagged_rows']} flagged) -> "
          f"{s['frames_changed']} frames to assign ({s['collapse_driven']} collapse-driven, "
          f"{s['propagated_only']} propagated) -> {args.out}")
    for f in out["flags"][:20]:
        print(f"  flag: {f}")


if __name__ == "__main__":
    main()
