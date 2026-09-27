"""Step 3 Claude call: review rule candidates, add judgment-based ones, and
propose affected regions for flagged geometry.

One call per building. Structured output: the reply is JSON matching
`TOOL["input_schema"]` (`output_config.format`; the configured model rejects a
forced tool call). Claude never computes loads; code validates everything it
returns (see validate.py) before the user sees it.

Two payloads (`mode`):
- "raw": raw geometry only (levels, column lines and sections, beams, floor
  areas). No candidates, no forces: Claude proposes the removal set itself.
- "conditions": raw geometry + the rule candidates + the condition table
  (core/conditions.py: tributary areas, intact axial forces, neighbours, framing,
  symmetry groups). Claude reviews the candidates and adds what the judgment
  conditions call for, citing the values it used.

Usage:
    from claude_client.review import review_candidates
    result = review_candidates(building, candidates, cfg, mode="conditions", conditions=table)
    # needs ANTHROPIC_API_KEY (environment or ap/.env)
"""
from __future__ import annotations

import copy
import json
import time
from pathlib import Path

from core.candidates import difficult_geometry_flags

ROOT = Path(__file__).resolve().parents[1]

TOOL = {
    "name": "submit_removal_review",
    "description": "Submit the reviewed list of column removal candidates for Alternate Path analysis.",
    "input_schema": {
        "type": "object",
        "properties": {
            "decisions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "location_id": {"type": "string"},
                        "decision": {"type": "string", "enum": ["accept", "reject", "add"]},
                        "reason": {"type": "string", "description": "Plain-language engineering reason"},
                        "clause": {"type": "string", "description": "UFC 4-023-03 clause, e.g. 3-2.9.2.2"},
                        "condition": {"type": "string",
                                      "enum": ["corner", "mid_long_side", "mid_short_side", "re_entrant_corner",
                                               "bay_size_change", "lightly_loaded_adjacent",
                                               "different_tributary_sizes", "framing_orientation_or_elevation",
                                               "other"],
                                      "description": "The 3-2.9.2.2 condition this decision rests on"},
                        "stories_of_concern": {"type": "array", "items": {"type": "string"},
                                               "description": "Stories where the condition is most pronounced (for "
                                                              "the engineer; story selection itself is by rule)"},
                        "evidence": {
                            "type": "array",
                            "description": "Every number the decision relies on, as read from the data provided",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "location_id": {"type": "string"},
                                    "story": {"type": "string"},
                                    "field": {"type": "string",
                                              "description": "Condition-table field name, e.g. p_kn, tributary_m2"},
                                    "value": {"anyOf": [{"type": "number"}, {"type": "string"},
                                                        {"type": "boolean"}]},
                                },
                                "required": ["location_id", "story", "field", "value"],
                                "additionalProperties": False,
                            },
                        },
                        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                        "needs_engineer_review": {"type": "boolean"},
                        "affected_region": {
                            "type": "object",
                            "description": "Only for flagged geometry: bays that receive amplified load",
                            "properties": {
                                "levels": {"type": "array", "items": {"type": "string"}},
                                "bays": {"type": "array", "items": {"type": "string"}},
                                "reasoning": {"type": "string"},
                            },
                            "required": ["levels", "bays", "reasoning"],
                            "additionalProperties": False,
                        },
                    },
                    "required": ["location_id", "decision", "reason", "clause", "condition",
                                 "evidence", "confidence", "needs_engineer_review"],
                    "additionalProperties": False,
                },
            },
            "not_added": {
                "type": "array",
                "description": "Locations or symmetry groups considered for the judgment conditions and not "
                               "added, with the values that decided it",
                "items": {
                    "type": "object",
                    "properties": {
                        "location_ids": {"type": "array", "items": {"type": "string"}},
                        "reason": {"type": "string"},
                    },
                    "required": ["location_ids", "reason"],
                    "additionalProperties": False,
                },
            },
            "model_observations": {
                "type": "array", "items": {"type": "string"},
                "description": "Anything in the data that looks like a modelling error or needs the engineer",
            },
            "summary": {"type": "string"},
        },
        "required": ["decisions", "not_added", "model_observations", "summary"],
        "additionalProperties": False,
    },
}

