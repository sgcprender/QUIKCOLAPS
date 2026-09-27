"""Tonnage files for a project (short tons): the baseline summary and the premium.

baseline_tonnage.json: from the baseline takeoff CSV (quikcolaps weigh) and the iterate log.
collapse_tonnage.json is written by scripts/finalize.py; `update_premium` redoes its premium and
split against the baseline without weighing again.
"""
from __future__ import annotations

import csv
import json
import re
from pathlib import Path


def _w(section: str) -> float:
    m = re.search(r"X([\d.]+)$", section or "")
    return float(m.group(1)) if m else 0.0


def original_sections(building: dict) -> dict[str, str]:
    return {c["id"]: c["section"] for c in building["columns"]} | {m["id"]: m["section"] for m in building["beams"]}


def baseline_summary(folder: Path, takeoff_csv: Path, rounds_file: Path, model_name: str) -> dict:
    b = json.loads((folder / "building.json").read_text())
    orig = original_sections(b)
    rows = list(csv.DictReader(open(takeoff_csv, encoding="utf-8")))
    it = json.loads(rounds_file.read_text())
    tons = lambda pred, key=lambda r: float(r["Lb"]): round(sum(key(r) for r in rows if pred(r)) / 2000, 2)
    kind = lambda r: "column" if r["Kind"] == "Column" else ("composite beam" if r["SectionSource"].startswith("composite") else "steel beam")
    chg = [r for r in rows if r["Frame"] in orig and r["Section"] != orig[r["Frame"]]]
    out = {
        "model": model_name, "units": "short tons (2000 lb); nominal lb/ft from the AISC name x length",
        "design": {"steel_combos": it["steel_combos"], "composite_combos": it["composite_combos"], "cases_run": it["cases"],
                   "rounds": len(it["rounds"]), "max_rounds": it["max_rounds"], "converged": it["converged"],
                   "frames_differing_after_each_round": [r["frames_differing"] for r in it["rounds"]],
                   "steel_max_ratio_last_round": it["rounds"][-1]["steel_max_ratio"] if it["rounds"] else None},
        "tonnage": {"total": tons(lambda r: True), "columns": tons(lambda r: r["Kind"] == "Column"),
                    "beams": tons(lambda r: r["Kind"] != "Column"), "steel_beams": tons(lambda r: kind(r) == "steel beam"),
                    "composite_beams": tons(lambda r: kind(r) == "composite beam"),
                    "original_sections_total": tons(lambda r: r["Frame"] in orig,
                                                    lambda r: _w(orig[r["Frame"]]) * float(r["LengthFt"]))},
        "changed_from_original": {"frames": len(chg), "heavier": sum(_w(r["Section"]) > _w(orig[r["Frame"]]) for r in chg),
                                  "lighter": sum(_w(r["Section"]) < _w(orig[r["Frame"]]) for r in chg)},
        "takeoff_csv": str(takeoff_csv),
    }
    (folder / "baseline_tonnage.json").write_text(json.dumps(out, indent=1))
    return out


def update_premium(folder: Path) -> dict | None:
    ct_path, b_path = folder / "collapse_tonnage.json", folder / "baseline_tonnage.json"
    if not (ct_path.exists() and b_path.exists()):
        return None
    ct, base = json.loads(ct_path.read_text()), json.loads(b_path.read_text())["tonnage"]
    total = ct["tonnage"]["total"]
    ct["baseline_total"] = base["total"]
    ct["premium"] = {"short_tons": round(total - base["total"], 2), "percent": round(100 * (total - base["total"]) / base["total"], 1)}
    so = ct["split_over_original_sections"]
    ct["split_of_premium_over_baseline"] = {
        "collapse_driven": so["collapse_driven"], "propagated": so["propagated"],
        "strength": round(so["strength_and_other"] - (base["total"] - base["original_sections_total"]), 2),
        "note": "strength = unassigned frames' change over the original less the baseline's own strength redesign over the original"}
    ct_path.write_text(json.dumps(ct, indent=1))
    return ct
