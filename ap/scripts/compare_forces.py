"""Staged-case validation (decision D5): compare frame forces from the single-model staged case
with forces from a model where the column was deleted by hand.

    python scripts/compare_forces.py staged.json deleted.json [--tol 0.01]

Both files come from `quikcolaps-bridge forces`. Exits 1 if any force differs by more than tol
(relative, on the larger of the two values; tiny forces compared against 1 kN / 1 kN·m).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def compare(a: dict, b: dict, tol: float) -> list[str]:
    bad = []
    for frame in sorted(set(a) & set(b)):
        for key in ("p_kn", "v2_kn", "m3_knm"):
            x, y = a[frame][key], b[frame][key]
            scale = max(abs(x), abs(y), 1.0)
            rel = abs(x - y) / scale
            line = f"{frame:>10} {key:<7} staged {x:10.2f}  deleted {y:10.2f}  diff {rel:6.2%}"
            print(line)
            if rel > tol:
                bad.append(line)
    missing = sorted(set(a) ^ set(b))
    if missing:
        print(f"frames only in one file: {missing}")
    return bad


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("staged")
    ap.add_argument("deleted")
    ap.add_argument("--tol", type=float, default=0.01)
    args = ap.parse_args()
    a = json.loads(Path(args.staged).read_text())["frames"]
    b = json.loads(Path(args.deleted).read_text())["frames"]
    bad = compare(a, b, args.tol)
    print(f"\n{len(bad)} value(s) differ by more than {args.tol:.0%}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
