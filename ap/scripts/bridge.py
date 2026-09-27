"""Thin wrapper around the C# bridge (tools/Quikcolaps.Bridge) so the whole pipeline can be
driven from Python. Windows only; ETABS must be running with the model open.

    python scripts/bridge.py export
    python scripts/bridge.py stacks
    python scripts/bridge.py apply            # dry run
    python scripts/bridge.py apply --commit
    python scripts/bridge.py results --run --design
    python scripts/bridge.py axial
    python scripts/bridge.py assign-sections            # dry run; --commit to write

Extra arguments are passed through (e.g. --model "my model" --template CS1).
File locations default to ap/web/data/ so the viewer picks them up.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

AP = Path(__file__).resolve().parents[1]
REPO = AP.parent
PROJECT = REPO / "tools" / "Quikcolaps.Bridge"
DATA = AP / "web" / "data"

DEFAULTS = {
    "export": ["--out", str(DATA / "building.json")],
    "stacks": ["--scenarios", str(DATA / "scenarios.json"), "--out", str(DATA / "stacks.json")],
    "apply": ["--scenarios", str(DATA / "scenarios.json")],
    "results": ["--scenarios", str(DATA / "scenarios.json"), "--out", str(DATA / "results.json")],
    "forces": [],
    "axial": ["--case", "1.2D+0.5L", "--out", str(DATA / "intact_axial.json")],
    "assign-sections": ["--file", str(DATA / "propagation.json")],
}


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] not in DEFAULTS:
        print(__doc__)
        return 2
    cmd, extra = sys.argv[1], sys.argv[2:]
    args = ["dotnet", "run", "--project", str(PROJECT), "--", cmd, *DEFAULTS[cmd], *extra]
    print(" ".join(args))
    return subprocess.call(args, cwd=REPO)


if __name__ == "__main__":
    raise SystemExit(main())
