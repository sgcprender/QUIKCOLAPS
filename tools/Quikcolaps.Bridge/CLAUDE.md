# tools/Quikcolaps.Bridge

JSON bridge between ETABS and the Python side (`ap/`). Builds on the existing
`src/Quikcolaps.Etabs` library; nothing in that library or in the other tools
is modified. Windows, ETABS running, x64.

```
dotnet run --project tools/Quikcolaps.Bridge -- export  --model "progressive collapse - AP" --out ap/fixtures/etabs_building.json
dotnet run --project tools/Quikcolaps.Bridge -- stacks  --scenarios ap/web/data/scenarios.json --out ap/web/data/stacks.json
dotnet run --project tools/Quikcolaps.Bridge -- apply   --scenarios ap/web/data/scenarios.json            # dry run
dotnet run --project tools/Quikcolaps.Bridge -- apply   --scenarios ap/web/data/scenarios.json --commit
dotnet run --project tools/Quikcolaps.Bridge -- results --scenarios ap/web/data/scenarios.json --out ap/web/data/results.json --run --design
dotnet run --project tools/Quikcolaps.Bridge -- forces  --case AP_SC01 --frames 101,102,103 --out forces_staged.json
dotnet run --project tools/Quikcolaps.Bridge -- sections                                  # analysis vs design sections
dotnet run --project tools/Quikcolaps.Bridge -- axial   --case "1.2D+0.5L" --out ap/web/data/intact_axial.json
dotnet run --project tools/Quikcolaps.Bridge -- assign-sections --file ap/web/data/propagation.json            # dry run
dotnet run --project tools/Quikcolaps.Bridge -- assign-sections --file ap/web/data/propagation.json --commit
dotnet run --project tools/Quikcolaps.Bridge -- open    --file "<path>.EDB"                 # switch model (never saves)
dotnet run --project tools/Quikcolaps.Bridge -- design-select --combos DStlS1,DStlS2 [--commit]
dotnet run --project tools/Quikcolaps.Bridge -- iterate --cases SW,SDL,LL --max-rounds 3 --out rounds.json [--commit]
```
Common flags: `--model` (default `progressive collapse`), `--template` (default `CS1`),
`--plan-tolerance` (model length units, default 1.0). `--model` matches the
filename stem by substring and refuses more than one hit: pass the working copy
`progressive collapse - AP` in full. Never run or save the original.

## Status: compiles, signatures checked; export measured against base reactions

Builds against the ETABS 23 `CSiAPIv1.dll` (2026-09-26). `ColumnStack.Check` is
internal to the library, so the bridge has its own copy, `Api.Check`. Every
call not already used by `src/Quikcolaps.Etabs` has been checked against
`ETABS 23\CSI API ETABS v1.chm` for argument order, `ref` vs value, and codes.
The compiler proves counts, types and `ref`, but not the order of arguments
that share a type or what a code means. No signature needed changing. The
`VERIFY` comments stay until each call has been measured on a live model
(see "to measure" below). Never guess a signature.

`export` checked on the working copy (2026-09-26), SW, SDL and LL run alone,
total from `building.json` against ETABS base reaction FZ:

| Pattern | building.json | ETABS | Diff |
|---|---|---|---|
| SW | beams 5,752.6 + columns 1,164.5 + deck 34,866.8 = 41,783.9 kN | 41,640.7 kN | +0.34% |
| SDL | 4.788 kPa × 11,237.8 m² = 53,806.8 kN | 53,806.8 kN | 0.00% |
| LL | 4.788 kPa × 11,237.8 m² = 53,806.8 kN | 53,806.8 kN | 0.00% |

## Resolved: composite design reset the steel design sections

Symptom (AP2, 2026-09-26): column 165 under `AP_SC02_CMB` (P = 3,914 kN,
M3 = 433 kN·m, more than a W14X61 can carry) was reported as W14X61 at ratio
0.903, and no auto-select frame changed size.
Cause (measured, two-step test): design did use the final staged forces
("Design Forces - Columns" shows them) and auto-selected W14X145, which the
ratio fits (P part 0.49 = 880 kips / φPn 1,798 kips). Then
`DesignCompositeBeam.StartDesign` **reset every steel frame's design section to
its analysis section and left the steel ratios**: after steel design 165 read
W14X145 and `DesignSteel.VerifySections` listed 400 frames; after composite
design 165 read W14X61 and it listed 0. The "Multi-Response Case Design"
preference was never the problem.
Fix: `results --design` runs composite design first, then steel design. Checked:
165 reads W14X61 → W14X145 at 0.903, `VerifySections` 400, composite results
still available (420, sections match).