MODES = ("raw", "conditions")


def system_prompt() -> str:
    notes = (ROOT / "docs" / "ufc_notes.md").read_text(encoding="utf-8")
    return (
        "You are assisting a structural engineer with progressive collapse Alternate Path "
        "analysis of a steel frame under UFC 4-023-03 (2009, Change 4). You decide which "
        "external columns to remove.\n\n"
        "Rules you must follow:\n"
        "- Never reject a candidate marked mandatory=true.\n"
        "- Only use locations that exist in the building's column list. External (perimeter) "
        "columns only; internal removals are out of scope.\n"
        "- Beyond the minimum set, add locations only for the conditions in 3-2.9.2.2: plan "
        "geometry changes (abrupt bay-size decrease, re-entrant corners), lightly loaded adjacent "
        "columns, bays with different tributary sizes, members framing in at different "
        "orientations or elevations. Say which condition you see and where.\n"
        "- Check re-entrant corners at every level, not only the first floor: the rule candidates "
        "look at the first-floor outline only, so a re-entrant corner created by a setback or "
        "notch higher up is yours to add (condition re_entrant_corner). Use the condition "
        "table's re_entrant_corners list and each row's corner_type / on_outline where a table "
        "is given; otherwise the floor outlines per level in the geometry (outlines_by_level).\n"
        "- Cite the values you used in `evidence`: location, story, field and value exactly as "
        "given in the data (condition-table field names where a table is given). Code checks "
        "every cited value against the data.\n"
        "- Where locations are equivalent by symmetry, one of them represents the group; say so.\n"
        "- For candidates with geometry flags, propose the affected_region using only bay ids "
        "and level names from the data provided. Otherwise omit affected_region.\n"
        "- Do not compute loads or member capacities, and do not choose stories: code selects "
        "the stories for every location (first above grade, below roof, mid-height, above "
        "each splice).\n"
        "- Cite a clause for every decision. Mark anything uncertain as low confidence and "
        "needs_engineer_review=true.\n"
        "- Report anything that looks like a modelling error in model_observations.\n\n"
        "Reply with JSON matching the given schema only.\n\n"
        "Reference notes (the team's summary of the relevant clauses):\n\n" + notes
    )


def building_summary(b: dict) -> dict:
    """Compact view of the building: enough for judgment, small enough to fit."""
    return {
        "grids": b["grids"],
        "levels": b["levels"],
        "stories": [{k: s[k] for k in ("name", "bottom_z", "top_z")} for s in b["stories"]],
        "outlines": b["outlines"],
        "column_locations": sorted({(c["location_id"], c["x"], c["y"]) for c in b["columns"]}),
        "column_sections_by_story": sorted({(c["location_id"], c["story"], c["section"]) for c in b["columns"]}),
        "zones": b.get("zones", []),
    }


def _r(v, nd: int = 3):
    return round(v, nd) + 0.0


def raw_geometry(b: dict) -> dict:
    """The building as drawn: levels, column lines with their sections bottom to top,
    and the framing and floor areas per level. Levels with the same framing, sections
    and floor areas share one entry. No derived quantities."""
    stories = sorted(b["stories"], key=lambda s: s["bottom_z"])
    cols = {}
    for c in sorted(b["columns"], key=lambda c: c["bottom_z"]):
        e = cols.setdefault(c["location_id"], {"x": _r(c["x"]), "y": _r(c["y"]), "sections": {}})
        e["sections"][c["story"]] = c["section"]
    layouts: list[dict] = []
    for lv in sorted(b["levels"], key=lambda l: l["z"]):
        beams = sorted([_r(bm["i"][0]), _r(bm["i"][1]), _r(bm["j"][0]), _r(bm["j"][1]), bm["section"],
                        _r(bm["z"] - lv["z"])] for bm in b["beams"] if bm["level"] == lv["name"])
        bays = sorted([a["id"], [[_r(x), _r(y)] for x, y in a["polygon"]], a.get("loads", {})]
                      for a in b["bays"] if a["level"] == lv["name"])
        if not beams and not bays:
            continue
        key = (json.dumps(beams), json.dumps([[p, l] for _, p, l in bays]))
        for L in layouts:
            if L["_key"] == key:
                L["levels"].append(lv["name"])
                L["bay_ids"][lv["name"]] = [i for i, _, _ in bays]
                break
        else:
            layouts.append({"_key": key, "levels": [lv["name"]], "beams": beams,
                            "bays": [[p, l] for _, p, l in bays], "bay_ids": {lv["name"]: [i for i, _, _ in bays]}})
    for L in layouts:
        del L["_key"]
    return {
        "units": {"length": "m", "force": "kN", "pressure": "kPa"},
        "levels": b["levels"],
        "stories": [{k: s[k] for k in ("name", "bottom_level", "top_level", "bottom_z", "top_z")} for s in stories],
        "outline_first_floor": b["outlines"].get(stories[0]["top_level"]) if stories else None,
        "outlines_by_level": _outlines_by_level(b),
        "columns": cols,
        "framing": {
            "beam_format": "[xi, yi, xj, yj, section, z offset from level]",
            "bay_format": "[polygon, loads kPa]; bay ids per level in bay_ids, same order",
            "layouts": layouts,
        },
    }


