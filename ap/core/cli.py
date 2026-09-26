"""Command line: building JSON -> candidates + scenarios JSON.

    python -m core.cli fixtures/demo_building.json --out web/data/scenarios.json

Runs the deterministic part of steps 3 and 5 of the flow (no Claude, no ETABS),
so the viewer and the ETABS bridge have something real to consume.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .candidates import generate_candidates
from .model import load_building, load_config, load_stacks
from .scenarios import build_scenarios
from .stories import select_stories


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("building")
    ap.add_argument("--out", default="web/data/scenarios.json")
    ap.add_argument("--config", default=None)
    ap.add_argument("--stacks", default=None,
                    help="stacks.json from quikcolaps-bridge; ETABS influence areas become the regions")
    ap.add_argument("--candidates", default=None,
                    help="approved candidates JSON (from the viewer); default: all rule candidates")
    args = ap.parse_args()

    cfg = load_config(args.config)
    b = load_building(args.building)
    if args.candidates:
        cands = json.loads(Path(args.candidates).read_text())["candidates"]
        for c in cands:  # locations added by the user in the viewer have no stories yet
            if not c.get("stories"):
                c["stories"] = select_stories(b, c["location_id"])
    else:
        cands = generate_candidates(b, cfg)
    stacks = load_stacks(args.stacks) if args.stacks else None
    scen = build_scenarios(b, cands, cfg, stacks)
    out = {"code": cfg["code"], "amplification_factor": cfg["loads"]["amplification_factor"],
           "candidates": cands, "scenarios": scen}
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, indent=2))
    # the viewer reads the building next to the scenarios (with derived outlines and grids)
    (Path(args.out).parent / "building.json").write_text(json.dumps(b, indent=2))
    print(f"{len(cands)} candidate locations -> {len(scen)} scenarios -> {args.out}")
    for s in scen:
        inc = s["increment"]
        print(f"  {s['id']}: {s['location_id']} @ {s['story']:<7} removed={len(s['removed_columns'])} "
              f"bays={len(s['region']['bays']):>2} increment={inc['increment_total_kn']:.0f} kN "
              f"flags={','.join(s['flags']) or '-'}")


if __name__ == "__main__":
    main()
