"""Turn approved candidates into analysis scenarios.

One scenario = one plan location x one story. Each carries: the removed column
segments (including simultaneous removals), the amplified region, and the
increment load spec. The C# bridge (`apply`) writes the case, load group and combo;
the increment itself comes from the template case CS1 loading the group (D13).
"""
from __future__ import annotations

from .candidates import difficult_geometry_flags
from .loads import build_increment
from .model import column, levels_at_or_above
from .regions import (amplified_region, region_from_bays, simultaneous_radius,
                      simultaneous_removals)


def region_from_stacks(b: dict, removed: list[dict], stacks: dict) -> dict | None:
    """Region from ETABS topology (quikcolaps-bridge stacks): the union of the influence
    areas of every removed column. None if any removed column has no stack."""
    if not all(c["id"] in stacks for c in removed):
        return None
    bays = []
    for c in removed:
        bays += [x for x in stacks[c["id"]]["influence_areas"] if x not in bays]
    reg = region_from_bays(b, bays, source="etabs")
    return reg


def build_scenarios(b: dict, candidates: list[dict], cfg: dict, stacks: dict | None = None) -> list[dict]:
    """stacks: optional ETABS stack traces; when present they define the region (decision D12)
    and the rule-based region becomes a cross-check."""
    frac = cfg["removal"]["simultaneous_fraction"]
    out = []
    n = 0
    for cand in candidates:
        if cand.get("status", "accepted") == "rejected":
            continue
        flags = difficult_geometry_flags(b, cand["location_id"])
        for pick in cand["stories"]:
            col = column(b, cand["location_id"], pick["story"])
            if col is None:
                continue
            n += 1
            extra = simultaneous_removals(b, col, frac)
            removed = [col] + extra
            override = cand.get("region_override")  # set only after the user approves it
            if override:
                # an approved region is per location; keep only levels above this removal
                above = set(levels_at_or_above(b, min(c["top_z"] for c in removed)))
                lvl_of = {a["id"]: a["level"] for a in b["bays"]}
                region = region_from_bays(b, [x for x in override["bays"] if lvl_of.get(x) in above])
            else:
                region = amplified_region(b, removed)
                from_etabs = region_from_stacks(b, removed, stacks) if stacks else None
                if from_etabs is not None:
                    if set(from_etabs["bays"]) != set(region["bays"]):
                        flags = flags + ["etabs_region_differs_from_rule"]
                        from_etabs["rule_bays"] = region["bays"]
                    for c in removed:
                        stop = stacks[c["id"]].get("stop", "")
                        if "not directly above" in stop:
                            flags = flags + [f"stack_stops: {stop}"]
                    region = from_etabs
            inc = build_increment(b, region, cfg)
            sid = f"SC{n:02d}"
            inc["pattern_name"] = f"AP_INC_{sid}"
            out.append({
                "id": sid,
                "location_id": cand["location_id"],
                "story": pick["story"],
                "story_reasons": pick["reasons"],
                "location_reasons": cand["reasons"],
                "removed_columns": [c["id"] for c in removed],
                "simultaneous_columns": [c["id"] for c in extra],
                "simultaneous_radius_m": round(simultaneous_radius(b, col, frac), 3),
                # names follow the existing Quikcolaps tool: <case>_CMB for the combo
                "case_name": f"AP_{sid}",
                "group_name": f"AP_{sid}_LOAD",
                "combo_name": f"AP_{sid}_CMB",
                "region": region,
                "increment": inc,
                "flags": flags,
            })
    return out
