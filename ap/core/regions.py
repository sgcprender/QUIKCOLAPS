"""Simultaneous removal and the amplified load region.

Simultaneous removal, UFC 3-2.9.2.2: any other column within 30% of the largest
dimension of the associated bay from the removal location is removed too.
"Associated bay" = the bays touching the removed column at the level at its top;
we take the largest plan dimension over those bays.

Amplified region, UFC 3-2.11.4.1 / Fig. 3-13: the bays immediately adjacent to
the removed element, at all floors above it (literal rule). Bays that don't
exist at a level (setbacks) simply drop out. Claude may propose a different
region for flagged geometry; that goes through user approval, not this module.
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


def amplified_region(b: dict, removed: list[dict]) -> dict:
    """Bays and beams that receive the amplified load, level by level."""
    top_z = min(c["top_z"] for c in removed)
    levels = levels_at_or_above(b, top_z)
    pts = [(c["x"], c["y"]) for c in removed]
    region_bays, region_beams = [], []
    for lvl in levels:
        lvl_bays = [a for a in bays_at_level(b, lvl)
                    if any(point_on_boundary(p, a["polygon"]) for p in pts)]
        region_bays += [a["id"] for a in lvl_bays]
        for bm in beams_at_level(b, lvl):
            m = midpoint(bm["i"], bm["j"])
            if any(point_in_polygon(m, a["polygon"]) for a in lvl_bays):
                region_beams.append(bm["id"])
    return {"levels": levels, "bays": region_bays, "beams": region_beams, "source": "rule"}


def region_from_bays(b: dict, bay_ids: list[str], source: str = "approved") -> dict:
    """Rebuild a full region (levels, bays, beams) from an approved list of bay ids,
    e.g. when the user accepts Claude's proposed affected region."""
    bays = [a for a in b["bays"] if a["id"] in set(bay_ids)]
    levels = sorted({a["level"] for a in bays},
                    key=lambda n: next(lv["z"] for lv in b["levels"] if lv["name"] == n))
    beams = []
    for lvl in levels:
        lvl_bays = [a for a in bays if a["level"] == lvl]
        for bm in beams_at_level(b, lvl):
            m = midpoint(bm["i"], bm["j"])
            if any(point_in_polygon(m, a["polygon"]) for a in lvl_bays):
                beams.append(bm["id"])
    return {"levels": levels, "bays": [a["id"] for a in bays], "beams": beams, "source": source}