## Contract

| Command | Reads | Writes | Model changes |
|---|---|---|---|
| `export` | open model, template's initial case | `building.json` (ap/docs/schema/building.schema.json), kN/m, with `combination` (D17) | none (units restored) |
| `stacks` | `scenarios.json` | `stacks.json` | none |
| `apply` | `scenarios.json`, template case | — | with `--commit`: unlocks a locked model first (read-back; deletes results), then cases, load groups, combos, steel selection |
| `results` | `scenarios.json`, template case | `results.json` (ap/docs/schema/results.schema.json) | `--run` analyses, `--design` designs |
| `forces` | one case | `forces.json` | none |
| `sections` | auto-select frames | — | none; exit 4 if any design section differs from the analysis section |
| `axial` | one run case | `intact_axial.json`: every column's max \|P\| at the last step, with label and story, plus the lowest-columns sum against the base reaction FZ | none |
| `assign-sections` | `propagation.json` (`assignments`: frame, section, optional `from`) | — | with `--commit`: unlocks, then fixed analysis sections (auto-select list removed), each read back; refuses the whole file if a frame, section or `from` doesn't match |

| `open` | a model file | — | opens it in the running ETABS; the previous model is closed unsaved (bridge never saves) |
| `design-select` | combos | — | with `--commit`: steel and composite strength selection = exactly these, read back |
| `iterate` | cases, design selection | `rounds.json` | with `--commit`: lean run → composite → steel design, repeated until no auto-select frame would change or `--max-rounds`; flags restored |

Every command exits non-zero with a message on failure: 1 error, 2 usage,
3 unknown ETABS message box, 4 sections differ (`results --run`, `sections`),
5 `iterate` not converged within `--max-rounds`.
Unlocking is shared (`ModelLock`): nothing when unlocked, a message on a dry
run, unlock + read-back with `--commit`. Tested 2026-09-26 on locked AP2 with
dry runs only (lock and results kept); the unlock itself first runs at the
start of plan item D. `assign-sections --commit` is untested: whether
`FrameObj.SetSection` clears the auto-select list is not documented, and the
read-back will say.

`results --run` checks sections first and stops with exit 4 (nothing run) if
an auto-select frame's design section differs from its analysis section: the
run would adopt the design sections. `--accept-design-sections` runs anyway,
as a deliberate redesign iteration.

