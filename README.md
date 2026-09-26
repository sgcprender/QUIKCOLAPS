# QUIKCOLAPS

Progressive collapse case setup in ETABS: one staged-construction case per column to be removed.

For each column in the removal group, a case is written that
- starts from the template case's initial case (the loaded structure),
- removes the column, and
- loads a group of floor areas with the template's load operations and factors.

The group is the column's **influence area**: the floor areas on the column's top joint, plus the
floor areas on the top joint of every column standing directly above it, up to the last column in
the stack.

## Method

- **Stack.** A column above shares its bottom joint with the top joint of the column below. From
  each top joint, `PointObj.GetConnectivity` lists what is on it; the column whose lower end is that
  joint, and whose upper end is within the plan tolerance of it, is the next one up. The walk
  stops where there is none. `GetCommonTo` only counts the objects on a joint and does not name them.
- **Floors.** Areas on each top joint whose design orientation is Floor. Walls are left out.
- **Template.** The example case is read in full (stages, operations, nonlinear settings) and copied.
  Only its removed frame and its loaded group change. The new group copies the template group's
  flags, so it is usable as a staged-construction group.
- **Combination.** Each case is wrapped in its own linear additive combination, 1.0 × the case,
  named `<case>_CMB`, and selected for steel strength design.
- **Verify.** Group membership and every stage operation are read back and compared after writing.
  A zero return code alone does not mean the program kept what was sent.

## Use

```bash
dotnet build
dotnet run --project tools/Quikcolaps.Cli                          # dry run: prints every stack and influence area
dotnet run --project tools/Quikcolaps.Cli -- --only CS_C6_Story1 --commit   # write one
dotnet run --project tools/Quikcolaps.Cli -- --commit              # write all cases, groups and combos
dotnet run --project tools/Quikcolaps.Cli -- --combos-only --commit # write only the combos, over existing cases
dotnet run --project tools/Quikcolaps.Probe -- --group COLS_REMOVED --columns 3   # read-only survey
```

### Adding a load to the whole set

```bash
dotnet run --project tools/Quikcolaps.Cli -- add-load --pattern SDL --scale 1.2 --commit
```

Puts the pattern into the template's initial case and into the template's influence-area loads,
then rebuilds every collapse case from the template. Setting a pattern that is already there changes
its factor rather than adding it twice. Combinations and the steel design selection are left alone.

### Steel takeoff

```bash
dotnet run --project tools/Quikcolaps.Cli -- weigh --label collapse   # read-only; saves takeoffs/collapse.csv
dotnet run --project tools/Quikcolaps.Cli -- weigh --label strength
dotnet run --project tools/Quikcolaps.Cli -- compare collapse strength
```

Each frame is weighed as its length × the weight per foot of its section. The section is the steel
designer's, else the composite beam designer's, else the analysis section; the source is on every
row of the CSV. Weight per foot is the nominal value in the AISC shape name (W14X90 is 90 lb/ft),
or area × material unit weight for a section without one. Tons are short tons (2000 lb).
```bash
dotnet run --project tools/Quikcolaps.Cli -- design-combos strength --commit       # DStlS* only
dotnet run --project tools/Quikcolaps.Cli -- design-combos collapse --commit       # DStlS* + collapse
dotnet run --project tools/Quikcolaps.Cli -- design-combos collapseonly --commit   # collapse only
```

`design-combos` sets the steel strength selection. A collapse combination is one whose every case
is a staged-construction case; a strength combination is one named with `--strength-prefix`
(default `DStlS`). Without `--commit` it lists the changes and makes none. Re-run steel design
before weighing.

`compare a b` gives the column, beam and total difference, then the weight `b` adds to `a` frame by
frame — Σ max(0, b − a), which is the envelope of both designs less `a` — and lists the frames sized
differently. For what progressive collapse adds, `compare strength collapseonly`: a frame the
collapse design sizes lighter is still built at its strength section, so it adds nothing rather than
offsetting one that gets heavier.

| flag | default | |
|---|---|---|
| `--model` | `progressive collapse` | matched against the open models' filenames |
| `--group` | `COLS_REMOVED` | columns to remove |
| `--template` | `CS1` | the example staged case |
| `--plan-tolerance` | `1.0` | plan offset, in the model's present length unit, that still counts as directly above |
| `--only` | | one case name or frame name |
| `--combos-only` | off | write the combinations without rewriting the cases |
| `--commit` | off | without it nothing in the model changes |

Cases are named `CS_<label>_<story>`. The group name is the template group's name with the
template case name replaced. Re-running rewrites existing cases and groups in full. The model is
never saved.

## ETABS API notes, measured

- `GroupDef.Clear` answers `-99` (not implemented), so an existing group is emptied member by member.
- `DesignSteel.GetComboAutoGenerate` answers `-99`; `GetComboStrength` answers and reads back.
- `GetStageData_2` takes the stage number by reference and `SetStageData_2` by value.
- Operation codes: `2` removes structure, `4` loads objects. Object type codes from connectivity:
  `2` frame, `5` area.

Connection code (`Attach`, `Csi.props`) follows Oryx's CSI adapter, so moving onto Oryx later is a
reference swap.
