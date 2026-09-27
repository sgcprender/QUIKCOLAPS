"""What each app step runs (plan item F). Every ETABS command names the working copy (--model).

Outputs go to the project folder. A step stops at the first failed command (jobs.StepError).
Steps 2 and 6 end "awaiting approval"; the approve endpoints finish them.
"""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

from .jobs import REPO, Job, StepError
from .projects import Project
from . import tonnage

OUTPUTS = {
    0: ["check_model.json"],
    1: ["building.json", "intact_axial.json", "scenarios.json"],
    2: ["conditions.json", "review_conditions.json", "approved_candidates.json"],
    3: ["apply.json"],
    4: ["results_original.json"],
    5: ["rounds.json"],
    6: ["propagation.json", "finalize.json", "collapse_tonnage.json"],
    7: ["baseline_tonnage.json"],
}


def _analysis_cases(p: Project) -> list[str]:
    b = p.load("building.json")
    combo = b.get("combination", {})
    return list(combo.get("patterns", {})) + [combo.get("initial_case", "1.2D+0.5L")]


def _all_cases(p: Project) -> list[str]:
    return _analysis_cases(p) + [s["case_name"] for s in p.load("scenarios.json")["scenarios"]]


def ensure_open(job: Job, p: Project, model: Path, name: str) -> None:
    """Attach to the given working copy; open it if another model is open (closed unsaved)."""
    try:
        job.bridge("sections", "--model", name, ok=(0, 4))
    except StepError as e:
        if "no running instance has a model named like" not in str(e):
            raise
        job.say(f"opening {model.name} in ETABS (the model open now is closed without saving)")
        job.bridge("open", "--model", "", "--file", str(model))


def step0(job: Job, p: Project) -> str:
    ensure_open(job, p, p.ap_model, p.ap_name)
    job.bridge("check-model", "--model", p.ap_name, "--template", p.state.get("template", "CS1"),
               "--out", str(p.file("check_model.json")), ok=(0, 6))
    items = p.load("check_model.json")["items"]
    fails = [i for i in items if i["status"] == "fail"]
    if fails:
        raise StepError("model check failed: " + "; ".join(f"{i['name']}: {i['message']}" for i in fails))
    return f"{sum(i['status'] == 'pass' for i in items)} pass, {sum(i['status'] == 'warning' for i in items)} warning"


def step1(job: Job, p: Project) -> str:
    f = p.file
    job.bridge("export", "--model", p.ap_name, "--template", p.state.get("template", "CS1"), "--out", str(f("building.json")))
    cases = _analysis_cases(p)
    job.say(f"intact gravity run: {', '.join(cases)}")
    job.bridge("run", "--model", p.ap_name, "--cases", ",".join(cases), "--commit")
    job.bridge("axial", "--model", p.ap_name, "--case", cases[-1], "--out", str(f("intact_axial.json")))
    job.py("-m", "core.cli", str(f("building.json")), "--out", str(f("scenarios.json")))
    s = p.load("scenarios.json")
    return f"{len(s['candidates'])} locations, {len(s['scenarios'])} scenarios"


def step2(job: Job, p: Project) -> str:
    f = p.file
    job.py("-m", "core.conditions", str(f("building.json")), "--axial", str(f("intact_axial.json")), "--out", str(f("conditions.json")))
    job.py("-m", "claude_client.run_review", "--mode", "conditions", "--building", str(f("building.json")),
           "--scenarios", str(f("scenarios.json")), "--conditions", str(f("conditions.json")),
           "--axial", str(f("intact_axial.json")), "--out", str(f("review_conditions.json")))
    r = p.load("review_conditions.json")
    adds = [d["location_id"] for d in r["review"]["decisions"] if d["decision"] == "add"]
    return f"review ${r['meta']['cost_usd']:.2f}; suggested additions: {', '.join(adds) or 'none'}; approve the scenario set"


def approve_scenarios(job: Job, p: Project, accepted: list[str]) -> str:
    """Rule candidates (mandatory kept) plus the additions the user accepted → scenarios.json."""
    f = p.file
    rule = p.load("scenarios.json")["candidates"]
    rule = [c for c in rule if c.get("source", "rule") == "rule"]
    review = p.load("review_conditions.json")
    merged = {c["location_id"]: c for c in review["merged_candidates"]}
    cands = []
    for c in rule:
        c = dict(c)
        if not c.get("mandatory") and c["location_id"] not in accepted:
            c["status"] = "rejected"
        cands.append(c)
    for loc in accepted:
        if loc not in {c["location_id"] for c in rule} and loc in merged:
            c = dict(merged[loc])
            c["status"] = "accepted"
            cands.append(c)
    f("approved_candidates.json").write_text(json.dumps({"candidates": cands}, indent=1))
    # core.cli writes building.json next to --out as well: same folder, same content plus derived fields
    job.py("-m", "core.cli", str(f("building.json")), "--candidates", str(f("approved_candidates.json")),
           "--out", str(f("scenarios.json")))
    s = p.load("scenarios.json")
    return f"approved: {len([c for c in cands if c.get('status') != 'rejected'])} locations, {len(s['scenarios'])} scenarios"


def step3(job: Job, p: Project) -> str:
    args = ["apply", "--model", p.ap_name, "--scenarios", str(p.file("scenarios.json")), "--template", p.state.get("template", "CS1")]
    job.bridge(*args)
    out = job.bridge(*args, "--commit")
    m = re.search(r"(\d+) of (\d+) written and verified", out)
    comp = "composite strength selection: matches steel" in out
    res = {"written": int(m.group(1)) if m else 0, "total": int(m.group(2)) if m else 0,
           "composite_selection_matches": comp, "groups_cases_combos_per_scenario": 3}
    p.file("apply.json").write_text(json.dumps(res, indent=1))
    if not m or res["written"] != res["total"]:
        raise StepError(f"apply wrote {res['written']} of {res['total']} scenarios")
    return f"{res['written']} of {res['total']} scenarios written and verified (case, load group, combo each)"


