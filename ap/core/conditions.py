"""Condition table: the facts behind the judgment-based removal conditions. UFC 3-2.9.2.2.

The clause asks for extra removals where adjacent columns are lightly loaded,
where bays have different tributary sizes, and where members frame in at
different orientations or elevations. This module states those facts for every
perimeter column at every story, so the Claude review (claude_client) reads
numbers instead of inferring them. It decides nothing: no thresholds, no
candidates. Axial forces come from the intact 1.2D + 0.5L case in ETABS
(`intact_axial.json`, written from `bridge forces`).

    python -m core.conditions web/data/building.json --axial web/data/intact_axial.json \
        --out web/data/conditions.json

Definitions (all at the level at the top of the column segment):
- tributary area: each bay touching the column contributes area / number of its
  corners that have a column in this story (a quarter of a rectangular bay).
  tributary_above is the sum over this story and every story above.
- adjacent bays: the bays touching the column, with their plan dimensions.
- neighbours: along each beam framing in at the top joint and along the outline
  edges through the column, the nearest column in the same story.
- beams at top: beams with an end at the top joint (framing in) and beams whose
  span passes through it; direction in degrees from +x, offset = beam z - column top z.
- symmetry: plan reflections/rotations that map the framing (column and beam
  positions) onto itself; symmetry_group is a location's orbit under them. For
  each one, the floor areas with no image and the sections that differ are
  listed. symmetry_group_with_sections splits a group where the column sections
  up the height differ (G1a, G1b).
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from .candidates import perimeter_locations, reference_outline
from .geometry import area, bbox_dims, dist, edges, point_on_boundary, point_on_segment
from .model import above_grade_stories, columns_at, load_building, story_by_name

TOL = 1e-3  # m; ETABS exports in feet round-trip to about 1e-4 m


def _same(p, q, tol: float = TOL) -> bool:
    return dist(p, q) <= tol


def _angle(p, q) -> float:
    return round(math.degrees(math.atan2(q[1] - p[1], q[0] - p[0])) % 360.0, 1)


def _side(p, outline) -> list[str]:
    """Names of the outline edges the point lies on: south/north/east/west for
    axis-aligned edges (outward normal), edge_k otherwise."""
    ccw = sum(a[0] * c[1] - c[0] * a[1] for a, c in edges(outline)) > 0
    out = []
    for k, (a, c) in enumerate(edges(outline)):
        if not point_on_segment(p, a, c, TOL):
            continue
        dx, dy = c[0] - a[0], c[1] - a[1]
        nx, ny = (dy, -dx) if ccw else (-dy, dx)  # outward normal
        if abs(nx) < 1e-9:
            out.append("north" if ny > 0 else "south")
        elif abs(ny) < 1e-9:
            out.append("east" if nx > 0 else "west")
        else:
            out.append(f"edge_{k}")
    return sorted(out)


# ---------- symmetry ----------

def _plan_ops(b: dict):
    """The eight plan isometries about the centre of the column bounding box."""
    xs = [c["x"] for c in b["columns"]]
    ys = [c["y"] for c in b["columns"]]
    cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
    return {
        "identity": lambda x, y: (x, y),
        "mirror_x": lambda x, y: (2 * cx - x, y),        # about the vertical centre line
        "mirror_y": lambda x, y: (x, 2 * cy - y),        # about the horizontal centre line
        "rotate_180": lambda x, y: (2 * cx - x, 2 * cy - y),
        "rotate_90": lambda x, y: (cx - (y - cy), cy + (x - cx)),
        "rotate_270": lambda x, y: (cx + (y - cy), cy - (x - cx)),
        "mirror_diag": lambda x, y: (cx + (y - cy), cy + (x - cx)),
        "mirror_antidiag": lambda x, y: (cx - (y - cy), cy - (x - cx)),
    }


def _r(p, nd: int = 2):
    return (round(p[0], nd) + 0.0, round(p[1], nd) + 0.0)


def _framing(b: dict, op) -> tuple:
    cols = frozenset((c["story"], _r(op(c["x"], c["y"]))) for c in b["columns"])
    beams = frozenset((bm["level"], frozenset({_r(op(*bm["i"])), _r(op(*bm["j"]))})) for bm in b["beams"])
    return cols, beams


def symmetry(b: dict) -> dict:
    """Plan symmetries of the framing (column and beam positions), and for each one
    what breaks it: floor areas (bays, with their loads) with no image, and
    column / beam sections that differ from their image."""
    ops = _plan_ops(b)
    ref = _framing(b, ops["identity"])

    def bay_key(a, op):
        return (a["level"], frozenset(_r(op(*v)) for v in a["polygon"]),
                tuple(sorted(a.get("loads", {}).items())))

    bays_ref = {bay_key(a, ops["identity"]) for a in b["bays"]}
    col_sec = {(c["story"], _r((c["x"], c["y"]))): c["section"] for c in b["columns"]}
    beam_sec = {(bm["level"], frozenset({_r(bm["i"]), _r(bm["j"])})): bm["section"] for bm in b["beams"]}
    out = {}
    for name, op in ops.items():
        if name == "identity" or _framing(b, op) != ref:
            continue
        bays = sorted((a["id"] for a in b["bays"] if bay_key(a, op) not in bays_ref), key=lambda x: (len(x), x))
        cols = [c["id"] for c in b["columns"]
                if col_sec.get((c["story"], _r(op(c["x"], c["y"])))) != c["section"]]
        beams = sorted((bm["id"] for bm in b["beams"]
                        if beam_sec.get((bm["level"], frozenset({_r(op(*bm["i"])), _r(op(*bm["j"]))})))
                        != bm["section"]), key=lambda x: (len(x), x))
        out[name] = {"bays_without_image": bays, "columns_with_other_section": len(cols),
                     "beams_with_other_section": beams}
    return out


def symmetry_groups(b: dict, locs: dict, op_names: list[str]) -> dict[str, str]:
    """location_id -> group name. A group is the orbit of a plan location under
    op_names (plus identity); groups are named G1, G2, ... in order of their first location."""
    ops = _plan_ops(b)
    by_pt = {_r(p): k for k, p in locs.items()}
    order = sorted(locs, key=lambda k: (locs[k][0], locs[k][1]))
    out: dict[str, str] = {}
    n = 0
    for k in order:
        if k in out:
            continue
        n += 1
        for name in ["identity", *op_names]:
            img = by_pt.get(_r(ops[name](*locs[k])))
            if img is not None:
                out.setdefault(img, f"G{n}")
    return out


def section_subgroups(b: dict, groups: dict[str, str]) -> dict[str, str]:
    """Split each symmetry group by the column sections up the height: G1 stays G1
    where every member has the same sections, otherwise G1a, G1b, ..."""
    stack = {loc: tuple(c["section"] for c in columns_at(b, loc)) for loc in groups}
    out = {}
    for g in dict.fromkeys(groups.values()):
        members = sorted((l for l in groups if groups[l] == g), key=lambda s: (len(s), s))
        kinds = list(dict.fromkeys(stack[l] for l in members))
        for l in members:
            out[l] = g if len(kinds) == 1 else g + "abcdefghijklmnop"[kinds.index(stack[l])]
    return out


# ---------- per column ----------

def _columns_in_story(b: dict, story: str) -> dict[str, dict]:
    return {c["location_id"]: c for c in b["columns"] if c["story"] == story}


def tributary_area(b: dict, level: str, p, col_pts: list) -> tuple[float, list[dict]]:
    """(tributary area, adjacent bays) at one level for a column at p.

    col_pts: plan points of the columns under this level (the story below it).
    """
    trib, bays = 0.0, []
    for a in b["bays"]:
        if a["level"] != level or not point_on_boundary(p, a["polygon"], TOL):
            continue
        corners = sum(1 for v in a["polygon"] if any(_same(v, q) for q in col_pts)) or len(a["polygon"])
        trib += area(a["polygon"]) / corners
        dx, dy = bbox_dims(a["polygon"])
        bays.append({"id": a["id"], "dx_m": round(dx, 3), "dy_m": round(dy, 3),
                     "area_m2": round(area(a["polygon"]), 2), "corners_with_columns": corners})
    return trib, bays


def beams_at_joint(b: dict, level: str, p, top_z: float) -> list[dict]:
    out = []
    for bm in b["beams"]:
        if bm["level"] != level:
            continue
        i, j = bm["i"], bm["j"]
        if _same(i, p) or _same(j, p):
            far = j if _same(i, p) else i
            kind = "frames_in"
        elif point_on_segment(p, i, j, TOL):
            far, kind = j, "passes_through"
        else:
            continue
        out.append({"id": bm["id"], "section": bm["section"], "kind": kind,
                    "direction_deg": _angle(p, far), "length_m": round(dist(i, j), 3),
                    "z_offset_m": round(bm["z"] - top_z, 3)})
    return sorted(out, key=lambda r: (r["direction_deg"], r["id"]))


def nearest_on_ray(p, angle_deg: float, pts: dict) -> tuple[str, float] | None:
    ux, uy = math.cos(math.radians(angle_deg)), math.sin(math.radians(angle_deg))
    best = None
    for k, q in pts.items():
        vx, vy = q[0] - p[0], q[1] - p[1]
        t = vx * ux + vy * uy
        if t <= TOL or abs(vx * uy - vy * ux) > TOL:
            continue
        if best is None or t < best[1]:
            best = (k, t)
    return best


def condition_table(b: dict, axial: dict) -> dict:
    """axial: intact_axial.json ({columns: {frame: {p_kn, ...}}})."""
    p_of = {k: v["p_kn"] for k, v in axial["columns"].items()}
    outline = reference_outline(b)
    perim = perimeter_locations(b)
    stories = above_grade_stories(b)
    st_by = story_by_name(b)
    order = [s["name"] for s in stories]
    sym = symmetry(b)
    g_geo = symmetry_groups(b, perim, list(sym))
    g_sec = section_subgroups(b, g_geo)
    edge_dirs = [((a, c), (_angle(a, c), _angle(c, a))) for a, c in edges(outline)]

    # tributary area per (location, story) for all columns, so neighbours and
    # tributary_above can use it
    trib: dict[tuple[str, str], float] = {}
    bays_of: dict[tuple[str, str], list] = {}
    for s in stories:
        in_story = _columns_in_story(b, s["name"])
        pts = [(c["x"], c["y"]) for c in in_story.values()]
        for loc, c in in_story.items():
            t, bays = tributary_area(b, s["top_level"], (c["x"], c["y"]), pts)
            trib[(loc, s["name"])] = t
            bays_of[(loc, s["name"])] = bays

    def trib_above(loc: str, story: str) -> float:
        return sum(trib.get((loc, n), 0.0) for n in order[order.index(story):])

    rows = []
    for loc in sorted(perim, key=lambda k: (perim[k][0], perim[k][1])):
        p = perim[loc]
        segs = columns_at(b, loc)
        present = {c["story"] for c in segs}
        by_story = {c["story"]: c for c in segs}
        sides = _side(p, outline)
        for s in stories:
            col = by_story.get(s["name"])
            if col is None:
                continue
            k = order.index(s["name"])
            below = by_story.get(order[k - 1]) if k > 0 else None
            above = by_story.get(order[k + 1]) if k + 1 < len(order) else None
            in_story = _columns_in_story(b, s["name"])
            pts = {l: (c["x"], c["y"]) for l, c in in_story.items() if l != loc}
            beams = beams_at_joint(b, s["top_level"], p, col["top_z"])
            dirs = {bm["direction_deg"] for bm in beams}
            for (a, c), ds in edge_dirs:
                if point_on_segment(p, a, c, TOL):
                    dirs |= {d for d in ds if nearest_on_ray(p, d, pts)}
            p_self = p_of.get(col["id"])
            neigh = []
            for d in sorted(dirs):
                hit = nearest_on_ray(p, d, pts)
                if hit is None:
                    continue
                nl, nd = hit
                nc = in_story[nl]
                pn = p_of.get(nc["id"])
                neigh.append({
                    "location_id": nl, "direction_deg": d, "distance_m": round(nd, 3),
                    "framed": any(bm["direction_deg"] == d and bm["kind"] == "frames_in" for bm in beams),
                    "perimeter": nl in perim,
                    "p_kn": pn, "p_ratio_to_this": round(pn / p_self, 3) if pn and p_self else None,
                    "tributary_m2": round(trib[(nl, s["name"])], 2),
                })
            ta = trib_above(loc, s["name"])
            rows.append({
                "location_id": loc, "story": s["name"], "frame": col["id"],
                "x": round(p[0], 3), "y": round(p[1], 3), "sides": sides,
                "position": "corner" if len(sides) > 1 else "edge",
                "top_level": s["top_level"],
                "section": col["section"],
                "section_below": below["section"] if below else None,
                "section_above": above["section"] if above else None,
                "splice_below": bool(col.get("splice_at_bottom")) or bool(below and below["section"] != col["section"]),
                "continuous_to_roof": all(n in present for n in order[k:]),
                "tributary_m2": round(trib[(loc, s["name"])], 2),
                "tributary_above_m2": round(ta, 2),
                "adjacent_bays": bays_of[(loc, s["name"])],
                "p_kn": p_self,
                "p_per_tributary_above_kpa": round(p_self / ta, 2) if p_self and ta else None,
                "neighbours": neigh,
                "beams_at_top": beams,
                "beam_count": len(beams),
                "beam_directions_deg": sorted({bm["direction_deg"] for bm in beams}),
                "beam_z_offsets_m": sorted({bm["z_offset_m"] for bm in beams}),
                "symmetry_group": g_geo.get(loc),
                "symmetry_group_with_sections": g_sec.get(loc),
            })

    return {
        "model": b.get("meta", {}).get("name", ""),
        "axial_case": axial.get("case", ""),
        "definitions": __doc__.split("Definitions (all at the level at the top of the column segment):")[1].strip(),
        "symmetry": {
            "framing_ops": sym,
            "groups": _invert(g_geo),
            "groups_with_sections": _invert(g_sec),
        },
        "rows": rows,
    }


def _invert(groups: dict[str, str]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for loc, g in groups.items():
        out.setdefault(g, []).append(loc)
    return {g: sorted(v, key=lambda s: (len(s), s))
            for g, v in sorted(out.items(), key=lambda kv: (int(kv[0][1:].rstrip("abcdefghijklmnop")), kv[0]))}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("building")
    ap.add_argument("--axial", required=True, help="intact_axial.json (bridge forces on the intact case)")
    ap.add_argument("--out", default="web/data/conditions.json")
    args = ap.parse_args()
    b = load_building(args.building)
    axial = json.loads(Path(args.axial).read_text())
    t = condition_table(b, axial)
    Path(args.out).write_text(json.dumps(t, indent=1))
    sym = t["symmetry"]
    print(f"{len(t['rows'])} rows -> {args.out}")
    for op, ex in sym["framing_ops"].items():
        print(f"framing symmetry {op}: bays without image {ex['bays_without_image'] or '-'}, "
              f"columns with other section {ex['columns_with_other_section']}, "
              f"beams with other section {len(ex['beams_with_other_section'])}")
    for g, locs in sym["groups_with_sections"].items():
        print(f"  {g}: {' '.join(locs)}")


if __name__ == "__main__":
    main()
