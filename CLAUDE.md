# QUIKCOLAPS

Progressive collapse tooling for ETABS. Two halves:

| Path | What | Language | Runs on |
|---|---|---|---|
| `src/Quikcolaps.Etabs/` | ETABS library: attach, column stacks, staged cases from a template, combos, takeoff | C# | Windows + ETABS |
| `tools/Quikcolaps.Cli/`, `tools/Quikcolaps.Probe/` | Existing command-line tools (see README.md) | C# | Windows + ETABS |
| `tools/Quikcolaps.Bridge/` | JSON bridge for the AP pipeline: export, stacks, apply, results, forces | C# | Windows + ETABS |
| `ap/` | AP pipeline: UFC rules, Claude review, 3D viewer, report | Python + JS | anywhere |

Read `ap/docs/scope_and_flow.md` first. The Python side has its own
`ap/CLAUDE.md`; the bridge has `tools/Quikcolaps.Bridge/CLAUDE.md`.

## Rules for this repository

- On the `ap-pipeline` branch, don't modify `src/`, `tools/Quikcolaps.Cli`,
  `tools/Quikcolaps.Probe`, `README.md`, `QUIKCOLAPS.sln` or the root props
  files. Add, don't edit (ap/docs/decisions.md D14).
- Never save the ETABS model from code. Commands write only with `--commit`,
  and every write is read back.
- Don't guess ETABS API signatures: check the CSI API help for the installed
  version, and record measured behaviour in the relevant CLAUDE.md.
- C# style follows the existing code: records, `ColumnStack.Check` on every
  return code, dry run by default.
- Build: `dotnet run --project tools/Quikcolaps.Bridge -- <command>`; the
  Python side: see `ap/CLAUDE.md`.
