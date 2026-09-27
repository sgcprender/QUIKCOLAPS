"""Scenario increment loads.

Base loading on the whole building:     G   = 1.2 D + (0.5 L or 0.2 S)
Amplified region (UFC 3-2.11.4):        G_A = amp * G
So each scenario adds an increment of   (amp - 1) * G   on its region only.

D covers: slab superimposed dead + slab self-weight (area loads), beam
self-weight and facade line loads (frame loads), point loads. Wind is never
included. Live load is not reduced (config: live_load_reduction = false).

Beams on the boundary of the region are amplified in full (conservative; they
share load with non-region bays).

Deck floors (D13): in ETABS a load group's deck load reaches the structure only
through the group's beams, each taking its one-way tributary strip on both
sides, including a neighbouring bay's strip on a shared edge. When the region
bays carry `deck_span_deg`, the increment is computed that way (method
"deck_to_beams"); otherwise by area (method "area").

Factors: when the building carries `combination` (an ETABS export: the template's
initial case, D17), its factors are used for every bay, roof included, so the
increment is exactly what ETABS applies. Otherwise they come from config, with
the roof rule (0.5 Lr or 0.2 S) on the roof level.
"""
from __future__ import annotations

from .geometry import area, dist, midpoint, point_in_polygon
from .model import bays_at_level, beams_at_level, roof_level

G = 9.81e-3  # kN per kg


def _gravity_live(loads: dict, is_roof: bool, cfg: dict) -> float:
    lf = cfg["loads"]["live_factor"]
    sf = cfg["loads"]["snow_factor"]
    if not is_roof:
        return lf * loads.get("live_kpa", 0.0)
    rl = lf * loads.get("roof_live_kpa", 0.0)
    sn = sf * loads.get("snow_kpa", 0.0)
    rule = cfg["loads"]["roof_live_rule"]
    return {"max": max(rl, sn), "live": rl, "snow": sn}[rule]


_KINDS = ("self_weight", "sdl", "live", "roof_live", "snow")


def combination_factors(b: dict) -> dict | None:
    """Load factors exported from the ETABS initial case, or None (use config)."""
    combo = b.get("combination")
    if not combo:
        return None
    factors = combo.get("factors", {})
    missing = [k for k in _KINDS if k not in factors]
    if missing:
        raise ValueError(f"combination from {combo.get('initial_case')!r} has no factor for "
                         f"{', '.join(missing)}; see the export flags")
    return factors


def bay_combo_kpa(bay: dict, is_roof: bool, cfg: dict, factors: dict | None = None) -> float:
    ld = bay["loads"]
    if factors is not None:
        return (factors["self_weight"] * ld.get("slab_sw_kpa", 0.0)
                + factors["sdl"] * ld.get("sdl_kpa", 0.0)
                + factors["live"] * ld.get("live_kpa", 0.0)
                + factors["roof_live"] * ld.get("roof_live_kpa", 0.0)
                + factors["snow"] * ld.get("snow_kpa", 0.0))
    d = ld.get("sdl_kpa", 0.0) + ld.get("slab_sw_kpa", 0.0)
    return cfg["loads"]["dead_factor"] * d + _gravity_live(ld, is_roof, cfg)


_TOL = 1e-6


def _span_axis(bay: dict) -> int | None:
    """0 when the deck spans along X, 1 along Y, None when unknown or skewed."""
    ang = bay.get("deck_span_deg")
    if ang is None:
        return None
    a = ang % 180.0
    if min(a, 180.0 - a) < 1e-3:
        return 0
    if abs(a - 90.0) < 1e-3:
        return 1
    return None


def _box(poly) -> tuple[float, float, float, float] | None:
    """(x0, y0, x1, y1) of an axis-aligned rectangle, else None."""
    xs = [p[0] for p in poly]
    ys = [p[1] for p in poly]
    box = (min(xs), min(ys), max(xs), max(ys))
    if abs((box[2] - box[0]) * (box[3] - box[1]) - area(poly)) > 1e-6 * max(1.0, area(poly)):
        return None
    return box


def _supports(b: dict, bay: dict, axis: int) -> list[tuple[float, dict]]:
    """Beams the deck of `bay` spans onto: running across the span, midpoint inside or on
    the bay, as (coordinate along the span, beam), sorted."""
    out = []
    for bm in beams_at_level(b, bay["level"]):
        if abs(bm["i"][axis] - bm["j"][axis]) > _TOL:      # not across the span
            continue
        if point_in_polygon(midpoint(bm["i"], bm["j"]), bay["polygon"]):
            out.append((bm["i"][axis], bm))
    return sorted(out, key=lambda t: t[0])