def _outlines_by_level(b: dict) -> list[dict]:
    """Floor outline per level, levels with the same outline grouped (setbacks show as a change)."""
    groups: list[dict] = []
    for lv in sorted(b["levels"], key=lambda l: l["z"]):
        o = b.get("outlines", {}).get(lv["name"])
        if not o:
            continue
        pts = [[_r(x), _r(y)] for x, y in o]
        if groups and groups[-1]["outline"] == pts:
            groups[-1]["levels"].append(lv["name"])
        else:
            groups.append({"levels": [lv["name"]], "outline": pts})
    return groups


def compact_conditions(t: dict) -> dict:
    """The condition table as a header + rows, to keep the prompt small."""
    head = ["location_id", "story", "frame", "sides", "position", "corner_type", "on_outline",
            "perimeter_first_floor", "section", "section_below", "section_above",
            "splice_below", "continuous_to_roof", "tributary_m2", "tributary_above_m2", "p_kn",
            "p_per_tributary_above_kpa", "adjacent_bays", "neighbours", "beams_at_top", "symmetry_group",
            "symmetry_group_with_sections"]
    rows = []
    for r in t["rows"]:
        row = []
        for h in head:
            v = r[h]
            if h == "adjacent_bays":
                v = [[a["id"], a["dx_m"], a["dy_m"], a["area_m2"]] for a in v]
            elif h == "neighbours":
                v = [[n["location_id"], n["direction_deg"], n["distance_m"], n["p_kn"], n["p_ratio_to_this"],
                      n["tributary_m2"], n["framed"], n["perimeter"]] for n in v]
            elif h == "beams_at_top":
                v = [[m["id"], m["section"], m["direction_deg"], m["length_m"], m["z_offset_m"], m["kind"]] for m in v]
            row.append(v)
        rows.append(row)
    return {
        "axial_case": t["axial_case"],
        "definitions": t["definitions"],
        "formats": {
            "adjacent_bays": "[bay id, dx_m, dy_m, area_m2]",
            "neighbours": "[location_id, direction_deg, distance_m, p_kn, p_ratio_to_this, tributary_m2, framed, "
                          "perimeter]",
            "beams_at_top": "[beam id, section, direction_deg, length_m, z_offset_m, kind]",
        },
        "symmetry": t["symmetry"],
        "re_entrant_corners": t.get("re_entrant_corners", []),
        "columns": head,
        "rows": rows,
    }


def local_neighbourhood(b: dict, location_id: str, radius_m: float = 12.0) -> dict:
    col = next(c for c in b["columns"] if c["location_id"] == location_id)
    p = (col["x"], col["y"])

    def near(q):
        return abs(q[0] - p[0]) <= radius_m and abs(q[1] - p[1]) <= radius_m

    return {
        "bays": [{"id": a["id"], "level": a["level"], "polygon": a["polygon"]}
                 for a in b["bays"] if any(near(v) for v in a["polygon"])],
        "beams": [{"id": bm["id"], "level": bm["level"], "i": bm["i"], "j": bm["j"]}
                  for bm in b["beams"] if near(bm["i"]) or near(bm["j"])],
        "columns": [{"id": c["id"], "x": c["x"], "y": c["y"], "story": c["story"],
                     "lands_on_beam": c.get("lands_on_beam", False)}
                    for c in b["columns"] if near((c["x"], c["y"]))],
    }


