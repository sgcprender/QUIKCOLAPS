# Scope and application flow

## Scope

| Item | Decision |
|---|---|
| Code basis | UFC 4-023-03 (2009, Change 4): Alternate Path, linear static, conservative simplification with every m-factor at 1.0 |
| Requirement covered | Alternate Path only. Fully compliant for Risk Category II Option 2; AP portion only for Categories III and IV |
| Structure | Steel framed, 3+ stories |
| Removal locations | External columns: corner, mid short side, mid long side, plus irregular spots (code + Claude, user-approved) |
| Stories per location | First story above grade, story below roof, mid-height, story above any column splice or size change |
| Multiple removal | Any column within 30% of the largest bay dimension of the removal is removed simultaneously |
| Model | Single ETABS model, one staged construction case per scenario |
| Loads | 2.0 × [1.2D + (0.5L or 0.2S)] on adjacent bays at all floors above the removal, and 1.2D + (0.5L or 0.2S) elsewhere. D includes façade, beam self-weight, and point loads. No wind. No live load reduction. |
| Strength | Nominal material strengths, Φ per AISC 360 |
| Checks | ETABS steel design: every member strength ratio ≤ 1.0, with unbraced-length overwrites near removals. No collapse area allowed. |
| Redesign | ETABS auto-select on failing and similar members, user-approved, then re-verify all scenarios and run the conventional design check |
| Web app | 3D viewer (three.js) built from the extracted JSON, with a 2D plan toggle. Used for approval, results, and the final design. |
| Claude | Candidate review, affected region for difficult geometry, failure pattern summary, report narrative |
| Out of scope | Connection checks, m-factors and expected strengths, Enhanced Local Resistance, tie forces, internal removals, nonlinear procedures |

## Application flow

Owner in brackets. `bridge` = the C# tool `tools/Quikcolaps.Bridge` (built on the
existing `src/Quikcolaps.Etabs` library); everything else is Python under `ap/`.

1. **Connect and extract** `[bridge export]`
   ETABS model → `building.json` in kN/m: stories, columns, beams, floor areas
   as polygons with their loads, sections, flags (columns with nothing under
   them). `core` derives outlines and grids. The base model is never saved.

2. **Render the building** `[web]`
   3D scene from `web/data/building.json`; every object tagged with its ETABS name.

3. **Generate candidates** `[core, bridge stacks, claude_client]`
   - `core.cli` finds the removal locations and their four stories, the 30%
     simultaneous removals, and flags difficult geometry.
   - `bridge stacks` traces each removed column's stack in ETABS and returns its
     influence area (floor areas on the top joints of the column and every
     column above). `core.cli --stacks` uses it as the amplified region and
     flags any difference from the rule-based region (D12).
   - One Claude call reviews the candidates; `claude_client/validate.py` checks it.

4. **Approve scenarios** `[web]`
   Removed segment, simultaneous removals, amplified region, 30% radius,
   flags. Accept, reject, add; export approvals; rerun `core.cli --candidates`.

5. **Build scenarios** `[bridge apply]`
   From the hand-built template case CS1: one staged case per scenario
   (`AP_SCnn`, several columns removed if needed), its load group
   (`AP_SCnn_LOAD`: region floor areas + region beams, D13) and its combo
   (`AP_SCnn_CMB`) selected for steel strength design. Dry run first; every
   write is read back.

6. **Analyze** `[bridge results --run]`
   Case status, and the base-reaction check per case: reaction(case) −
   reaction(initial case) = scenario increment within 1%.

7. **Check** `[bridge results --design]`
   Steel design; every frame's ratio and governing combo → scenario, into
   `results.json`.

8. **Review results** `[web]`
   Members colored by ratio per scenario, failing members highlighted.

9. **Propose redesign** `[core, claude_client]`
   Failing members + similar members; Claude summarizes the pattern.

10. **Approve redesign** `[web]`

11. **Redesign and re-verify** `[bridge + existing Cli tool]`
    Auto-select on approved members, rerun all scenarios; `quikcolaps
    design-combos strength` then steel design for the conventional check.

12. **Final design** `[web]` before/after toggle.

13. **Report** `[report, claude_client, existing Cli tool]`
    Submittal items (Risk Category, AP, linear static, software, input files),
    scenario set, pass matrix before/after, section changes, and the tonnage
    premium from `quikcolaps weigh` + `compare strength collapseonly`.

## Build order

1. Build the bridge on Windows, fix compile errors, verify the `VERIFY` calls.
2. Validate the single-model approach: `apply` + `forces` against a hand-deleted
   model, `scripts/compare_forces.py` (D5).
3. `export` the real model; run `core.cli` on it; check candidates and regions
   in the viewer.
4. `stacks`, then compare ETABS regions with the rule regions (flags in the viewer).
5. `apply --commit`, `results --run --design`; results view in the viewer.
6. Claude review call on the real model; redesign loop; report.

## Status

| Step | Owner | State |
|---|---|---|
| Existing: attach, stacks, cases, combos, design selection, takeoff | src/, tools/Cli | working on the team model |
| 1, 3 (stacks), 5, 6–7 | tools/Quikcolaps.Bridge | written, not yet compiled or run |
| 2, 4 | web | working on the synthetic fixture |
| 3 (rules, ETABS-region merge) | core | working, tested on the fixture |
| 3 (Claude review) | claude_client | written, tested with fake responses only |
| 8–12 | web, core | not started |
| 13 | report | tables only; tonnage from the existing Cli tool |
