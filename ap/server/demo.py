"""Register the AP2 work (2026-09-26/27) as the app's first project.

    python -m server.demo

Copies (never moves) the files from ap/web/data and takeoffs/ into
"<ETABS folder>/progressive collapse - quikcolaps", recovers the first design pass (original
sections) from git as results_original.json, writes project.json with every step done, and adds
the project to the index. The working copies are the ones used: "progressive collapse - AP2.EDB"
and "baseline strength.EDB"; the source is QUIKCOLAPS.EDB (same sections and frame ids as AP2's
first export, checked 2026-09-26).
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from . import projects

AP = Path(__file__).resolve().parents[1]
REPO = AP.parent
DATA = AP / "web" / "data"
ETABS = REPO.parent / "ETABS"

COPY = {  # project file: source
    "building.json": DATA / "building.json",
    "intact_axial.json": DATA / "intact_axial.json",
    "scenarios.json": DATA / "scenarios.json",
    "approved_candidates.json": DATA / "approved_candidates.json",
    "conditions.json": DATA / "conditions.json",
    "review_conditions.json": DATA / "review_conditions.json",
    "review_raw.json": DATA / "review_raw.json",
    "results.json": DATA / "results.json",
    "rounds.json": DATA / "ap2_rounds.json",
    "building_current.json": DATA / "building_current.json",
    "building_final.json": DATA / "building_final.json",
    "propagation.json": DATA / "propagation.json",
    "finalize.json": DATA / "finalize.json",
    "collapse_tonnage.json": DATA / "collapse_tonnage.json",
    "baseline_tonnage.json": DATA / "baseline_tonnage.json",
    "baseline_rounds.json": DATA / "baseline_rounds.json",
    "scenario_ratios.json": DATA / "scenario_ratios.json",
    "collapse_takeoff.csv": REPO / "takeoffs" / "collapse_final.csv",
    "baseline_takeoff.csv": REPO / "takeoffs" / "baseline_strength.csv",
}

MESSAGES = {
    0: "5 checks: 2 pass, 3 warning (ETABS 23.3.0; 10 deck areas off the grid at C29; fixed sections)",
    1: "3 rule locations, 23 scenarios; intact axial read from 1.2D+0.5L",
    2: "review $0.47; C5 added by the user: 4 locations, 30 scenarios",
    3: "30 of 30 scenarios written and verified (case, load group, combo each)",
    4: "30/30 scenarios pass the load check; first design done",
    5: "3 round(s), 913.57 short tons, converged",
    6: "finalize passed: steel max 0.992, composite max 0.587",
    7: "baseline 790.18 short tons; premium +367.83 (+46.5%)",
}


def main() -> None:
    folder = ETABS / "progressive collapse - quikcolaps"
    folder.mkdir(exist_ok=True)
    for name, src in COPY.items():
        if src.exists():
            shutil.copy2(src, folder / name)
        else:
            print(f"  missing {src.name}; skipped")
    orig = subprocess.run(["git", "show", "ff6512d:ap/web/data/results.json"], cwd=REPO, capture_output=True, text=True, check=True)
    (folder / "results_original.json").write_text(orig.stdout)
    chk = folder / "check_model.json"
    if not chk.exists():
        chk.write_text(json.dumps({"model": "progressive collapse - AP2", "items": [
            {"name": "ETABS version", "status": "pass", "message": "ETABS 23.3.0 (the bridge was checked against ETABS 23, API 2.16)"},
            {"name": "Deck floors", "status": "warning", "message": "220 deck floor areas; 10 have a corner off the column grid (e.g. 50, 95, 140, 185, 230): not one area per bay"},
            {"name": "Template case", "status": "pass", "message": "CS1: initial '1.2D+0.5L' = 1.2×SW + 0.5×LL + 1.2×SDL; removes frame 1; loads group 'INFLUENCE AREA_CS1'"},
            {"name": "Load patterns", "status": "pass", "message": "dead SW, SDL; live LL; not used (no wind or quake in AP): W, E, ~LLRF and the wind/quake sub-patterns"},
            {"name": "Auto-select lists", "status": "warning", "message": "columns 0/320, steel girders 182/520 on an auto-select list (after the final assignment; all were on lists at the start)"},
        ]}, indent=1))
    (folder / "apply.json").write_text(json.dumps({"written": 30, "total": 30, "composite_selection_matches": True,
                                                    "groups_cases_combos_per_scenario": 3}, indent=1))
    state = {
        "id": projects.pid_for(folder), "name": "progressive collapse", "demo": True,
        "source_model": str(ETABS / "QUIKCOLAPS.EDB"),
        "ap_model": str(ETABS / "progressive collapse - AP2.EDB"),
        "baseline_model": str(ETABS / "baseline strength.EDB"),
        "created": "2026-09-26T09:00:00", "strength_combos": ["DStlS1", "DStlS2"], "template": "CS1",
        "steps": {str(n): {"status": "done", "message": m, "at": "2026-09-27T00:00:00"} for n, m in MESSAGES.items()},
        "last_completed": 7,
        "notes": ["SC07 reaction check -1.70% against the final export (open)"],
    }
    (folder / "project.json").write_text(json.dumps(state, indent=1))
    p = projects.Project(folder)
    p.save()
    projects.register(p)
    print(f"registered {p.state['name']} ({p.id}) at {folder}")


if __name__ == "__main__":
    main()
