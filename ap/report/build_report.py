"""Build the submittal-style report (UFC 1-8) as Markdown.

    python -m report.build_report web/data/scenarios.json --results results.json --out report.md

Works with scenarios only (before analysis) and fills in pass/fail tables once
results JSON exists. The Claude narrative is a TODO: add a second Claude call
that turns this table data into the written justification.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

EXCLUSIONS = [
    "Connection checks (model end conditions taken as given)",
    "m-factors and expected strengths (all m = 1.0, nominal strengths: conservative)",
    "Enhanced Local Resistance and Tie Forces (required for Risk Category III/IV)",
    "Internal column removals (parking / uncontrolled public areas)",
    "Nonlinear static and nonlinear dynamic procedures",
]


def build(scen: dict, results: dict | None) -> str:
    code = scen["code"]
    lines = [
        "# Progressive collapse: Alternate Path report", "",
        f"**Criteria:** {code['edition']}  ",
        f"**Risk Category:** {code['risk_category']}  ",
        "**Design approach:** Alternate Path  ",
        f"**Method:** {code['method']}  ",
        f"**Amplification factor:** {scen['amplification_factor']}  ",
        "**Software:** ETABS (analysis and steel design), pc-ap-tool (scenario generation, checks)", "",
        "## Removal scenarios", "",
        "| Scenario | Location | Story | Why this location | Why this story | Removed | Increment (kN) | Flags |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for s in scen["scenarios"]:
        why_loc = ", ".join(r["code"] for r in s["location_reasons"])
        why_st = ", ".join(s["story_reasons"])
        lines.append(f"| {s['id']} | {s['location_id']} | {s['story']} | {why_loc} | {why_st} | "
                     f"{len(s['removed_columns'])} | {s['increment']['increment_total_kn']:.0f} | "
                     f"{', '.join(s['flags']) or '-'} |")
    if results:
        lines += ["", "## Results", "", "| Scenario | Max ratio | Failing members |", "|---|---|---|"]
        for sid, r in sorted(results.get("by_scenario", {}).items()):
            lines.append(f"| {sid} | {r['max_ratio']:.2f} | {len(r['failing'])} |")
    lines += ["", "## Simplifications and exclusions", ""] + [f"- {e}" for e in EXCLUSIONS]
    lines += ["", "## Narrative", "", "_TODO: Claude-written justification of the scenario set and redesign._"]
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("scenarios")
    ap.add_argument("--results", default=None)
    ap.add_argument("--out", default="report.md")
    a = ap.parse_args()
    scen = json.loads(Path(a.scenarios).read_text())
    res = json.loads(Path(a.results).read_text()) if a.results else None
    Path(a.out).write_text(build(scen, res))
    print(f"wrote {a.out}")


if __name__ == "__main__":
    main()
