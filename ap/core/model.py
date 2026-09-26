"""Loading the building JSON and config, plus small lookup helpers.

The building dict follows docs/schema/building.schema.json. We keep it as plain
dicts on purpose: it is the contract between modules, and dicts serialize
straight to the web viewer.
"""
from __future__ import annotations

import json
import tomllib
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    path = Path(path) if path else ROOT / "config" / "config.toml"
    with open(path, "rb") as f:
        return tomllib.load(f)


def load_building(path: str | Path) -> dict[str, Any]:
    return ensure_derived(json.loads(Path(path).read_text()))


def story_by_name(b: dict) -> dict[str, dict]:
    return {s["name"]: s for s in b["stories"]}


def level_z(b: dict) -> dict[str, float]:
    return {lv["name"]: lv["z"] for lv in b["levels"]}


def above_grade_stories(b: dict) -> list[dict]:
    """Stories ordered bottom to top, excluding below-grade and unoccupied ones.

    UFC 1-2.1: unoccupied stories (e.g. mechanical only) are not counted.
    """
    return [s for s in sorted(b["stories"], key=lambda s: s["bottom_z"])
            if not s.get("below_grade") and s.get("occupied", True)]


def columns_at(b: dict, location_id: str) -> list[dict]:
    """All column segments at one plan location, bottom to top."""
    return sorted((c for c in b["columns"] if c["location_id"] == location_id),
                  key=lambda c: c["bottom_z"])


def column(b: dict, location_id: str, story: str) -> dict | None:
    for c in b["columns"]:
        if c["location_id"] == location_id and c["story"] == story:
            return c
    return None


def bays_at_level(b: dict, level: str) -> list[dict]:
    return [a for a in b["bays"] if a["level"] == level]


def beams_at_level(b: dict, level: str) -> list[dict]:
    return [bm for bm in b["beams"] if bm["level"] == level]


def levels_at_or_above(b: dict, z: float, tol: float = 1e-6) -> list[str]:
    return [lv["name"] for lv in sorted(b["levels"], key=lambda l: l["z"]) if lv["z"] >= z - tol]


def roof_level(b: dict) -> str:
    return max(b["levels"], key=lambda l: l["z"])["name"]


# ---------- filling in what an ETABS export doesn't carry ----------

def _key(p, nd: int = 3):
    return (round(p[0], nd), round(p[1], nd))


def outline_from_bays(bays: list[dict]) -> list[list[float]]:
    """Outer boundary of a set of bay polygons: edges used by exactly one bay, chained.

    Works when neighbouring bays share whole edges (one area object per bay, drawn on
    grid). If bays meet at T-junctions the chain breaks; the largest loop found is returned.

    Corners are matched on coordinates rounded to 1 mm but returned as the bays'
    own coordinates, so columns on the outline test as on it exactly (an ETABS
    export in feet gives 51.2064 m, which rounded to 51.206 put a whole edge's
    columns off the outline).
    """
    from collections import Counter
    from .geometry import area

    count = Counter()
    actual: dict = {}
    for a in bays:
        poly = a["polygon"]
        for p in poly:
            actual.setdefault(_key(p), (p[0], p[1]))
        for i in range(len(poly)):
            e = tuple(sorted((_key(poly[i]), _key(poly[(i + 1) % len(poly)]))))
            count[e] += 1
    boundary = [e for e, c in count.items() if c == 1]
    nxt: dict = {}
    for a, c in boundary:
        nxt.setdefault(a, []).append(c)
        nxt.setdefault(c, []).append(a)
    loops, used = [], set()
    for start in list(nxt):
        if start in used:
            continue
        loop, prev, cur = [start], None, start
        used.add(start)
        while True:
            options = [q for q in nxt[cur] if q != prev]
            if not options:
                break
            prev, cur = cur, options[0]
            if cur == start:
                break
            if cur in used:
                break
            used.add(cur)
            loop.append(cur)
        if len(loop) >= 3:
            loops.append([list(actual[p]) for p in loop])
    if not loops:
        return []
    best = max(loops, key=area)
    # drop collinear vertices so edges run corner to corner
    out = []
    n = len(best)
    for i in range(n):
        a, b, c = best[i - 1], best[i], best[(i + 1) % n]
        cross = (b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0])
        if abs(cross) > 1e-9:
            out.append(b)
    return out


def ensure_derived(b: dict) -> dict:
    """Fill outlines (from bays) and grids (from column positions) when the export lacks them."""
    if not b.get("outlines"):
        b["outlines"] = {}
        for lv in b["levels"]:
            bays = [a for a in b["bays"] if a["level"] == lv["name"]]
            if bays:
                b["outlines"][lv["name"]] = outline_from_bays(bays)
    if not b.get("grids"):
        xs = sorted({round(c["x"], 3) for c in b["columns"]})
        ys = sorted({round(c["y"], 3) for c in b["columns"]})
        letters = [chr(ord("A") + i) if i < 26 else f"A{i - 25}" for i in range(len(ys))]
        b["grids"] = {"x": [{"name": str(i + 1), "coord": x} for i, x in enumerate(xs)],
                      "y": [{"name": letters[i], "coord": y} for i, y in enumerate(ys)],
                      "derived": True}
    return b


def load_stacks(path) -> dict:
    """stacks.json from `quikcolaps-bridge stacks`: {frame: {levels, influence_areas, stop}}."""
    return json.loads(Path(path).read_text())["stacks"]
