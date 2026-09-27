# Note: load groups of floor areas only may add almost no deck load

For whoever ran the existing tool's collapse cases (`quikcolaps` CLI, the
`CS_C*_Story1` cases and `INFLUENCE AREA_*` groups).

## What we found

On this model the floors are steel deck (`Deck1`). When a staged construction
case loads a group ("Load Objects", e.g. 1.2 SW + 1.2 SDL + 0.5 LL on the
group), the deck load reaches the structure **only through the beams in the
group**. Each beam in the group takes its one-way tributary strip of deck on
both sides; the deck areas in the group add nothing by themselves.

Measured on SC03 (column C1 at Story5, six corner bays), working copy,
2026-09-26:

| Load group | Increment from base reactions | Beam-strip model |
|---|---|---|
| 6 areas + all 36 beams touching them | 4,699.6 kN | 4,710.0 kN |
| 6 areas + 24 beams (shared edges left out) | 3,342.1 kN | 3,348.7 kN |

The region's own deck load is 3,808.8 kN. Both runs match the beam-strip model
within 0.2% and neither matches the region total.

## What it means for the earlier runs

The existing tool's groups (`INFLUENCE AREA_CS_C*_Story1`) held floor areas
only, no beams. By the same mechanism those cases would have added almost no
deck load (only whatever does not go through beams), so **their collapse runs
may have been badly under-loaded**, and any design checked against them may be
unconservative.

This is inferred from the two runs above; we did not run an areas-only group
to confirm it. To check: copy one `CS_C*` case, run it with its initial case,
and compare the base reaction change with the influence area's
1.2 D + 1.2 SDL + 0.5 L total. If it comes out near zero, re-run those cases
with the beams added to the groups (as the AP bridge now does, D13).

The CS_C* cases and their groups were deleted from the AP2 working copy; they
are still in the original model.

See `ap/docs/decisions.md` D13 and `tools/Quikcolaps.Bridge/CLAUDE.md`.