Names: case `AP_SCnn`, load group `AP_SCnn_LOAD`, combo `AP_SCnn_CMB` (the
existing tool's `<case>_CMB` convention).

## The template case (built by hand, once)

`CS1` must: start from an initial case carrying 1.2D + (0.5L or 0.2S) on the
whole building (no wind); remove exactly one column; load exactly one group
with the same patterns at factor 1.0 (the increment, amplification − 1).
`results` checks this: reaction(case) − reaction(initial case) must equal the
scenario's `increment_total_kn` within 1%.

## First task: validate the single-model approach

1. `apply --commit` one scenario, run it, then
   `forces --case AP_SC01 --frames <beams over the removed column> --out staged.json`.
2. In a copy of the model, delete the same column(s) by hand, define a linear
   static case with the same total loading (initial combination everywhere +
   increment on the load group), run, and `forces` the same frames into `deleted.json`.
3. `python ap/scripts/compare_forces.py staged.json deleted.json` → expect < 1% difference.
   Record the result in `ap/docs/decisions.md` (D5).

## API notes

The existing notes in the root README still apply (`GroupDef.Clear` answers −99,
`GetStageData_2` stage by reference, operation codes 2 = remove, 4 = load,
object types 2 = frame, 5 = area).

"Documented" means from the ETABS 23 API help (API 2.16); "measured" means
seen on the working copy, ETABS 23, 2026-09-26.

- `Analyze.RunAnalysis` (measured): **saves the model file** before running
  (the `.edb` write time changed) and leaves the model locked. The help only
  says the model needs a file path. Only ever run it on the working copy.
- `Analyze.GetRunCaseFlag` (documented): `(ref NumberItems, ref CaseName,
  ref Run)`; `SetRunCaseFlag(Name, Run, All = false)`. Measured: setting all
  false then three true reads back exactly; restoring the saved flags reads back.

- `Story.GetStories_2` (documented): `(ref BaseElevation, ref NumberStories,
  ref StoryNames, ref StoryElevations, ref StoryHeights, ref IsMasterStory,
  ref SimilarToStory, ref SpliceAbove, ref SpliceHeight, ref color)`; the
  bridge's order matches. Returns stories "for the current tower" only. To
  measure: whether `StoryElevations` is each story's top, as `Export.Stories`
  assumes.
- `AreaObj.GetPoints` (documented): `(Name, ref NumberPoints, ref Point[])`;
  matches.
- `AreaObj.GetLoadUniform` (documented): `(Name, ref NumberItems, ref AreaName,
  ref LoadPat, ref CSys, ref Dir, ref Value, ItemType)`; matches. `Value` is
  F/L². `Dir` codes: 1–3 are local 1/2/3 (CSys Local only); 4–6 are X/Y/Z in
  CSys; 7–9 are projected X/Y/Z; 10 is gravity and 11 is projected gravity
  (Global only). Positive gravity is −Z. `Export.Gravity` reads 10 and 11 as
  +down and 6 (Global only) as +up; any other direction, or 6 in another CSys,
  is flagged in `building.json` and not exported. Measured: every floor area
  has SDL and LL at 4.788 kPa (100 psf), dir 10, Global. Area names not in
  the model answer 1 (export reads the names from `GetNameList`).
  "Uniform to frame" loads are not returned by this call; `export` reads them
  with `AreaObj.GetLoadUniformToFrame` (documented: same arguments plus
  `ref int[] DistType`) into the same kinds. Measured: **−100 with 0 rows**
  on all 220 areas of this model (undocumented code; this model has no such
  loads, so read as "none"); any other non-zero code is flagged.
- `FrameObj.GetLoadDistributed` (documented): `(Name, ref NumberItems,
  ref FrameName, ref LoadPat, ref MyType, ref CSys, ref Dir, ref RD1, ref RD2,
  ref Dist1, ref Dist2, ref Val1, ref Val2, ItemType)`; matches. `MyType` is
  1 for force/length and 2 for moment/length. `Dir` codes are the same as for
  area loads. `RD1` and `RD2` are undocumented in the ETABS help (taken as
  relative distances 0–1 from the I end), so `FrameLineLoads` spreads each
  load's mean value over the whole beam: w × (RD2 − RD1). Moment loads
  (`MyType` 2) and non-gravity directions are flagged. This model has none.
  Beam self-weight is not a load here: it comes from section mass.
- `PropArea.GetSlab` (documented): `(Name, ref eSlabType, ref eShellType,
  ref MatProp, ref Thickness, ref color, ref notes, ref GUID)`; matches.
  `Thickness` is the membrane thickness and does not apply to Layered shells.
  For Ribbed or Waffle slabs it leaves out the ribs
  (`GetSlabRibbed`/`GetSlabWaffle`); `export` flags those, and Layered shells.
  Measured: **answers 1 for a deck** (`Deck1`). `PropArea.GetTypeOAPI` answers
  1 = Shell for a deck too, so it cannot tell them apart.
- `PropArea.GetDeck_1` (documented): `(Name, ref eDeckType, ref SlabFillMatProp,
  ref DeckMatProp, ref SlabDepth, ref RibDepth, ref RibWidthTop, ref RibWidthBot,
  ref RibSpacing, ref DeckShearThickness, ref DeckUnitWeight, ref ShearStudDia,
  ref ShearStudHs, ref ShearStudFu, ref color, ref notes, ref GUID)`.
  `DeckUnitWeight` has no documented unit; measured F/L² (0.1101 kPa = 2.3 psf
  for `Deck1`). `Deck1`: Filled, 4000Psi fill (23.563 kN/m³), tc 88.9 mm,
  hr 76.2 mm, ribs 177.8/127.0 mm at 304.8 mm. Filled deck weight per area =
  γ_fill × (tc + hr × (wrt + wrb) / 2 / sr) + DeckUnitWeight = 2.9925 + 0.1101
  = 3.1026 kPa; the SW base reaction implies 3.0901 kPa (0.4%), so ETABS
  weighs decks this way (the SW check above). Unfilled = DeckUnitWeight;
  SolidSlab = γ_fill × tc (not measured). `slab_sw_kpa` is exported without
  the self-weight multiplier; `combination.factors.self_weight` carries it.
- `PropMaterial.GetWeightAndMass` (documented): `(Name, ref W, ref M,
  Temp = 0)`; W is F/L³, so kN/m³ under `Si.With`.
- `PropFrame.GetSectProps` (documented): `Area` is the first of 12 `ref double`
  (Area, As2, As3, Torsion, I22, I33, S22, S33, Z22, Z33, R22, R33); matches.
- `PointObj.GetRestraint` (documented): `bool[6]` = U1, U2, U3, R1, R2, R3.
- `Results.BaseReact` (documented): FX, FY, FZ, MX, MY, MZ, then GX, GY, GZ
  (the reporting point); matches. `Results.FrameForce` (documented): Obj,
  ObjSta, Elm, ElmSta, LoadCase, StepType, StepNum, P, V2, V3, T, M2, M3;
  matches.
- `CaseStaticNonlinearStaged.SetResultsSaved` (documented): `(Name,
  StagedSaveOption, StagedMinSteps = 1, StagedMinStepsTD = 1)`; matches, same
  as `CollapseCase`.
- `Results.Setup.SetOptionNLStatic` / `SetOptionMultiStepStatic` (not
  documented; **measured** on `AP_SC03` and `1.2D+0.5L`): 1 = envelope (two
  rows, StepType Max / Min), 2 = step by step (one row per saved step; blank
  StepType for `AP_SC03`), 3 = last step (one row, StepType "Single Value").
  Both setters answer 0. The model's own setting was 1; the bridge's 3 is
  right. A staged case built from CS1 saves only its final state, so all three
  give the same FZ and frame forces there.
- `SapModel.SetModelIsLocked(false)` (measured): **answers 1 but does unlock**
  (`GetModelIsLocked` reads False afterwards). Check the read-back, not the
  return code. Unlocking deletes the analysis results. On AP2 (2026-09-26,
  after a design pass) it answered 0, and **the steel design sections
  survived the unlock**: `sections` still listed 400 of 840 auto-select frames
  with a design section different from the analysis section, so
  `results --run` stopped (exit 4). Unlocking is not a reset of the design
  sections. `DesignSteel.SetDesignSection(Name, PropName, LastAnalysis,
  ItemType)` is documented, but the help does not say what `LastAnalysis` does:
  measure it before relying on it as the reset.
- `View.RefreshView` and `DesignSteel.StartDesign` (measured): on this machine
  ETABS raises a modal "Error initializing shader … 0x80070057" box and the API
  call waits behind it. Display only; the writes had been read back before
  it appeared. `apply` no longer calls `RefreshView`. `results` runs
  `RunAnalysis` and `StartDesign` inside `Watch.During`, which presses OK on
  boxes whose text starts with "Error initializing shader" (logged to stderr)
  and exits with code 3 on any other box, leaving it up. By hand:
  `quikcolaps dialogs --pid <pid>` lists boxes, `--close` answers them.
- `DesignSteel.GetSummaryResults_3` (measured): covers **steel frame design
  only** (840 of 1,260 frames here). The 420 infill beams have design procedure
  3 = composite beam (`FrameObj.GetDesignProcedure`: 0 program, 1 steel frame,
  2 concrete, 3 composite beam, 4 joist, 7 none, 13 composite column) and get
  no ratio from it. `PMMCombo` comes back **with a suffix**, e.g.
  `AP_SC03_CMB(C)`, so matching it to a combo name needs the suffix removed
  (`Results.ComboName` strips a trailing `(...)` before matching).
- Composite beam design (documented + measured): `DesignCompositeBeam`
  `SetComboStrength`/`GetComboStrength`/`StartDesign`/`GetSummaryResults`.
  The composite strength selection was empty on the original model and ETABS
  has no default composite combos (`RespCombo.AddDesignDefaultCombos` covers
  steel and concrete only), so `apply --commit` mirrors the whole steel
  strength selection (DStlS1, DStlS2 and every AP combo) into it and reads it
  back. `GetSummaryResults` names neither the frame nor the governing combo:
  `results` reads it one frame at a time (item type Objects) and reports the
  strength ratio only, max(StrPMRat, StrShrRat); the stud ratio and ETABS's
  overall ratio and pass/fail (which include deflection and construction
  stage) go in the status text. The conventional check this covers is gravity
  strength only (DStlS1, DStlS2).
- `File.OpenFile` (measured 2026-09-26, AP2 ↔ `baseline strength.EDB`): no
  question box either way; the model that was open is closed **without saving**.
  AP2 reopened locked with its analysis results (axial read identical) but **no
  design results** (`sections` 0 differing; the steel design sections were
  back to the analysis sections). Design again after reopening.
- `iterate` on the strength baseline (measured): 3 rounds of SW/SDL/LL + design
  moved 260 → 172 → 76 frames; the last 76 step between neighbouring W14
  sizes both ways, so it had not converged at 3 rounds.
- `Analyze.GetRunCaseFlag` (measured): after an analysis it no longer lists the
  internal `~LLRF` case, though the case and pattern are still defined.
- `DesignSteel.AISC360_16.GetPreference`/`SetPreference(Item, Value)`
  (measured): item 2 is "Multi-Response Case Design" (1 envelopes, 2 step by
  step, 3 last step, 4 envelopes all, 5 step by step all; AP2 has 5), item 3
  framing type (3 = OMF), item 4 seismic design category (4 = D), item 5
  importance factor. It can be set while the model is locked. The composite
  beam preferences have no multi-step setting.
- Auto-select lists (measured): all columns `AS-W14` (35 sections), all
  girders `AS-W24` (21 sections), start Median; infill beams fixed W24X55.
  `FrameObj.GetSection` gives the current analysis section and the list name;
  `StartDesign` picks design sections but leaves the analysis sections alone.
  **But the next `RunAnalysis` after a design replaces the analysis section of
  every auto-select frame whose design section differs** (measured: 31 of 54
  frames around SC03 changed, e.g. column 165 W14X61 → W14X120, and the saved
  working copy kept them). Running analysis after design is a redesign
  iteration, not a re-check; `SectionGuard` stops it unless asked for.
- `DesignSteel.GetDesignSection` / `DesignCompositeBeam.GetDesignSection`
  (measured, no design results yet): the steel call answers 0 and the
  analysis section for steel frame design members, 1 for others (composite
  beam 1051); the composite call answers 1. `GetResultsAvailable` is False
  for both.
- Staged "Load Objects" on a group, deck floors (measured on AP_SC03,
  2026-09-26): deck load reaches the group **only through its beams**, each
  taking its one-way tributary strip on both sides, deck area in the group or
  not. All 36 region beams: increment 4,699.6 kN (strip model 4,710.0); the 12
  shared-edge beams left out: 3,342.1 kN (strip model 3,348.7). Per-pattern
  split with 36 beams: SW +12.7%, SDL +16.5%, LL +16.3% over the region total.
  `core` now computes the increment this way (D13).
- Deck span direction (measured): every deck area on this model answers
  `AreaObj.GetLocalAxes` angle 90, not advanced, and the deck spans along
  global Y onto the X-direction infill beams, so the span is the area's local
  1 axis. The help does not document this; `export` writes the angle as
  `bays.deck_span_deg` for deck properties (`PropArea.GetDeck` answers 0) and
  flags advanced local axes.
- `LoadCases.StaticLinear.GetLoads` / `Results.BaseReact` on a linear case
  (measured): one row per case, FX = FY = 0 for gravity patterns.
- `StaticNonlinear.GetLoads` on `1.2D+0.5L` (measured, via `CaseLoads.Initial`):
  1.2 × SW + 0.5 × LL + 1.2 × SDL, all type `Load`; SW self-weight multiplier 1.
- `Analyze.GetCaseStatus` (documented): `(ref NumberItems, ref CaseName,
  ref Status)`. Status 1 = not run, 2 = could not start, 3 = not finished,
  4 = finished. This matches the comment in `Results.Run`.
