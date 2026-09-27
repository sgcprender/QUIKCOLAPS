"""Finalize: make every steel member pass after the fixed (propagated) sections are assigned.

The loop, with ETABS behind an `ops` object (scripts/finalize.py gives the bridge-backed one;
tests give a fake):

    check: run all AP cases, design once (composite, then steel)
    while a steel member is over 1.0 and rounds < max_rounds:
        autoselect: put those members back on an auto-select list starting at their section
        check: run + design; ETABS picks their section from the same forces
        pick:  ETABS's section if it is heavier than the current one and passes; otherwise the
               next heavier section of the series (fallback: the list could not find one, or
               picked one that is not heavier)
        apply the pick to the member and its symmetry images, never lighter (core/stepup.py)
        assign: fixed sections, every `from` refreshed from the model
        check
    passed when nothing is over 1.0; otherwise not converged.

Composite beams over 1.0 are reported, not resized. ETABS refuses a section-list change on a
locked model (measured), so each autoselect unlocks and the pick needs its own run.
"""
from __future__ import annotations

from typing import Protocol

from .propagate import weight
from .stepup import apply_sections, next_heavier

LIMIT = 1.0


class Ops(Protocol):
    def check(self) -> dict: ...                                # run + design → results.json dict
    def autoselect(self, frames: list[str]) -> None: ...
    def current_sections(self) -> dict[str, str]: ...          # export → frame -> section
    def assign(self, propagation: dict) -> None: ...            # write, dry run, --commit
    def building(self) -> dict: ...                             # geometry for the symmetry images


def over_limit(results: dict, limit: float = LIMIT) -> tuple[dict[str, dict], dict[str, dict]]:
    """(steel members over the limit, composite beams over the limit): frame -> member row."""
    steel, comp = {}, {}
    for f, m in results["members"].items():
        if m["max_ratio"] > limit:
            (comp if m.get("kind") == "CompositeBeam" else steel)[f] = m
    return steel, comp


def pick(current: str, chosen: str | None, chosen_ratio: float | None, limit: float = LIMIT) -> tuple[str | None, str]:
    """(section, how): ETABS's pick if heavier than current and passing, else one size up."""
    if chosen and chosen_ratio is not None and chosen_ratio <= limit and (weight(chosen) or 0) > (weight(current) or 0):
        return chosen, "auto-select"
    up = next_heavier(max([current, chosen or current], key=lambda s: weight(s) or 0))
    why = ("auto-select found no passing section" if chosen_ratio is None or chosen_ratio > limit
           else f"auto-select picked {chosen}, not heavier than {current}")
    return up, f"step-up ({why})"


def finalize(ops: Ops, propagation: dict, max_rounds: int = 5, limit: float = LIMIT) -> tuple[dict, dict]:
    """Runs the loop. Returns (log, updated propagation). log["status"]: passed / not converged."""
    rounds = []
    results = ops.check()
    over, comp = over_limit(results, limit)
    for r in range(1, max_rounds + 1):
        if not over:
            break
        frames = sorted(over, key=lambda f: (len(f), f))
        ops.autoselect(frames)
        picked = ops.check()
        current = ops.current_sections()
        targets, moves = {}, []
        for f in frames:
            m = picked["members"].get(f, {})
            to, how = pick(current[f], m.get("section"), m.get("max_ratio"), limit)
            move = {"frame": f, "from": current[f], "ratio_before": round(over[f]["max_ratio"], 3),
                    "governing_combo": over[f].get("governing_combo"), "etabs_pick": m.get("section"),
                    "etabs_pick_ratio": round(m["max_ratio"], 3) if "max_ratio" in m else None, "to": to, "reason": how}
            moves.append(move)
            if to is None:
                move["reason"] += "; no heavier section in the series, left as is"
                continue
            targets[f] = (to, f"finalize round {r}: {f} ratio {over[f]['max_ratio']:.3f}, {how}, {current[f]} -> {to}")
        propagation, rows, msgs = apply_sections(ops.building(), propagation, targets, current)
        ops.assign(propagation)
        results = ops.check()
        over, comp = over_limit(results, limit)
        rounds.append({"round": r, "moves": moves,
                       "applied": [x for x in rows if x["from"] != x["to"]], "messages": msgs,
                       "after": {"steel_over": {f: round(m["max_ratio"], 3) for f, m in over.items()},
                                 "composite_over": {f: round(m["max_ratio"], 3) for f, m in comp.items()}}})
    status = "passed" if not over else "not converged"
    log = {"status": status, "max_rounds": max_rounds, "limit": limit, "rounds": rounds,
           "steel_over": {f: round(m["max_ratio"], 3) for f, m in over.items()},
           "composite_over_reported": {f: round(m["max_ratio"], 3) for f, m in comp.items()},
           "steel_max": round(max((m["max_ratio"] for m in results["members"].values() if m.get("kind") != "CompositeBeam"), default=0), 3),
           "composite_max": round(max((m["max_ratio"] for m in results["members"].values() if m.get("kind") == "CompositeBeam"), default=0), 3)}
    return log, propagation
