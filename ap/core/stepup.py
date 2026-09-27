"""Step failing fixed members up one section, with their symmetry counterparts.

`apply_sections` (a section on a member and its symmetry images) is shared with core/finalize.py.

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

# AISC shapes by series, light to heavy (lb/ft).
SERIES = {
    "W14": [22, 26, 30, 34, 38, 43, 48, 53, 61, 68, 74, 82, 90, 99, 109, 120, 132, 145, 159, 176, 193, 211,
            233, 257, 283, 311, 342, 370, 398, 426, 455, 500, 550, 605, 665, 730],
    "W24": [55, 62, 68, 76, 84, 94, 103, 104, 117, 131, 146, 162, 176, 192, 207, 229, 250, 279, 306, 335, 370],
}
W14 = SERIES["W14"]


def next_heavier(section: str) -> str | None:
    """Next section of the same series (W14, W24), or None."""
    w = weight(section)
    series = (section or "").upper().split("X")[0]
    if w is None or series not in SERIES:
        return None
    heavier = [x for x in SERIES[series] if x > w]
    return f"{series}X{heavier[0]}" if heavier else None


def apply_sections(b: dict, propagation: dict, targets: dict[str, tuple[str, str]],
                   current: dict[str, str]) -> tuple[dict, list[dict], list[str]]:
    """Gives each target frame its section and the same section to its images under the
    framing symmetries, never lighter than what a frame has (assigned or in the model).

    targets: frame -> (section, reason). current: frame -> section in the model now; every
    assignment's `from` is refreshed from it (assign-sections checks `from`).
    Returns (updated propagation, rows, messages).
    """
    fr = Frames(b)
    ops = _plan_ops(b)
    op_names = list(symmetry(b))
    asg = {a["frame"]: {**a, "from": current.get(a["frame"], a["from"])} for a in propagation["assignments"]}
    msgs, rows = [], []
    for f, (up, reason) in targets.items():
        for t, n in [(f, "identity")] + [(fr.image(f, ops[k]), k) for k in op_names]:
            if t is None:
                msgs.append(f"{f}: no frame at its {n} image")
                continue
            have = asg[t]["section"] if t in asg else current[t]
            if (weight(have) or 0) >= (weight(up) or 0):
                rows.append({"member": f, "counterpart": t, "symmetry": n, "from": have, "to": have,
                             "reason": f"{reason}; {t} already {have}", "flags": []})
                continue
            asg[t] = {"frame": t, "section": up, "from": current[t]}
            rows.append({"member": f, "counterpart": t, "symmetry": n, "from": have, "to": up,
                         "reason": reason + ("" if t == f else f", copied by {n}"), "flags": []})
    out = dict(propagation)
    out["assignments"] = sorted(asg.values(), key=lambda a: (len(a["frame"]), a["frame"]))
    out["check_rows"] = propagation.get("check_rows", []) + rows
    s = dict(out.get("summary", {}))
    s["frames_assigned"] = len(out["assignments"])
    s["check_steps"] = s.get("check_steps", 0) + 1
    out["summary"] = s
    return out, rows, msgs


def step_up(b: dict, propagation: dict, frames: list[str], current: dict[str, str],
            ratios: dict[str, float] | None = None) -> tuple[dict, list[str]]:
    """Next heavier section on each frame and its images. Returns (updated propagation, messages)."""
    targets, msgs = {}, []
    for f in frames:
        now = current[f]
        up = next_heavier(now)
        if up is None:
            msgs.append(f"{f}: no heavier section after {now} in {sorted(SERIES)}; not changed")
            continue
        r = f" (ratio {ratios[f]:.3f})" if ratios and f in ratios else ""
        targets[f] = (up, f"check: {f} over 1.0{r}, stepped {now} -> {up}")
    out, _, more = apply_sections(b, propagation, targets, current)
    return out, msgs + more


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