def build_user_message(b: dict, candidates: list[dict], mode: str = "conditions",
                       conditions: dict | None = None) -> str:
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}")
    if mode == "raw":
        payload = {"building": raw_geometry(b)}
        return ("No candidates are given. From the geometry below, decide which external columns "
                "to remove: the minimum set (a corner, near the middle of the long side, near the "
                "middle of the short side) and any others 3-2.9.2.2 calls for. Use decision=\"add\" "
                "for every location you choose. Reply with the JSON.\n\n" + json.dumps(payload))
    flagged = {}
    for c in candidates:
        f = difficult_geometry_flags(b, c["location_id"])
        if f:
            flagged[c["location_id"]] = {"flags": f, "neighbourhood": local_neighbourhood(b, c["location_id"])}
    payload = {
        "building": raw_geometry(b),
        "candidates": [{k: c[k] for k in ("location_id", "x", "y", "reasons", "stories", "mandatory")}
                       for c in candidates],
        "flagged_geometry": flagged,
    }
    if conditions is not None:
        payload["condition_table"] = compact_conditions(conditions)
    return ("Review these rule candidates (accept or reject each), then check every perimeter "
            "column against the judgment conditions of 3-2.9.2.2 using the condition table, and add "
            "the locations they call for. Reply with the JSON.\n\n" + json.dumps(payload))


def output_schema() -> dict:
    return copy.deepcopy(TOOL["input_schema"])


def cost_usd(usage: dict, cfg: dict) -> float:
    c = cfg["claude"]
    return (usage.get("input_tokens", 0) * c["price_input_per_mtok"]
            + usage.get("output_tokens", 0) * c["price_output_per_mtok"]
            + usage.get("cache_read_input_tokens", 0) * c["price_cache_read_per_mtok"]
            + usage.get("cache_creation_input_tokens", 0) * c["price_cache_write_per_mtok"]) / 1e6


def load_env() -> None:
    """ANTHROPIC_API_KEY from ap/.env when it is not already in the environment."""
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env", override=False)


def review_candidates(b: dict, candidates: list[dict], cfg: dict, client=None, mode: str = "conditions",
                      conditions: dict | None = None, with_meta: bool = False):
    """Call Claude and return the parsed review (validate it with validate.validate_review).

    with_meta=True returns (review, meta) with the model, usage, cost and duration.
    """
    if client is None:
        import anthropic  # imported lazily so tests don't need the SDK
        load_env()
        client = anthropic.Anthropic()
    c = cfg["claude"]
    t0 = time.time()
    with client.messages.stream(
        model=c["model"],
        max_tokens=c["max_tokens"],
        system=system_prompt(),
        thinking={"type": "adaptive"},
        output_config={"effort": c.get("effort", "high"),
                       "format": {"type": "json_schema", "schema": output_schema()}},
        messages=[{"role": "user", "content": build_user_message(b, candidates, mode, conditions)}],
    ) as stream:
        resp = stream.get_final_message()
    if resp.stop_reason in ("max_tokens", "refusal"):
        raise RuntimeError(f"Claude stopped with {resp.stop_reason}; no usable review")
    text = next((blk.text for blk in resp.content if getattr(blk, "type", None) == "text"), None)
    if text is None:
        raise RuntimeError("Claude returned no text block")
    review = json.loads(text)
    if not with_meta:
        return review
    u = resp.usage
    usage = {k: getattr(u, k, 0) or 0 for k in ("input_tokens", "output_tokens", "cache_read_input_tokens",
                                                 "cache_creation_input_tokens")}
    return review, {"model": resp.model, "mode": mode, "stop_reason": resp.stop_reason, "usage": usage,
                    "cost_usd": round(cost_usd(usage, cfg), 4), "seconds": round(time.time() - t0, 1)}
