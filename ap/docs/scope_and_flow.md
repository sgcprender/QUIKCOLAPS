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

The app runs in this order (recorded 2026-09-26):

**export → intact gravity run (1.2D+0.5L) → read axial loads → candidates +
condition table → Claude review → approval → unlock → apply staged cases → run →
design**

| Stage | Command | Writes to the model |
|---|---|---|
| export | `bridge export` | no |
| intact gravity run | ETABS analysis of the template's initial case `1.2D+0.5L` (already run on a model whose staged cases have been analysed: it is their initial case) | analysis only |
| read axial loads | `bridge forces --case "1.2D+0.5L" --frames <all columns>` → `web/data/intact_axial.json` | no (read-only; no analysis) |
| candidates + condition table | `core.cli` (rule candidates), `core.conditions` → `web/data/conditions.json` | no |
| Claude review | `claude_client.run_review --mode conditions` → `web/data/review_conditions.json` (validated; cited values checked against the table) | no |
| approval | viewer / user → approved candidates → `core.cli --candidates` → `scenarios.json` | no |
| unlock | `SetModelIsLocked(false)` on the working copy (deletes results) | yes, with approval |
| apply staged cases | `bridge apply --commit` | yes, with approval |
| run, design | `bridge results --run --design` (composite first, then steel) | yes, with approval |

The steps below give the detail.

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
| 1, 5, 6 | tools/Quikcolaps.Bridge | working on the AP2 working copy: export checked against base reactions, 23 scenarios applied, run, converged and within 1% on reactions; steel and composite design results in `web/data/results.json` (one design pass, before any redesign iteration) |
| 3 (stacks), 7 | tools/Quikcolaps.Bridge | written, not yet run |
| 2, 4 | web | working on the synthetic fixture |
| 3 (rules, ETABS-region merge) | core | working, tested on the fixture |
| 3 (intact axial, condition table) | bridge forces, core.conditions | run on AP2 (read-only): Story1 column sum 141,439.9 kN against 141,440.4 kN from the measured base reactions (1.2 SW + 1.2 SDL + 0.5 LL); 200 perimeter rows, 5 symmetry groups (framing symmetric about both axes; a 0.15 × 0.15 m deck area at C29 on every floor, ids 50…455, has no mirror image) |
| 3 (Claude review) | claude_client | run on AP2 with the API key (claude-opus-5-5, structured output), 2026-09-26: (a) raw geometry, $0.22, the minimum set only; (b) candidates + condition table, $0.47, accepts the 3 rule locations and proposes C5 (lightly loaded adjacent corner). All cited values match the table. **Awaiting approval; scenario set unchanged (23)** |
| 8–12 | web, core | not started |
| 13 | report | tables only; tonnage from the existing Cli tool |

## Next session

1. ~~**Design forces for staged combos.**~~ Resolved 2026-09-26: composite beam
   design was resetting the steel design sections after steel design; the
   bridge now runs composite first (`tools/Quikcolaps.Bridge/CLAUDE.md`).
2. **Redesign loop with similarity.** Propose section changes for failing
   members and similar members (`results.redesign`), apply with approval,
   re-run with `--accept-design-sections` as a deliberate iteration.
3. ~~**Claude review with the API key.**~~ Run 2026-09-26 (see status); the
   decision on the proposed additions is the user's.
4. **Viewer results view.** Show reaction checks, ratios and failing members
   per scenario from `results.json`.
5. **Local server.** Serve the viewer and data locally for the team
   (`python -m http.server` today).
