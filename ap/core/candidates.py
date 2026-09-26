"""Rule-based external column removal candidates. UFC 3-2.9.2.2.

Minimum set (one each): a corner, near the middle of the long side, near the
middle of the short side. Plus every re-entrant corner and every perimeter
location where the bay size changes abruptly. Judgment-based locations are left
to Claude (claude_client) and the user.

Plan geometry is taken from the outline of the first above-grade floor level.
"""
from __future__ import annotations

from .geometry import (dist, edges, midpoint, point_in_polygon, point_on_boundary,
                       point_on_segment, vertex_convexity)
from .model import above_grade_stories
from .stories import select_stories

CLAUSE = "3-2.9.2.2"


def _plan_locations(b: dict) -> dict[str, tuple[float, float]]:
    locs = {}
    for c in b["columns"]:
        locs.setdefault(c["location_id"], (c["x"], c["y"]))
    return locs


def reference_outline(b: dict) -> list[list[float]]:
    first = above_grade_stories(b)[0]
    return b["outlines"][first["top_level"]]


def perimeter_locations(b: dict) -> dict[str, tuple[float, float]]:
    outline = reference_outline(b)
    return {k: p for k, p in _plan_locations(b).items() if point_on_boundary(p, outline)}


def _locs_on_edge(perim: dict, a, c) -> list[tuple[str, tuple[float, float]]]:
    on = [(k, p) for k, p in perim.items() if point_on_segment(p, a, c)]
    return sorted(on, key=lambda kp: dist(a, kp[1]))


def _nearest_interior_to_mid(perim: dict, a, c) -> str | None:
    on = _locs_on_edge(perim, a, c)
    interior = [(k, p) for k, p in on if dist(p, a) > 1e-6 and dist(p, c) > 1e-6]
    if not interior:
        return None
    m = midpoint(a, c)
    # tie-break: closer to the edge start, then by id, so results are reproducible
    return min(interior, key=lambda kp: (round(dist(kp[1], m), 6), dist(kp[1], a), kp[0]))[0]


def generate_candidates(b: dict, cfg: dict) -> list[dict]:
    outline = reference_outline(b)
    perim = perimeter_locations(b)
    convex = vertex_convexity(outline)
    found: dict[str, list[dict]] = {}

    def add(loc: str, code: str, note: str = "") -> None:
        found.setdefault(loc, [])
        if not any(r["code"] == code for r in found[loc]):
            found[loc].append({"code": code, "clause": CLAUSE, "note": note})

    # corners: one convex corner (the first vertex with a column); re-entrant: all
    corner_done = False
    for v, is_convex in zip(outline, convex):
        loc = next((k for k, p in perim.items() if dist(p, v) <= 1e-6), None)
        if loc is None:
            continue
        if is_convex and not corner_done:
            add(loc, "corner")
            corner_done = True
        elif not is_convex:
            add(loc, "re_entrant_corner")

    # long side = longest outline edge; short side = longest edge perpendicular to it
    eds = edges(outline)
    lengths = [dist(a, c) for a, c in eds]
    li = max(range(len(eds)), key=lambda i: lengths[i])
    la, lc = eds[li]
    ldir = ((lc[0] - la[0]) / lengths[li], (lc[1] - la[1]) / lengths[li])
    perp = [i for i, (a, c) in enumerate(eds)
            if abs(((c[0] - a[0]) * ldir[0] + (c[1] - a[1]) * ldir[1]) / lengths[i]) < 1e-6]
    loc = _nearest_interior_to_mid(perim, la, lc)
    if loc:
        add(loc, "mid_long_side")
    if perp:
        si = max(perp, key=lambda i: lengths[i])
        loc = _nearest_interior_to_mid(perim, *eds[si])
        if loc:
            add(loc, "mid_short_side")

    # abrupt bay-size change along each perimeter edge
    ratio = cfg["removal"]["bay_change_ratio"]
    for a, c in eds:
        on = _locs_on_edge(perim, a, c)
        for (k0, p0), (k1, p1), (k2, p2) in zip(on, on[1:], on[2:]):
            s1, s2 = dist(p0, p1), dist(p1, p2)
            if s1 > 0 and s2 > 0 and max(s1, s2) / min(s1, s2) >= ratio:
                add(k1, "bay_size_change", f"adjacent spans {s1:.2f} m / {s2:.2f} m")

    cands = []
    for loc, reasons in found.items():
        x, y = perim[loc]
        cands.append({
            "location_id": loc,
            "x": x, "y": y,
            "reasons": reasons,
            "stories": select_stories(b, loc),
            "source": "rule",
            "mandatory": any(r["code"] in ("corner", "mid_long_side", "mid_short_side") for r in reasons),
        })
    return sorted(cands, key=lambda c: c["location_id"])


def difficult_geometry_flags(b: dict, location_id: str, radius_m: float = 12.0) -> list[str]:
    """Cheap triggers that mark a candidate for Claude's affected-region judgment.

    - the column line does not run continuously to the roof
    - a floor outline above does not contain this plan location (setback)
    - a column within radius_m is flagged by the extractor as landing on a beam
    """
    flags = []
    segs = [c for c in b["columns"] if c["location_id"] == location_id]
    if not segs:
        return ["no_columns_at_location"]
    stories = above_grade_stories(b)
    if len({c["story"] for c in segs}) < len(stories):
        flags.append("column_line_not_continuous_to_roof")
    p = (segs[0]["x"], segs[0]["y"])
    for lvl, poly in b.get("outlines", {}).items():
        if not point_in_polygon(p, poly):
            flags.append(f"setback_above_at_{lvl}")
    for c in b["columns"]:
        if c.get("lands_on_beam") and dist(p, (c["x"], c["y"])) <= radius_m:
            flags.append(f"landing_column_{c['id']}")
    return sorted(set(flags))
