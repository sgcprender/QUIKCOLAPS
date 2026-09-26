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
