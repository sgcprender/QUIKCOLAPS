"""Finalize the collapse design on the open ETABS model (plan item D / app button 6).

    python scripts/finalize.py --model "progressive collapse - AP2" [--max-rounds 5]
        [--data <project data folder>] [--label collapse_final]

Loop logic: core/finalize.py. This file gives it the ETABS operations through the C# bridge
and stops at the first command that fails (every write is checked before the next step):

  check          bridge autoselect --cleanup --commit (deletes FIN_* lists no frame uses; the
                 run unlocks anyway), then bridge iterate --max-rounds 1 --commit --accept-design-sections (run all AP
                 cases + the initial case and its patterns, design once), then bridge results
  autoselect     bridge autoselect --frames ... --commit
  current        bridge export → web/data/building_final.json
  assign         web/data/propagation.json, bridge assign-sections (dry run must be clean), --commit

Writes <data>/finalize.json (status passed / not converged / error, every round's moves; earlier
runs kept under "history"), then weighs (quikcolaps weigh --label <label>, takeoffs/<label>.csv)
and updates <data>/collapse_tonnage.json (premium only when <data>/baseline_tonnage.json exists).
<data> defaults to ap/web/data.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

AP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AP))

from core.finalize import finalize  # noqa: E402
from core.model import load_building  # noqa: E402

REPO = AP.parent
DATA = AP / "web" / "data"      # set by --data
LABEL = "collapse_final"        # set by --label
BRIDGE = REPO / "tools" / "Quikcolaps.Bridge"
CLI = REPO / "tools" / "Quikcolaps.Cli"


class BridgeError(RuntimeError):
    pass


def call(project: Path, args: list[str], ok=(0,), show=r"^(round|iterate|lock|error|problem|READ BACK|\d+ of \d+|wrote|total)") -> str:
    cmd = ["dotnet", "run", "--no-build", "--project", str(project), "--", *args]
    p = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True, encoding="utf-8", errors="replace")
    out = p.stdout + p.stderr
    for line in out.splitlines():
        if re.match(show, line):
            print(f"    {line[:200]}")
    if p.returncode not in ok:
        raise BridgeError(f"{' '.join(args[:1])} exited {p.returncode}: {out.strip().splitlines()[-1] if out.strip() else ''}")
    return out


class BridgeOps:
    def __init__(self, model: str):
        self.model = model
        b = json.loads((DATA / "building.json").read_text())
        s = json.loads((DATA / "scenarios.json").read_text())
        combo = b.get("combination", {})
        self.cases = list(combo.get("patterns", {})) + [combo.get("initial_case", "1.2D+0.5L")] + \
            [x["case_name"] for x in s["scenarios"]]
        self._building = load_building(DATA / "building.json")

    def check(self) -> dict:
        print("  check: run all AP cases, design once")
        call(BRIDGE, ["autoselect", "--cleanup", "--model", self.model, "--commit"], show=r"^(cleanup|lock|error|READ BACK|\d+ of \d+)")
        call(BRIDGE, ["iterate", "--model", self.model, "--cases", ",".join(self.cases), "--max-rounds", "1",
                      "--out", str(DATA / "finalize_run.json"), "--commit", "--accept-design-sections"], ok=(0, 5))
        call(BRIDGE, ["results", "--model", self.model, "--scenarios", str(DATA / "scenarios.json"),
                      "--out", str(DATA / "results.json")])
        return json.loads((DATA / "results.json").read_text())

    def autoselect(self, frames: list[str]) -> None:
        print(f"  autoselect {', '.join(frames)}")
        call(BRIDGE, ["autoselect", "--model", self.model, "--frames", ",".join(frames), "--commit"])

    def current_sections(self) -> dict[str, str]:
        call(BRIDGE, ["export", "--model", self.model, "--out", str(DATA / "building_final.json")])
        b = json.loads((DATA / "building_final.json").read_text())
        return {c["id"]: c["section"] for c in b["columns"]} | {m["id"]: m["section"] for m in b["beams"]}

    def assign(self, propagation: dict) -> None:
        (DATA / "propagation.json").write_text(json.dumps(propagation, indent=1))
        print("  assign-sections (dry run, then --commit)")
        call(BRIDGE, ["assign-sections", "--model", self.model, "--file", str(DATA / "propagation.json")])
        call(BRIDGE, ["assign-sections", "--model", self.model, "--file", str(DATA / "propagation.json"), "--commit"])

    def building(self) -> dict:
        return self._building


def update_tonnage(model: str, log: dict) -> dict:
    """Weigh the model and rewrite collapse_tonnage.json: totals, premium over the baseline, split,
    check, reactions against the fresh export."""
    call(CLI, ["weigh", "--model", model, "--label", LABEL])
    w = lambda s: float(re.search(r"X([\d.]+)", s).group(1))
    b = json.loads((DATA / "building.json").read_text())
    orig = {x["id"]: x["section"] for x in b["columns"]} | {m["id"]: m["section"] for m in b["beams"]}
    prop = json.loads((DATA / "propagation.json").read_text())
    own = {x["member"] for x in prop["rows"] if x["symmetry"] == "identity"}
    asg = {a["frame"] for a in prop["assignments"]}
    rows = list(csv.DictReader(open(REPO / "takeoffs" / f"{LABEL}.csv", encoding="utf-8")))
    d = lambda x: (float(x["Lb"]) - w(orig[x["Frame"]]) * float(x["LengthFt"])) / 2000
    total = sum(float(x["Lb"]) for x in rows) / 2000
    cols = sum(float(x["Lb"]) for x in rows if x["Kind"] == "Column") / 2000
    comp = sum(float(x["Lb"]) for x in rows if x["SectionSource"].startswith("composite")) / 2000
    original = sum(w(orig[x["Frame"]]) * float(x["LengthFt"]) for x in rows) / 2000
    bpath = DATA / "baseline_tonnage.json"
    base = json.loads(bpath.read_text())["tonnage"] if bpath.exists() else None
    base_strength = base["total"] - base["original_sections_total"] if base else 0.0
    cd = sum(d(x) for x in rows if x["Frame"] in own)
    pr = sum(d(x) for x in rows if x["Frame"] in asg - own)
    st = sum(d(x) for x in rows if x["Frame"] not in asg)

    # reactions against the fresh export's increments (same regions)
    # core.cli also writes building.json next to --out: keep it out of web/data
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run([sys.executable, "-m", "core.cli", str(DATA / "building_final.json"), "--candidates",
                        str(DATA / "approved_candidates.json"), "--out", str(Path(tmp) / "scenarios.json")],
                       cwd=AP, check=True, capture_output=True)
        fresh = json.loads((Path(tmp) / "scenarios.json").read_text())
    exp = {s["id"]: s["increment"]["increment_total_kn"] for s in fresh["scenarios"]}
    res = json.loads((DATA / "results.json").read_text())
    reac = []
    for x in res["cases"].values():
        e, r = exp[x["scenario"]], x["increment_from_reactions_kn"]
        reac.append({"scenario": x["scenario"], "status": x["status"], "expected_kn": round(e, 1),
                     "from_reactions_kn": round(r, 1), "diff_percent": round((r - e) / e * 100, 2),
                     "ok": abs(r - e) / e <= 0.01})
    ct = json.loads((DATA / "collapse_tonnage.json").read_text()) if (DATA / "collapse_tonnage.json").exists() else {}
    ct.update({
        "state": f"finalize: {log['status']} after {len(log['rounds'])} round(s); fixed sections from propagation.json",
        "tonnage": {"total": round(total, 2), "columns": round(cols, 2), "steel_beams": round(total - cols - comp, 2),
                    "composite_beams": round(comp, 2)},
        "baseline_total": base["total"] if base else None,
        "premium": {"short_tons": round(total - base["total"], 2), "percent": round(100 * (total - base["total"]) / base["total"], 1)} if base else None,
        "split_over_original_sections": {"original": round(original, 2), "collapse_driven": round(cd, 2),
                                         "propagated": round(pr, 2), "strength_and_other": round(st, 2)},
        "split_of_premium_over_baseline": {"collapse_driven": round(cd, 2), "propagated": round(pr, 2),
                                           "strength": round(st - base_strength, 2) if base else None,
                                           "note": "strength = unassigned frames' change over the original less the baseline's own strength redesign over the original"},
        "check": {"all_at_or_below_1": log["status"] == "passed", "steel_max": log["steel_max"],
                  "composite_max": log["composite_max"], "steel_over": log["steel_over"],
                  "composite_over_reported": log["composite_over_reported"], "finalize_log": "web/data/finalize.json"},
        "reactions_vs_fresh_export": reac,
        "takeoff_csv": f"takeoffs/{LABEL}.csv",
    })
    (DATA / "collapse_tonnage.json").write_text(json.dumps(ct, indent=1))
    return ct


def save_log(log: dict) -> None:
    """finalize.json = this run, with every earlier run (and its history) under "history"."""
    path = DATA / "finalize.json"
    history = []
    if path.exists():
        old = json.loads(path.read_text())
        history = old.pop("history", []) + [old]
    path.write_text(json.dumps({**log, "history": history}, indent=1))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--max-rounds", type=int, default=5)
    ap.add_argument("--data", default=None, help="project data folder (default ap/web/data)")
    ap.add_argument("--label", default="collapse_final", help="takeoff label (takeoffs/<label>.csv)")
    args = ap.parse_args()
    global DATA, LABEL
    DATA = Path(args.data).resolve() if args.data else DATA
    LABEL = args.label
    b = subprocess.run(["dotnet", "build", str(BRIDGE), "-v", "q"], cwd=REPO, capture_output=True, text=True)
    c = subprocess.run(["dotnet", "build", str(CLI), "-v", "q"], cwd=REPO, capture_output=True, text=True)
    if b.returncode or c.returncode:
        print((b.stdout + c.stdout)[-2000:])
        return 1
    ops = BridgeOps(args.model)
    prop = json.loads((DATA / "propagation.json").read_text())
    try:
        log, prop = finalize(ops, prop, max_rounds=args.max_rounds)
    except BridgeError as e:
        log = {"status": "error", "error": str(e)}
        save_log(log)
        print(f"finalize: error: {e}")
        return 1
    save_log(log)
    ops.current_sections()   # export the final state: building_final.json feeds the reaction check
    ct = update_tonnage(args.model, log)
    for r in log["rounds"]:
        for m in r["moves"]:
            print(f"  round {r['round']}: {m['frame']} {m['from']} -> {m['to']} (ratio {m['ratio_before']}, "
                  f"ETABS {m['etabs_pick']} {m['etabs_pick_ratio']}; {m['reason']})")
    prem = f"premium {ct['premium']['short_tons']:+} ({ct['premium']['percent']:+}%)" if ct["premium"] else "no baseline yet"
    print(f"finalize: {log['status']} after {len(log['rounds'])} round(s); steel max {log['steel_max']}, "
          f"composite max {log['composite_max']}; {ct['tonnage']['total']} short tons, {prem}")
    return 0 if log["status"] == "passed" else 5


if __name__ == "__main__":
    raise SystemExit(main())