def _run_design(job: Job, p: Project, out_name: str, rounds: int, tol: str | None = None) -> None:
    args = ["iterate", "--model", p.ap_name, "--cases", ",".join(_all_cases(p)), "--max-rounds", str(rounds),
            "--out", str(p.file(out_name)), "--commit", "--accept-design-sections"]
    if tol:
        args += ["--weight-tol", tol]
    job.bridge(*args, ok=(0, 5))
    job.bridge("results", "--model", p.ap_name, "--scenarios", str(p.file("scenarios.json")), "--out", str(p.file("results.json")))


def step4(job: Job, p: Project) -> str:
    _run_design(job, p, "run_first.json", 1)
    shutil.copy2(p.file("results.json"), p.file("results_original.json"))
    r = p.load("results.json")
    ok = sum(c["reaction_check_ok"] for c in r["cases"].values())
    return f"{ok}/{len(r['cases'])} scenarios pass the load check; first design done"


def step5(job: Job, p: Project) -> str:
    combos = p.state.get("strength_combos", ["DStlS1", "DStlS2"]) + [s["combo_name"] for s in p.load("scenarios.json")["scenarios"]]
    job.bridge("design-select", "--model", p.ap_name, "--combos", ",".join(combos), "--commit")
    _run_design(job, p, "rounds.json", 3, "0.005")
    rd = p.load("rounds.json")
    return f"{len(rd['rounds'])} round(s), {rd['rounds'][-1]['tons']} short tons, {'converged' if rd['converged'] else 'not converged'}"


def step6(job: Job, p: Project) -> str:
    f = p.file
    job.bridge("export", "--model", p.ap_name, "--out", str(f("building_current.json")))
    job.py("-m", "core.propagate", "--building", str(f("building_current.json")), "--original", str(f("building.json")),
           "--results", str(f("results.json")), "--scenarios", str(f("scenarios.json")),
           "--conditions", str(f("conditions.json")), "--out", str(f("propagation.json")))
    s = p.load("propagation.json")["summary"]
    return f"{s['frames_assigned']} frames to fix ({s['collapse_driven']} collapse-driven, {s['propagated_only']} propagated), {s['flagged_rows']} flagged; approve the list"


def finalize(job: Job, p: Project) -> str:
    f = p.file
    job.bridge("assign-sections", "--model", p.ap_name, "--file", str(f("propagation.json")))
    job.bridge("assign-sections", "--model", p.ap_name, "--file", str(f("propagation.json")), "--commit")
    label = f"{p.state['name']}_collapse_final".replace(" ", "_")
    job.py("scripts/finalize.py", "--model", p.ap_name, "--data", str(p.folder), "--label", label, ok=(0, 5))
    shutil.copy2(REPO / "takeoffs" / f"{label}.csv", f("collapse_takeoff.csv"))
    tonnage.update_premium(p.folder)
    fin = p.load("finalize.json")
    return f"finalize {fin['status']}: steel max {fin['steel_max']}, composite max {fin['composite_max']}"


def step7(job: Job, p: Project) -> str:
    f = p.file
    if not p.has("baseline_tonnage.json"):
        name = p.baseline_name
        job.say(f"baseline: opening {p.baseline_model.name} (the AP copy is closed without saving; its results stay on disk)")
        job.bridge("open", "--model", p.ap_name, "--file", str(p.baseline_model))
        try:
            job.bridge("design-select", "--model", name, "--combos", ",".join(p.state.get("strength_combos", ["DStlS1", "DStlS2"])), "--commit")
            job.bridge("iterate", "--model", name, "--cases", ",".join(_analysis_cases(p)[:-1]), "--max-rounds", "3",
                       "--out", str(f("baseline_rounds.json")), "--commit", "--accept-design-sections", ok=(0, 5))
            label = f"{p.state['name']}_baseline".replace(" ", "_")
            job.cli("weigh", "--model", name, "--label", label)
            shutil.copy2(REPO / "takeoffs" / f"{label}.csv", f("baseline_takeoff.csv"))
            tonnage.baseline_summary(p.folder, f("baseline_takeoff.csv"), f("baseline_rounds.json"), name)
        finally:
            job.say(f"reopening {p.ap_model.name}")
            job.bridge("open", "--model", name, "--file", str(p.ap_model))
    ct = tonnage.update_premium(p.folder)
    b = p.load("baseline_tonnage.json")["tonnage"]["total"]
    if ct:
        return f"baseline {b} short tons; premium {ct['premium']['short_tons']:+} ({ct['premium']['percent']:+}%)"
    return f"baseline {b} short tons; run step 6 for the premium"


RUN = {0: step0, 1: step1, 2: step2, 3: step3, 4: step4, 5: step5, 6: step6, 7: step7}
AWAITS = {2: "approve-scenarios", 6: "approve-propagation"}


def cached(p: Project, n: int) -> str:
    """Mark a step done from files already in the project folder."""
    need = OUTPUTS[n]
    missing = [x for x in need if not p.has(x)]
    if n in AWAITS and missing and all(x in ("approved_candidates.json", "finalize.json", "collapse_tonnage.json") for x in missing):
        return "awaiting"
    if missing:
        raise StepError(f"no cached results for this step: missing {', '.join(missing)}")
    return "done"
