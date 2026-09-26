# tools/Quikcolaps.Bridge

JSON bridge between ETABS and the Python side (`ap/`). Builds on the existing
`src/Quikcolaps.Etabs` library; nothing in that library or in the other tools
is modified. Windows, ETABS running, x64.

```
dotnet run --project tools/Quikcolaps.Bridge -- export  --out ap/web/data/building.json
dotnet run --project tools/Quikcolaps.Bridge -- stacks  --scenarios ap/web/data/scenarios.json --out ap/web/data/stacks.json
dotnet run --project tools/Quikcolaps.Bridge -- apply   --scenarios ap/web/data/scenarios.json            # dry run
dotnet run --project tools/Quikcolaps.Bridge -- apply   --scenarios ap/web/data/scenarios.json --commit
dotnet run --project tools/Quikcolaps.Bridge -- results --scenarios ap/web/data/scenarios.json --out ap/web/data/results.json --run --design
dotnet run --project tools/Quikcolaps.Bridge -- forces  --case AP_SC01 --frames 101,102,103 --out forces_staged.json
```
Common flags: `--model` (default `progressive collapse`), `--template` (default `CS1`),
`--plan-tolerance` (model length units, default 1.0).

## Status: written, not yet compiled

This project was written without ETABS or the .NET SDK available. Expect to fix
compile errors on first build. Every API call not already used by
`src/Quikcolaps.Etabs` is marked `VERIFY` in a comment: check each one against
the CSI API help file for the installed ETABS version (argument order, `ref`
vs value, enum values) before trusting its output, and record what you find
below. Never guess a signature.

## Contract

| Command | Reads | Writes | Model changes |
|---|---|---|---|
| `export` | open model | `building.json` (ap/docs/schema/building.schema.json), kN/m | none (units restored) |
| `stacks` | `scenarios.json` | `stacks.json` | none |
| `apply` | `scenarios.json`, template case | — | with `--commit`: cases, load groups, combos, steel selection |
| `results` | `scenarios.json`, template case | `results.json` (ap/docs/schema/results.schema.json) | `--run` analyses, `--design` designs |
| `forces` | one case | `forces.json` | none |

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

## API notes (measured)

The existing notes in the root README still apply (`GroupDef.Clear` answers −99,
`GetStageData_2` stage by reference, operation codes 2 = remove, 4 = load,
object types 2 = frame, 5 = area). Add new ones here:

- `Story.GetStories_2`: ...
- `AreaObj.GetPoints`: ...
- `AreaObj.GetLoadUniform` direction codes: ...
- `FrameObj.GetLoadDistributed`: ...
- `PropArea.GetSlab` / decks: ...
- `Results.Setup.SetOptionNLStatic` / `SetOptionMultiStepStatic` for staged cases: ...
- `Analyze.GetCaseStatus` codes: ...
