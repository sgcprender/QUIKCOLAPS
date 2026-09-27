# Decision log

Short records of choices that shape the code. Add new ones at the bottom; don't
rewrite old ones, supersede them.

## D1. Linear static with all m-factors = 1.0
Use one amplification factor (2.0) and check every member with Φ Rn ≥ Ru at
nominal strength. Equivalent to the 2009 linear procedure with m = 1, which is
its most conservative case (ΩLD = 0.9m + 1.1 = 2.0 at m = 1; capacity grows with m
faster than load). Avoids needing ASCE 41 m-factor tables and connection types.

## D2. Alternate Path only
No tie forces, no Enhanced Local Resistance. Report must state full compliance
only for Risk Category II Option 2.

## D3. No connection tags
End conditions in the ETABS model are taken as given. Connections are not
checked. Listed as an exclusion in the report.

## D4. Simultaneous removal (30% rule) is implemented
`core/regions.py: simultaneous_removals`. Radius = 0.30 × largest plan dimension
of the bays touching the removed column at its top level.

## D5. One ETABS model, staged construction cases
Each scenario is a staged construction case built from the template CS1: start
from the loaded initial case, remove the column(s), load the region group. Must
be validated against a hand-deleted model first (bridge `forces` +
`scripts/compare_forces.py`). Result: _not yet run_.
2026-09-26: the hand-deleted comparison is deferred; all 23 scenarios are kept
(plan A). Until it is run, each staged case is checked only by the base-reaction
check in `bridge results`: reaction(case) − reaction(initial case) must equal the
scenario's `increment_total_kn` within 1% (config `reaction_check_tolerance`).
The check confirms the loads reach the model; it does not confirm that staged
removal redistributes forces like a deleted column.

## D6. Increment on the region (superseded in part by D13)
Base combination everywhere + increment (amp − 1) × base on the region. In
ETABS the increment is the template loading the region group; `core/loads.py`
computes the expected total for the viewer and the reaction check.

## D7. No wind, no live load reduction
2009 AP combinations have no wind. LLR is allowed but must use the pre-removal
structure; we skip it (conservative, simpler).

## D8. Literal amplified region by default
Adjacent bays at all floors above (bays that don't exist at a level drop out).
Claude may propose a different region only for flagged geometry, and it is used
only after the user approves it (`region_override`).

## D9. Story selection conventions
Mid-height story = ceil(n/2) counted from the bottom (10 stories → Story5, as in
the UFC example). Stories marked unoccupied or below grade are not counted.

## D10. Minimum candidate set picks one of each
One corner, one mid-long-side and one mid-short-side column (deterministic
tie-breaks), plus all re-entrant corners and bay-size changes (ratio ≥ 1.5,
config). Claude and the user add the rest.

## D11. SI units only on the Python side
The bridge sets ETABS present units to kN, m for every exchange and restores
them afterwards. The existing takeoff tool keeps its own units (lb, ft).

## D12. ETABS topology defines the amplified region
When `stacks.json` is available, a scenario's region is the union of the
removed columns' influence areas from `ColumnStack.Trace` (floor areas on the
top joints of the column and of every column directly above). That is exactly
what gets loaded in ETABS. The rule-based region is kept as `rule_bays` and any
difference raises `etabs_region_differs_from_rule` for the user to review. A
difference usually means floors aren't modelled one area per bay.

## D13. Load groups hold region beams as well as floor areas (not shared edges)
The existing tool's group holds floor areas only, so beam self-weight and
facade line loads in the region would not be amplified. The bridge adds the
region's beams (from `core`) to the group.
Revised 2026-09-26 (option A+): a beam on an edge shared with a bay outside the
region is left out of the group (`region.shared_edge_beams`). Beams inside the
region, between two region bays, or on the building's outer edge stay in.
Why: in ETABS a beam in the group brings the deck load it collects from the
neighbouring bay with it. On SC03 (6 corner bays) the reaction change exceeded
the region total by 16.5% for SDL and 16.3% for LL, the load on one 1.219 m
strip (half the infill spacing) of the next bay's deck on each of the six edge
beams parallel to the deck supports; SW +12.7% likewise. Leaving shared-edge
beams out means their self-weight is not amplified (on SC03, 1.2 × 76 kN of
12 beams) and the expected increment excludes it (SC03: 4075.2 → 3983.5 kN).

## D14. Existing code is not modified
`src/`, `tools/Quikcolaps.Cli`, `tools/Quikcolaps.Probe` and the root files stay
as they are. New ETABS work goes in `tools/Quikcolaps.Bridge`; everything else
in `ap/`. Multi-column removal is implemented in the bridge rather than by
changing `CaseTemplate.For`.

## D15. Template case convention
CS1 (built by hand): initial case = 1.2D + (0.5L or 0.2S) on the whole
building, no wind; removes exactly one column; loads exactly one group with the
same patterns at 1.0. `bridge results` checks it through base reactions.

## D16. Names
Case `AP_SCnn`, load group `AP_SCnn_LOAD`, combo `AP_SCnn_CMB` (matches the
existing tool's `<case>_CMB`, so `quikcolaps design-combos` recognises them as
collapse combos).

## D17. Load factors come from the ETABS initial case
The bridge exports the template's initial case (CS1 → `1.2D+0.5L`: 1.2 SW,
1.2 SDL, 0.5 LL) into `building.json` as `combination`. When it is present,
`core/loads.py` uses those factors for every bay, roof included, so the
increment is what ETABS applies to the region group; config factors and the
roof rule (0.5 Lr / 0.2 S) apply only to buildings without it (the demo).
Why: the model carries its 100 psf LL on the roof as an ordinary live pattern,
and the staged case applies 0.5 × LL there; the config roof rule dropped it and
every roof-reaching region would have failed the reaction check (~128 kN per
roof bay). A kind whose patterns carry different factors is not exported and
stops `core` with an error rather than being averaged. Checked on the working
model (2026-09-26): SW, SDL and LL totals from `building.json` match the ETABS
base reactions within 0.34%, 0% and 0%.
