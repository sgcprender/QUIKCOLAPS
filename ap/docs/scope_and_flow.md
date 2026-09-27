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
| 1, 5, 6 | tools/Quikcolaps.Bridge | working on the AP2 working copy (2026-09-26): export checked against base reactions; 30 scenarios (SC24–SC30 = C5) applied and read back; design sections reset to the original analysis sections (`DesignSteel.SetDesignSection(f, "", LastAnalysis: true)`, measured), then run with lean flags: 30/30 finished, 30/30 within 1% on reactions (−0.17% to −0.39%); one design pass (composite, then steel) in `web/data/results.json`: 1,260 frames, none over 1.0 with their design sections; 404 frames designed heavier than their original section (318 governed by an AP combo, 86 by DStlS2) |
| 3 (stacks), 7 | tools/Quikcolaps.Bridge | written, not yet run |
| 2, 4 | web | working on the synthetic fixture |
| 3 (rules, ETABS-region merge) | core | working, tested on the fixture |
| 3 (intact axial, condition table) | bridge forces, core.conditions | run on AP2 (read-only): Story1 column sum 141,439.9 kN against 141,440.4 kN from the measured base reactions (1.2 SW + 1.2 SDL + 0.5 LL); 200 perimeter rows, 5 symmetry groups (framing symmetric about both axes; a 0.15 × 0.15 m deck area at C29 on every floor, ids 50…455, has no mirror image) |
| 3 (Claude review) | claude_client | run on AP2 with the API key (claude-opus-5-5, structured output), 2026-09-26: (a) raw geometry, $0.22, the minimum set only; (b) candidates + condition table, $0.47, accepts the 3 rule locations and proposes C5 (lightly loaded adjacent corner). All cited values match the table. C5 approved by the user: 30 scenarios |
| 8–12 | web, core | not started |
| 13 | report | tables only; tonnage from the existing Cli tool |

## Build plan (demo)

Worked one item at a time; after each item: commit, push, update the status
here, and stop with a short report. Plan written 2026-09-26.