def deck_strips(b: dict, bay: dict) -> tuple[dict[str, float], float] | None:
    """One-way tributary deck area per supporting beam of a bay, m2, and the deck area left
    without a support (no beam on a bay edge across the span). None if the span is unknown
    or the bay is not an axis-aligned rectangle."""
    axis = _span_axis(bay)
    box = _box(bay["polygon"])
    if axis is None or box is None:
        return None
    lo, hi = box[axis], box[axis + 2]
    a_lo, a_hi = box[1 - axis], box[3 - axis]
    sup = _supports(b, bay, axis)
    coords = sorted({round(c, 6) for c, _ in sup})
    strips: dict[str, float] = {}
    for c, bm in sup:
        k = coords.index(round(c, 6))
        width = ((coords[k + 1] - c) / 2 if k + 1 < len(coords) else 0.0) \
            + ((c - coords[k - 1]) / 2 if k > 0 else 0.0)
        s0, s1 = sorted((bm["i"][1 - axis], bm["j"][1 - axis]))
        overlap = max(0.0, min(s1, a_hi) - max(s0, a_lo))
        strips[bm["id"]] = strips.get(bm["id"], 0.0) + width * overlap
    covered = (coords[-1] - coords[0]) if coords else 0.0
    unsupported = ((hi - lo) - covered) * (a_hi - a_lo)
    return strips, unsupported


def build_increment(b: dict, region: dict, cfg: dict) -> dict:
    extra = cfg["loads"]["amplification_factor"] - 1.0
    factors = combination_factors(b)
    fsw = factors["self_weight"] if factors else cfg["loads"]["dead_factor"]   # beam self-weight
    fd = factors["sdl"] if factors else cfg["loads"]["dead_factor"]           # facade and point loads
    roof = roof_level(b)
    bays = {a["id"]: a for a in b["bays"]}
    beams = {bm["id"]: bm for bm in b["beams"]}
    facade = {}
    for ll in b.get("line_loads", []):
        facade[ll["beam_id"]] = facade.get(ll["beam_id"], 0.0) + ll["w_kn_per_m"]

    def q_of(a: dict) -> float:
        return bay_combo_kpa(a, a["level"] == roof, cfg, factors)

    flags: list[str] = []

    # Deck to beams when every region bay's span is known: each group beam takes its strip
    # from every bay it supports, in the region or not (a neighbour's strip on a shared edge).
    group = set(region["beams"])
    deck_kn: dict[str, float] = {}
    known = bool(region["bays"]) and all(deck_strips(b, bays[i]) is not None for i in region["bays"])
    method = "deck_to_beams" if known else "area"
    if known:
        for lvl in sorted({bays[i]["level"] for i in region["bays"]}):
            for a in bays_at_level(b, lvl):
                got = deck_strips(b, a)
                if got is None:
                    continue
                strips, unsupported = got
                if a["id"] in region["bays"] and unsupported > 1e-6:
                    flags.append(f"bay {a['id']}: {unsupported:.2f} m2 of deck has no supporting beam; not in the increment")
                for bmid, tributary in strips.items():
                    if bmid in group:
                        deck_kn[bmid] = deck_kn.get(bmid, 0.0) + q_of(a) * tributary
    elif region["bays"]:
        flags.append("deck span unknown for a region bay: increment by area, not to beams")

    area_loads, frame_loads, point_loads = [], [], []
    base_total = 0.0
    for bid in region["bays"]:
        a = bays[bid]
        q_base = q_of(a)
        ar = area(a["polygon"])
        area_loads.append({"bay_id": bid, "q_kpa": round(extra * q_base, 4), "area_m2": round(ar, 4)})
        if not known:
            base_total += q_base * ar

    for bmid in region["beams"]:
        bm = beams[bmid]
        L = dist(bm["i"], bm["j"])
        sw = b["sections"][bm["section"]]["mass_kg_per_m"] * G
        deck_w = deck_kn.get(bmid, 0.0) / L if L > 0 else 0.0
        w_base = fsw * sw + fd * facade.get(bmid, 0.0) + deck_w
        frame_loads.append({"beam_id": bmid, "w_kn_per_m": round(extra * w_base, 4),
                            "length_m": round(L, 4),
                            "components": {"self_weight": round(extra * fsw * sw, 4),
                                           "facade": round(extra * fd * facade.get(bmid, 0.0), 4),
                                           "deck": round(extra * deck_w, 4)}})
        base_total += w_base * L

    region_bay_set = set(region["bays"])
    for pl in b.get("point_loads", []):
        if pl.get("bay_id") in region_bay_set:
            p_base = fd * pl["p_kn"]
            point_loads.append({"point": pl["point"], "level": pl["level"], "p_kn": round(extra * p_base, 4)})
            base_total += p_base

    return {
        "pattern_name": None,  # set by scenario builder
        "extra_factor": extra,
        "method": method,
        "flags": flags,
        "area_loads": area_loads,
        "frame_loads": frame_loads,
        "point_loads": point_loads,
        "region_base_total_kn": round(base_total, 3),
        "region_amplified_total_kn": round(base_total * (1 + extra), 3),
        "increment_total_kn": round(base_total * extra, 3),
    }
