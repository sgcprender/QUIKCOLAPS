"""Which stories to analyze for each removal location. UFC 3-2.9.2.2.

For each plan location, analyze:
  1. first story above grade
  2. story directly below the roof (top story)
  3. story at mid-height
  4. story above a column splice or change in column size
Duplicates collapse (short buildings).
"""
from __future__ import annotations

import math

from .model import above_grade_stories, columns_at


def mid_height_index(n: int) -> int:
    """0-based index of the mid-height story among n stories.

    Convention (document it in the report): ceil(n/2) counted from 1, i.e.
    4 stories -> Story2, 5 -> Story3, 10 -> Story5 (matches the UFC's 10-story example).
    """
    return max(0, math.ceil(n / 2) - 1)


def splice_stories(b: dict, location_id: str) -> list[str]:
    """Stories directly above a splice or section change at this location."""
    segs = columns_at(b, location_id)
    out = []
    for prev, cur in zip(segs, segs[1:]):
        if cur.get("splice_at_bottom") or cur["section"] != prev["section"]:
            out.append(cur["story"])
    return out


def select_stories(b: dict, location_id: str) -> list[dict]:
    """Return [{'story': name, 'reasons': [...]}] ordered bottom to top."""
    stories = above_grade_stories(b)
    present = {c["story"] for c in columns_at(b, location_id)}
    stories = [s for s in stories if s["name"] in present]
    if not stories:
        return []
    picks: dict[str, list[str]] = {}

    def add(name: str, reason: str) -> None:
        picks.setdefault(name, [])
        if reason not in picks[name]:
            picks[name].append(reason)

    add(stories[0]["name"], "first_story_above_grade")
    add(stories[-1]["name"], "story_below_roof")
    add(stories[mid_height_index(len(stories))]["name"], "mid_height")
    for s in splice_stories(b, location_id):
        if s in {st["name"] for st in stories}:
            add(s, "above_splice_or_size_change")

    order = {s["name"]: i for i, s in enumerate(stories)}
    return [{"story": n, "reasons": r} for n, r in sorted(picks.items(), key=lambda kv: order[kv[0]])]