| Item | What | Status |
|---|---|---|
| A | **Bridge commands** (a local server will call these; each exits non-zero with a clear message on failure): `apply --commit` unlocks the model itself with read-back; `axial --case "1.2D+0.5L" --out <file>`; `assign-sections --file ap/web/data/propagation.json` sets analysis sections as fixed sections (no auto-select), dry run by default, `--commit` to write, with read-back. | **done** 2026-09-26. `ModelLock` shared by `apply` and `assign-sections`. Tested read-only on locked AP2: `axial` matches `intact_axial.json` on all 320 columns (lowest columns 141,439.9 kN against base reaction 141,440.4 kN); dry runs report the lock and write nothing; `assign-sections` refuses a file with a wrong `from`, an undefined section or a missing frame (exit 1). Not yet exercised: the unlock itself (first use: start of D) and `assign-sections --commit` (auto-select clearing to be read back in D). |
| B | **Similarity propagation** (`ap/core`, no ETABS): `python -m core.propagate` writes `ap/web/data/propagation.json`. Equivalent locations: all columns in the same symmetry group from `conditions.json` (G1–G5). For each member whose design section is heavier than its analysis section, record its position relative to the removed column of its governing scenario (bay offsets x/y, story offset, member type and direction). Apply that at every equivalent location, mirrored as needed, to find the counterpart; check it matches (type, direction, original section), else flag and don't copy. Biggest required section wins; never lighter than a member's own design section. Rows: member, counterpart, from → to, source scenario, reason, flags. Hand-checked tests. | **done** 2026-09-26. `core/propagate.py`, 3 hand-checked tests. `propagation.json` has `assignments` ({frame, section, from}, the `assign-sections` format) and the detailed rows. Run on the first design pass (before any redesign round): 318 collapse-driven members → 686 frames (318 collapse-driven, 368 propagated only: G1 42, G2 62, G3 129, G5 135, G4 none since no scenario is in it); 0 flagged rows; added steel 139.5 t collapse-driven + 143.0 t propagated (Δ lb/ft × length). To be rerun in D after the redesign rounds, on a fresh export (`--building`) with the original sections (`--original`). |
| C | **Strength-only baseline**: copy the original `progressive collapse.edb` on disk to `baseline strength.edb` (don't open or modify the original). Select only DStlS1 and DStlS2 for steel and composite design; iterate design (composite first, then steel) → accept design sections → run SW, SDL, LL → design, until no sections change (max 3 rounds). Save the tonnage (weigh) to `ap/web/data/baseline_tonnage.json`. Close it and return to AP2. | **done (not converged)** 2026-09-26. Original is `QUIKCOLAPS.EDB` (same sections and frame ids as AP2's original export); copied on disk (hash unchanged) to `baseline strength.EDB`. Bridge `open`, `design-select`, `iterate`. DStlS1 + DStlS2 for steel and composite; 3 rounds of SW, SDL, LL + design: 260 → 172 → 76 frames still changing (last ones step between neighbouring W14 sizes both ways), steel max ratio 0.948. **790.18 short tons** (columns 146.26, steel beams 366.72, composite beams 277.20; original sections 776.74); 228 frames differ from the original sizes (144 heavier, 84 lighter; 204 columns, 24 girders). `ap/web/data/baseline_tonnage.json`, `baseline_rounds.json`, `takeoffs/baseline_strength.csv`. AP2 reopened: locked, analysis results kept, design results not kept. |
| D | **Collapse redesign in AP2**: iterate accept design sections → run all 30 → design, until no sections change (max 3 rounds). Run propagation, stop and show the list. After approval: assign-sections, run all 30, design once, confirm all ≤ 1.0, save tonnage, compare with the baseline. | **done, passed** 2026-09-26. Redesign 3 rounds (896.12 → 911.70 → 913.57 short tons); 658 fixed sections from `propagation.json` (270 collapse-driven + 388 propagated); two manual step-up rounds (frames 9, 29, 46, 61, then 9, 29, with their symmetry images); then `finalize` (1 round): frame 9 W14X132 → W14X145 and girder 422 W24X76 → W24X84 (ETABS's picks, 0.907 and 0.901), each with its 3 symmetry images. **All steel ≤ 1.0 (max 0.992), composite max 0.587. 1,158.01 short tons, +367.83 (+46.5%) over the 790.18 baseline** (collapse-driven +176.92, propagated +205.03, strength −14.11). Reactions against the fresh export: 29/30 within 1% (−0.33% to −0.9%), SC07 −1.70% (open). `web/data/finalize.json`, `collapse_tonnage.json`. |
| E | **Report**: `python -m report.build_report` with baseline vs collapse tonnage, member counts (collapse-driven, propagated, strength) and a short Claude narrative. Mention the stray 0.15 × 0.15 m deck area at C29 and the roof loads (100 psf LL and SDL, as typical floors); both stay as they are. | not started |
| F | **Demo app**: `ap/server` + `ap/web`, landing page with projects, steps 0–7, 3D view modes, results panel. Full spec below ("Item F: demo app"). | in progress |
| G | **Extras**: automated validation (SC03 deleted-column copy vs staged case, record in D5); a Claude redesign summary shown in the app. | not started |

### Open items

- **SC07 reaction check** (C1 removed at Story10, one roof bay): −1.21% against the
  export after the redesign rounds, −1.45% after the final assignment (790 kN
  against 802 kN), −1.70% after the step-ups; −0.39% before the redesign. Every case drifts negative as the
  beams get heavier (−0.33% to −0.87% for the other 29). Not investigated yet.
### Item F: demo app (spec, 2026-09-27)

Demo app in `ap/server` and `ap/web`, using the commands in the command list
below (open, design-select, iterate, assign-sections, finalize, axial, apply,
results and the rest). Server: FastAPI + uvicorn, one step at a time, with a
live log and status. Start with `python -m server` from `ap/`; it opens in the
browser. Every step shows a clear error if its command fails.

**Landing page.** The app opens on a landing page with "Start new project" (file
picker for a .edb, then step 0) and a list of past projects. Each project card
shows name, model file, dates, the last completed step and status, and the
headline premium if available, with "Open" (view results from the saved data
without needing ETABS; resume from the last completed step if ETABS is
available) and "Remove from list" (never deletes files). Each project's data is
stored in its "<name> - quikcolaps" folder next to the model; a small project
index (JSON) is what the landing page reads. The current AP2 work is registered
as the first project so it opens with all its results.

**Model and files.** Never modify the model file the user picks. Working copies
are created in the same folder: "<name> - AP.edb" (collapse) and
"<name> - baseline.edb" (strength only). All app data for the project
(scenarios, conditions, review, results, propagation, finalize, tonnage, report)
goes in the project's "<name> - quikcolaps" folder. The working model's name is
passed explicitly to every bridge command.

**Steps** (a step bar across the top; each step unlocks the next; live log at
the bottom; a per-step "use cached results" fallback):

0. Open model + Check model: a read-only readiness check (deck floors with one
   area per bay; CS1 present with initial case 1.2D+0.5L, removing one column and
   loading one group; load pattern types recognised; auto-select lists on
   columns and girders; ETABS version) shown as pass / warning / fail with a
   one-line explanation each. Bridge command for it if needed.
1. Load model: export, intact axial loads, rule-based scenarios. The building in
   3D with the UFC locations and stories.
2. Claude review: condition table + review. Decisions with reasons and cited
   values; suggested additions highlighted in 3D; the user approves the
   scenario set.
3. Write to ETABS: cases, load groups and combos; counts written and verified.
4. Run + design: the load check per scenario (pass/fail) and the first results.
5. Redesign rounds: iterate; weight per round as a small chart and members
   changed per round.
6. Copy to similar & finalize: propagation list in 3D (originals vs copies) → the
   user approves → assign-sections → finalize loop; the rounds, members stepped
   up, and status (passed / not converged).
7. Tonnage & report: compute the baseline on the baseline copy if missing
   (strength combos only, iterate); show the premium. The report itself comes
   later (item E); placeholder.

**3D view modes** (a switch in the viewer):

1. What changed: members colored by reason (collapse-driven red, propagated
   purple, strength blue, unchanged grey), line width by weight increase.
2. Ratio: green → yellow → red by worst ratio across all scenarios, with a
   toggle for original vs final design.
3. Scenario heat map: for the selected scenario, every member colored by its
   ratio under that scenario's combo, with the removed column and amplified
   region shown. ETABS only reports each member's governing ratio, so
   per-scenario ratios come from the cheapest source (database tables first;
   otherwise a cached batch of one design per scenario), as a bridge command.
4. Added weight: greyscale by added steel per member ((final − original weight
   per length) × length), light grey = none, black = most, with a colour bar in
   real units and a per-story bar chart.
5. Before / after sizes toggle.

**Interaction:** clicking a member shows original → final section, ratio,
governing scenario and reason (collapse / propagated / strength / finalize
step-up).

**Results panel:** baseline vs final tonnage bar with the premium in large text;
the split (collapse-driven / propagated / strength) as a stacked bar; the
finalize summary; open notes (SC07, simplifications: m = 1, amplification 2.0,
conservative deck load at shared edges, similarity copied to all group
locations, gravity strength only).

**Filters:** story slider, scenario list, symmetry group. Legend always visible.

**Rules:** no changes to the engine logic in `ap/core`, `ap/claude_client` or the
bridge beyond adding the commands this item needs; new commands go in the
command list. The demo project's existing results stay intact.

Before the plan (done 2026-09-26): Claude review with the condition table,
C5 approved, 30 scenarios applied, run and designed on AP2 (status above).

## Commands

Every command with its arguments, updated as commands are added. From the repo
root unless marked `ap/` (run those from `ap/`). Anything that writes to ETABS
needs the user's approval; pass the working copy with `--model "progressive collapse - AP2"`.

| Step | Command |
|---|---|
| export | `dotnet run --project tools/Quikcolaps.Bridge -- export --model "progressive collapse - AP2" --out ap/web/data/building.json` |
| intact axial | `dotnet run --project tools/Quikcolaps.Bridge -- axial --model "progressive collapse - AP2" --case "1.2D+0.5L" --out ap/web/data/intact_axial.json` (read-only) |
| rule candidates, scenarios | `ap/`: `python -m core.cli web/data/building.json --out web/data/scenarios.json [--candidates web/data/approved_candidates.json] [--stacks web/data/stacks.json]` |
| open model | `dotnet run --project tools/Quikcolaps.Bridge -- open --model "<open model>" --file "<path>.EDB"` (closes the open model unsaved) |
| design selection | `dotnet run --project tools/Quikcolaps.Bridge -- design-select --model "baseline strength" --combos DStlS1,DStlS2 [--commit]` |
| design iteration | `dotnet run --project tools/Quikcolaps.Bridge -- iterate --model "baseline strength" --cases SW,SDL,LL --max-rounds 3 --out ap/web/data/baseline_rounds.json [--commit --accept-design-sections]`; AP2: `--model "progressive collapse - AP2" --cases SW,SDL,LL,1.2D+0.5L,AP_SC01,…,AP_SC30 --max-rounds 3 --weight-tol 0.005 --out ap/web/data/ap2_rounds.json` |
| tonnage | `dotnet run --project tools/Quikcolaps.Cli -- weigh --model "baseline strength" --label baseline_strength` (→ `takeoffs/baseline_strength.csv`; summary in `ap/web/data/baseline_tonnage.json`) |
| finalize | `ap/`: `python scripts/finalize.py --model "progressive collapse - AP2" [--max-rounds 5] [--data <project data folder>] [--label collapse_final]` (run all AP cases → design → members over 1.0 back on auto-select → run + design → ETABS's pick, or one size up, on them and their symmetry images → assign-sections → repeat; → `web/data/finalize.json`, weigh, `collapse_tonnage.json`) |
| delete unused FIN_* lists | `dotnet run --project tools/Quikcolaps.Bridge -- autoselect --cleanup --model "progressive collapse - AP2" [--commit]` (finalize runs it before every check) |
| auto-select again | `dotnet run --project tools/Quikcolaps.Bridge -- autoselect --model "progressive collapse - AP2" --frames 9,422 [--commit]` |
| step up failing members | `ap/`: `python -m core.stepup --frames 9,29 [--current web/data/building_final.json] [--propagation web/data/propagation.json]` (next heavier W14 on each and its symmetry images; refreshes every `from` from the export) |
| re-export | `dotnet run --project tools/Quikcolaps.Bridge -- export --model "progressive collapse - AP2" --out ap/web/data/building_current.json` (read-only) |
| propagation | `ap/`: `python -m core.propagate [--building web/data/building_current.json] [--original <building with original sections>] [--results web/data/results.json] [--scenarios web/data/scenarios.json] [--conditions web/data/conditions.json] [--out web/data/propagation.json]` |
| condition table | `ap/`: `python -m core.conditions web/data/building.json --axial web/data/intact_axial.json --out web/data/conditions.json` |
| Claude review | `ap/`: `python -m claude_client.run_review --mode raw\|conditions [--out web/data/review_<mode>.json]` (costs money) |
| compare reviews | `ap/`: `python -m claude_client.run_review --compare web/data/review_raw.json web/data/review_conditions.json` |
| stacks | `dotnet run --project tools/Quikcolaps.Bridge -- stacks --model "progressive collapse - AP2" --scenarios ap/web/data/scenarios.json --out ap/web/data/stacks.json` |
| apply | `dotnet run --project tools/Quikcolaps.Bridge -- apply --model "progressive collapse - AP2" --scenarios ap/web/data/scenarios.json [--template CS1] [--commit]` (`--commit` unlocks a locked model first) |
| assign sections | `dotnet run --project tools/Quikcolaps.Bridge -- assign-sections --model "progressive collapse - AP2" --file ap/web/data/propagation.json [--commit]` |
| section check | `dotnet run --project tools/Quikcolaps.Bridge -- sections --model "progressive collapse - AP2"` (exit 4 when design ≠ analysis) |
| run | `dotnet run --project tools/Quikcolaps.Bridge -- results --model "progressive collapse - AP2" --scenarios ap/web/data/scenarios.json --out <file> --run [--accept-design-sections]` (lean flags set before, restored after: scratch `flags set/restore` today) |
| design | `dotnet run --project tools/Quikcolaps.Bridge -- results --model "progressive collapse - AP2" --scenarios ap/web/data/scenarios.json --out ap/web/data/results.json --design` (composite first, then steel) |
| forces | `dotnet run --project tools/Quikcolaps.Bridge -- forces --model "progressive collapse - AP2" --case AP_SC01 --frames 101,102 --out forces.json` |
| tests | `ap/`: `pytest` |
| viewer | `ap/`: `python -m http.server 8000`, open `http://localhost:8000/web/` |
| report | `ap/`: `python -m report.build_report web/data/scenarios.json --out report.md` |

Python wrapper: `ap/`: `python scripts/bridge.py export|stacks|apply|results|forces|axial|assign-sections [...]`.

Lean run flags are in `iterate`; `results --run` still needs them set by hand (scratch `flags set/restore`). Not yet a bridge command: lean flags for `results --run` (`Analyze.SetRunCaseFlag`,
saved and restored), design-section reset (`DesignSteel.SetDesignSection(f, "",
true)`: design section → analysis section; analysis section and auto-select
list unchanged, measured on frame 78 and 399 more).
