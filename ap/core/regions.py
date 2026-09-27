"""Simultaneous removal and the amplified load region.

Simultaneous removal, UFC 3-2.9.2.2: any other column within 30% of the largest
dimension of the associated bay from the removal location is removed too.
"Associated bay" = the bays touching the removed column at the level at its top;
we take the largest plan dimension over those bays.

Amplified region, UFC 3-2.11.4.1 / Fig. 3-13: the bays immediately adjacent to
the removed element, at all floors above it (literal rule). Bays that don't
exist at a level (setbacks) simply drop out. Claude may propose a different
region for flagged geometry; that goes through user approval, not this module.

Region beams (the load group, D13): every beam inside or on the edge of a
region bay. In ETABS deck load reaches the group only through its beams, so a
beam on an edge shared with a bay outside the region also brings that bay's
strip; those are listed as shared_edge_beams and loads.py counts the strip.
"""
from __future__ import annotations

from .geometry import bbox_dims, dist, point_in_polygon, point_on_boundary, midpoint
from .model import bays_at_level, beams_at_level, levels_at_or_above, story_by_name


def bays_touching(b: dict, level: str, p) -> list[dict]:
    return [a for a in bays_at_level(b, level) if point_on_boundary(p, a["polygon"])]


def simultaneous_radius(b: dict, col: dict, fraction: float) -> float:
    """fraction x largest plan dimension of the bays touching the column."""
    st = story_by_name(b)[col["story"]]
    touching = bays_touching(b, st["top_level"], (col["x"], col["y"]))
    if not touching:
        return 0.0
    return fraction * max(max(bbox_dims(a["polygon"])) for a in touching)


def simultaneous_removals(b: dict, col: dict, fraction: float) -> list[dict]:
    p = (col["x"], col["y"])
    limit = simultaneous_radius(b, col, fraction)
    if limit <= 0:
        return []
    return [c for c in b["columns"]
            if c["story"] == col["story"] and c["id"] != col["id"]
            and dist(p, (c["x"], c["y"])) <= limit + 1e-9]


def region_beams(b: dict, level: str, lvl_bays: list[dict]) -> tuple[list[str], list[str]]:
    """(beams, shared_edge) ids at one level for the region bays lvl_bays (D13).

    beams: every beam whose midpoint is inside or on the edge of a region bay; all
    go in the load group. shared_edge: those of them whose midpoint also lies on
    the edge of a bay outside the region, i.e. beams that carry a neighbour's
    deck strip into the group.
    """
    ids = {a["id"] for a in lvl_bays}
    outside = [a for a in bays_at_level(b, level) if a["id"] not in ids]
    beams, shared = [], []
    for bm in beams_at_level(b, level):
        m = midpoint(bm["i"], bm["j"])
        if not any(point_in_polygon(m, a["polygon"]) for a in lvl_bays):
            continue
        beams.append(bm["id"])
        if any(point_on_boundary(m, a["polygon"]) for a in outside):
            shared.append(bm["id"])
    return beams, shared


def amplified_region(b: dict, removed: list[dict]) -> dict:
    """Bays and beams that receive the amplified load, level by level."""
    top_z = min(c["top_z"] for c in removed)
    levels = levels_at_or_above(b, top_z)
    pts = [(c["x"], c["y"]) for c in removed]
    bays, beams, shared = [], [], []
    for lvl in levels:
        lvl_bays = [a for a in bays_at_level(b, lvl)
                    if any(point_on_boundary(p, a["polygon"]) for p in pts)]
        bays += [a["id"] for a in lvl_bays]
        k, s = region_beams(b, lvl, lvl_bays)
        beams += k
        shared += s
    return {"levels": levels, "bays": bays, "beams": beams, "shared_edge_beams": shared, "source": "rule"}


def region_from_bays(b: dict, bay_ids: list[str], source: str = "approved") -> dict:
    """Rebuild a full region (levels, bays, beams) from an approved list of bay ids,
    e.g. when the user accepts Claude's proposed affected region."""
    bays = [a for a in b["bays"] if a["id"] in set(bay_ids)]
    levels = sorted({a["level"] for a in bays},
                    key=lambda n: next(lv["z"] for lv in b["levels"] if lv["name"] == n))
    beams, shared = [], []
    for lvl in levels:
        k, s = region_beams(b, lvl, [a for a in bays if a["level"] == lvl])
        beams += k
        shared += s
    return {"levels": levels, "bays": [a["id"] for a in bays], "beams": beams,
            "shared_edge_beams": shared, "source": source}
