"""Step failing fixed members up one section, with their symmetry counterparts.

After the propagated sections are fixed, a final run can leave a few members over 1.0 (their
sizes came from an earlier round's forces). This steps each named frame to the next heavier
section of its series and gives the same section to its images under the building's framing
symmetries (core/conditions.py), so symmetric members stay alike. Nothing gets lighter: a
counterpart already heavier keeps its section.

    python -m core.stepup --frames 9,29,46,61 [--current web/data/building_final.json]
        [--propagation web/data/propagation.json] [--results web/data/results.json]

Updates propagation.json in place: `assignments` (frame, section, from = current section)
and one row per changed frame with reason "check: ...". `bridge assign-sections` then writes
them; it refuses a section that is not defined in the model.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .conditions import _plan_ops, symmetry
from .model import load_building
from .propagate import Frames, weight

# AISC W14 shapes, light to heavy (lb/ft).
W14 = [22, 26, 30, 34, 38, 43, 48, 53, 61, 68, 74, 82, 90, 99, 109, 120, 132, 145, 159, 176, 193, 211,
       233, 257, 283, 311, 342, 370, 398, 426, 455, 500, 550, 605, 665, 730]


def next_heavier(section: str) -> str | None:
    w = weight(section)
    if w is None or not section.upper().startswith("W14X"):
        return None
    heavier = [x for x in W14 if x > w]
    return f"W14X{heavier[0]}" if heavier else None


def step_up(b: dict, propagation: dict, frames: list[str], current: dict[str, str],
            ratios: dict[str, float] | None = None) -> tuple[dict, list[str]]:
    """Returns (updated propagation, messages). current: frame -> section in the model now."""
    fr = Frames(b)
    ops = _plan_ops(b)
    op_names = list(symmetry(b))
    # `from` must be the section in the model now (assign-sections checks it): refresh every row
    asg = {a["frame"]: {**a, "from": current.get(a["frame"], a["from"])} for a in propagation["assignments"]}
    msgs, rows = [], []
    for f in frames:
        now = current[f]
        up = next_heavier(now)
        if up is None:
            msgs.append(f"{f}: no heavier W14 after {now}; not changed")
            continue
        targets = [(f, "identity")] + [(fr.image(f, ops[n]), n) for n in op_names]
        for t, n in targets:
            if t is None:
                msgs.append(f"{f}: no frame at its {n} image")
                continue
            have = asg[t]["section"] if t in asg else current[t]
            if (weight(have) or 0) >= (weight(up) or 0):
                rows.append({"member": f, "counterpart": t, "symmetry": n, "from": have, "to": have,
                             "reason": f"check: {f} stepped {now} -> {up}; {t} already {have}", "flags": []})
                continue
            asg[t] = {"frame": t, "section": up, "from": current[t]}
            r = f" (ratio {ratios[f]:.3f})" if ratios and f in ratios else ""
            rows.append({"member": f, "counterpart": t, "symmetry": n, "from": have, "to": up,
                         "reason": f"check: {f} over 1.0{r}, stepped {now} -> {up}" + ("" if t == f else f", copied by {n}"),
                         "flags": []})
    out = dict(propagation)
    out["assignments"] = sorted(asg.values(), key=lambda a: (len(a["frame"]), a["frame"]))
    out["check_rows"] = propagation.get("check_rows", []) + rows
    s = dict(out.get("summary", {}))
    s["frames_assigned"] = len(out["assignments"])
    s["check_steps"] = s.get("check_steps", 0) + 1
    out["summary"] = s
    return out, msgs


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--frames", required=True)
    ap.add_argument("--current", default="web/data/building_final.json",
                    help="export of the model now (sections in the model)")
    ap.add_argument("--propagation", default="web/data/propagation.json")
    ap.add_argument("--results", default="web/data/results.json")
    args = ap.parse_args()
    b = load_building(args.current)
    current = {c["id"]: c["section"] for c in b["columns"]} | {m["id"]: m["section"] for m in b["beams"]}
    prop = json.loads(Path(args.propagation).read_text())
    res = json.loads(Path(args.results).read_text()) if Path(args.results).exists() else {"members": {}}
    ratios = {f: m["max_ratio"] for f, m in res["members"].items()}
    frames = [x.strip() for x in args.frames.split(",") if x.strip()]
    out, msgs = step_up(b, prop, frames, current, ratios)
    Path(args.propagation).write_text(json.dumps(out, indent=1))
    for r in [r for r in out["check_rows"] if r["member"] in frames][-4 * len(frames):]:
        print(f"  {r['member']:>5} -> {r['counterpart']:>5} {r['symmetry']:<11} {r['from']} -> {r['to']}")
    for m in msgs:
        print(f"  note: {m}")
    print(f"{len(out['assignments'])} assignments -> {args.propagation}")


if __name__ == "__main__":
    main()
