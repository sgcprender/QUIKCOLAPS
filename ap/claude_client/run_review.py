"""Run the step 3 Claude review on a building and save the validated result.

    python -m claude_client.run_review --mode raw        --out web/data/review_raw.json
    python -m claude_client.run_review --mode conditions --out web/data/review_conditions.json
    python -m claude_client.run_review --compare web/data/review_raw.json web/data/review_conditions.json

Both modes are validated the same way against the rule candidates
(validate.validate_review: unknown locations dropped, mandatory kept, stories by
rule) and every cited value is checked against the condition table
(validate.check_evidence). Nothing here changes scenarios.json: adding a
location to the scenario set goes through user approval (`core.cli --candidates`).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from core.candidates import perimeter_locations
from core.model import load_building, load_config

from .review import review_candidates
from .validate import check_evidence, validate_review


def run(args) -> None:
    cfg = load_config(args.config)
    b = load_building(args.building)
    rule = json.loads(Path(args.scenarios).read_text())["candidates"]
    conditions = json.loads(Path(args.conditions).read_text())
    axial = json.loads(Path(args.axial).read_text())
    review, meta = review_candidates(b, rule, cfg, mode=args.mode,
                                     conditions=conditions if args.mode == "conditions" else None,
                                     with_meta=True)
    merged, issues = validate_review(b, rule, review)
    evidence, ev_issues = check_evidence(conditions, axial, review)
    perim = perimeter_locations(b)
    for d in review.get("decisions", []):
        if d.get("decision") == "add" and d.get("location_id") not in perim and d.get("location_id") in {
                c["location_id"] for c in b["columns"]}:
            issues.append(f"{d['location_id']} is not a perimeter column (internal removals are out of scope).")
    out = {"meta": meta, "review": review, "merged_candidates": merged,
           "issues": issues + ev_issues, "evidence": evidence}
    Path(args.out).write_text(json.dumps(out, indent=1))
    ok = sum(e["status"] == "ok" for e in evidence)
    print(f"{args.mode}: {len(review['decisions'])} decisions, evidence {ok}/{len(evidence)} ok, "
          f"{len(issues) + len(ev_issues)} issues, {meta['usage']} ${meta['cost_usd']:.4f} "
          f"{meta['seconds']} s -> {args.out}")


def compare(paths: list[str], scenarios: str, conditions: str) -> str:
    """Markdown: one row per perimeter location, rule vs each run."""
    runs = [json.loads(Path(p).read_text()) for p in paths]
    rule = {c["location_id"]: c for c in json.loads(Path(scenarios).read_text())["candidates"]}
    t = json.loads(Path(conditions).read_text())
    group = {r["location_id"]: r["symmetry_group"] for r in t["rows"]}
    locs = sorted(group, key=lambda l: (group[l], int(l[1:])))
    names = [r["meta"]["mode"] for r in runs]
    lines = ["| Location | Group | Rule | " + " | ".join(names) + " |",
             "|---|---|---|" + "---|" * len(runs)]
    for loc in locs:
        cells = []
        for r in runs:
            ds = [d for d in r["review"]["decisions"] if d["location_id"] == loc]
            cells.append("; ".join(f"**{d['decision']}** ({d['condition']}, {d['confidence']})" for d in ds) or "")
        rc = ", ".join(x["code"] for x in rule[loc]["reasons"]) if loc in rule else ""
        if any(cells) or rc:
            lines.append(f"| {loc} | {group[loc]} | {rc} | " + " | ".join(cells) + " |")
    lines += ["", "| | " + " | ".join(names) + " |", "|---|" + "---|" * len(runs)]
    for label, f in [("model", lambda r: r["meta"]["model"]),
                     ("input tokens", lambda r: f"{r['meta']['usage']['input_tokens']:,}"),
                     ("output tokens (incl. thinking)", lambda r: f"{r['meta']['usage']['output_tokens']:,}"),
                     ("cost (USD)", lambda r: f"{r['meta']['cost_usd']:.4f}"),
                     ("time (s)", lambda r: str(r["meta"]["seconds"])),
                     ("evidence ok / cited", lambda r: f"{sum(e['status'] == 'ok' for e in r['evidence'])} / "
                                                        f"{len(r['evidence'])}"),
                     ("evidence mismatches", lambda r: str(sum(e['status'] == 'mismatch' for e in r['evidence']))),
                     ("validation issues", lambda r: str(len(r["issues"])))]:
        lines.append(f"| {label} | " + " | ".join(f(r) for r in runs) + " |")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["raw", "conditions"])
    ap.add_argument("--building", default="web/data/building.json")
    ap.add_argument("--scenarios", default="web/data/scenarios.json")
    ap.add_argument("--conditions", default="web/data/conditions.json")
    ap.add_argument("--axial", default="web/data/intact_axial.json")
    ap.add_argument("--config", default=None)
    ap.add_argument("--out", default=None)
    ap.add_argument("--compare", nargs="+", default=None)
    args = ap.parse_args()
    if args.compare:
        print(compare(args.compare, args.scenarios, args.conditions))
        return
    if not args.mode:
        ap.error("--mode or --compare is required")
    args.out = args.out or f"web/data/review_{args.mode}.json"
    run(args)


if __name__ == "__main__":
    main()
