"""Validate Claude's review before anything reaches the user or ETABS.

Rules:
- every location_id exists in the building
- mandatory candidates can't be rejected (the rejection is dropped and flagged)
- added locations get the deterministic story selection, never Claude's
- affected_region may only reference real bays/levels; otherwise it's discarded
Returns merged candidates plus a list of issues to show in the UI.
"""
from __future__ import annotations

from core.stories import select_stories


def validate_review(b: dict, candidates: list[dict], review: dict) -> tuple[list[dict], list[str]]:
    issues: list[str] = []
    locs = {}
    for c in b["columns"]:
        locs.setdefault(c["location_id"], (c["x"], c["y"]))
    bay_ids = {a["id"] for a in b["bays"]}
    level_names = {lv["name"] for lv in b["levels"]}
    by_loc = {c["location_id"]: dict(c) for c in candidates}

    for d in review.get("decisions", []):
        loc = d.get("location_id")
        if loc not in locs:
            issues.append(f"Claude referenced unknown location '{loc}'; ignored.")
            continue
        claude_note = {k: d.get(k) for k in ("reason", "clause", "confidence", "needs_engineer_review")}

        if d["decision"] == "add":
            if loc in by_loc:
                by_loc[loc].setdefault("claude", claude_note)
                continue
            x, y = locs[loc]
            by_loc[loc] = {"location_id": loc, "x": x, "y": y,
                           "reasons": [{"code": "judgment", "clause": d.get("clause", ""), "note": d.get("reason", "")}],
                           "stories": select_stories(b, loc), "source": "claude", "mandatory": False,
                           "status": "proposed"}
        elif d["decision"] == "reject":
            if loc not in by_loc:
                continue
            if by_loc[loc].get("mandatory"):
                issues.append(f"Claude tried to reject mandatory location {loc}; kept.")
            else:
                by_loc[loc]["status"] = "proposed_reject"
        elif d["decision"] == "accept" and loc in by_loc:
            by_loc[loc].setdefault("status", "proposed")

        if loc in by_loc:
            by_loc[loc]["claude"] = claude_note
            reg = d.get("affected_region")
            if reg:
                bad = [x for x in reg.get("bays", []) if x not in bay_ids] + \
                      [x for x in reg.get("levels", []) if x not in level_names]
                if bad or not reg.get("bays"):
                    issues.append(f"Affected region for {loc} referenced unknown ids {bad}; discarded.")
                else:
                    by_loc[loc]["region_proposal"] = {**reg, "source": "claude"}

    for c in by_loc.values():
        c.setdefault("status", "proposed")
        if c.get("claude", {}).get("confidence") == "low":
            c["needs_review"] = True
    return sorted(by_loc.values(), key=lambda c: c["location_id"]), issues


def check_evidence(conditions: dict, axial: dict | None, review: dict,
                   rel_tol: float = 0.01) -> tuple[list[dict], list[str]]:
    """Check every value Claude cites against the condition table (and the intact
    axial forces, which also cover interior columns).

    Returns (checked evidence, issues). Each checked item gets status "ok",
    "mismatch" or "unchecked" (a field the table doesn't have as a plain value).
    Numbers match within rel_tol (or 0.05 absolute); strings and booleans exactly.
    """
    rows = {(r["location_id"], r["story"]): r for r in conditions["rows"]}
    p_axial = {}
    if axial:
        for v in axial["columns"].values():
            p_axial[(v["location_id"], v["story"])] = v["p_kn"]
    out, issues = [], []
    for d in review.get("decisions", []):
        for e in d.get("evidence", []):
            key = (e.get("location_id"), e.get("story"))
            field, cited = e.get("field"), e.get("value")
            truth = None
            row = rows.get(key)
            if row is not None and field in row and not isinstance(row[field], (list, dict)):
                truth = row[field]
            elif field == "p_kn" and key in p_axial:
                truth = p_axial[key]
            if truth is None:
                status = "unchecked"
            elif isinstance(truth, bool) or isinstance(cited, bool) or isinstance(truth, str):
                status = "ok" if truth == cited else "mismatch"
            else:
                try:
                    c = float(cited)
                    status = "ok" if abs(c - truth) <= max(0.05, rel_tol * abs(truth)) else "mismatch"
                except (TypeError, ValueError):
                    status = "mismatch"
            out.append({"decision_location": d.get("location_id"), **e, "table_value": truth, "status": status})
            if status == "mismatch":
                issues.append(f"{d.get('location_id')}: cited {field}={cited} at {key[0]} {key[1]}, "
                              f"table has {truth}.")
    return out, issues
