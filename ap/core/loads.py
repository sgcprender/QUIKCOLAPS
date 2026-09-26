"""Scenario increment loads.

Base loading on the whole building:     G   = 1.2 D + (0.5 L or 0.2 S)
Amplified region (UFC 3-2.11.4):        G_A = amp * G
So each scenario adds an increment of   (amp - 1) * G   on its region only.

D covers: slab superimposed dead + slab self-weight (area loads), beam
self-weight and facade line loads (frame loads), point loads. Wind is never
included. Live load is not reduced (config: live_load_reduction = false).

Beams on the boundary of the region are amplified in full (conservative; they
share load with non-region bays).

Factors: when the building carries `combination` (an ETABS export: the template's
initial case, D17), its factors are used for every bay, roof included, so the
increment is exactly what ETABS applies. Otherwise they come from config, with
the roof rule (0.5 Lr or 0.2 S) on the roof level.
"""
from __future__ import annotations

from .geometry import area, dist
from .model import roof_level

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

    area_loads, frame_loads, point_loads = [], [], []
    base_total = 0.0
    for bid in region["bays"]:
        a = bays[bid]
        q_base = bay_combo_kpa(a, a["level"] == roof, cfg, factors)
        ar = area(a["polygon"])
        area_loads.append({"bay_id": bid, "q_kpa": round(extra * q_base, 4), "area_m2": round(ar, 4)})
        base_total += q_base * ar

    for bmid in region["beams"]:
        bm = beams[bmid]
        L = dist(bm["i"], bm["j"])
        sw = b["sections"][bm["section"]]["mass_kg_per_m"] * G
        w_base = fsw * sw + fd * facade.get(bmid, 0.0)
        frame_loads.append({"beam_id": bmid, "w_kn_per_m": round(extra * w_base, 4),
                            "length_m": round(L, 4),
                            "components": {"self_weight": round(extra * fsw * sw, 4),
                                           "facade": round(extra * fd * facade.get(bmid, 0.0), 4)}})
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
        "area_loads": area_loads,
        "frame_loads": frame_loads,
        "point_loads": point_loads,
        "region_base_total_kn": round(base_total, 3),
        "region_amplified_total_kn": round(base_total * (1 + extra), 3),
        "increment_total_kn": round(base_total * extra, 3),
    }
