# Team setup

## Getting the branch

The AP work lives on its own branch and only adds files: `ap/`,
`tools/Quikcolaps.Bridge/` and a root `CLAUDE.md`. Nothing that already
existed is changed.

```
git checkout main && git pull
git checkout -b ap-pipeline            # first person only; others: git checkout ap-pipeline
# unzip the starter files at the repo root, then
git add CLAUDE.md ap tools/Quikcolaps.Bridge
git commit -m "AP pipeline: Python rules, viewer, Claude review; ETABS JSON bridge"
git push -u origin ap-pipeline
```

Optional: `dotnet sln add tools/Quikcolaps.Bridge/Quikcolaps.Bridge.csproj` so
`dotnet build` at the root builds the bridge too. This edits `QUIKCOLAPS.sln`;
skip it to keep the existing files untouched (use `dotnet run --project`).

## Everyone

1. Install Claude Code (https://code.claude.com/docs/en/quickstart). On Windows
   install Git for Windows first. Check with `claude --version`.
2. Python side:
   ```
   cd ap
   python -m venv .venv
   .venv\Scripts\activate            # Windows   (source .venv/bin/activate elsewhere)
   pip install -e ".[dev]"
   pytest
   python -m core.cli fixtures/demo_building.json
   python -m http.server 8000        # open http://localhost:8000/web/
   ```
3. Start Claude Code at the repo root (`claude`). It reads the root `CLAUDE.md`
   and the `CLAUDE.md` of the folder you work in.

## Roles

| Person | Area | Needs ETABS? | First task |
|---|---|---|---|
| A (knows the C# code) | `tools/Quikcolaps.Bridge` | Yes | Build it, fix compile errors, verify the `VERIFY` calls, then the staged-case validation |
| B | `ap/core` | No, then the real export | Rules against `ap/docs/ufc_notes.md`; then run on A's first `export` |
| C | `ap/web` | No | Results view from a mock `results.json` |
| D | `ap/claude_client`, `ap/report` | No, needs `ANTHROPIC_API_KEY` | Run the review call on the fixture; redesign-summary call |

## How we work

- Branch off `ap-pipeline` per task, small pull requests into `ap-pipeline`.
- Don't edit `src/`, `tools/Quikcolaps.Cli`, `tools/Quikcolaps.Probe` or root
  files on this branch (D14). If something there needs to change, agree it
  with its author and do it in a separate pull request to `main`.
- Ask Claude to plan before editing; review engineering changes against
  `ap/docs/ufc_notes.md`.
- Every rule gets a hand-checked test in `ap/tests/`.
- ETABS API facts go into `tools/Quikcolaps.Bridge/CLAUDE.md` as they're measured.
- New decisions go in `ap/docs/decisions.md`.

## End-to-end on the real model (Windows, ETABS open)

```
cd ap
python scripts/bridge.py export                      # -> web/data/building.json
python -m core.cli web/data/building.json            # -> web/data/scenarios.json
python scripts/bridge.py stacks                      # -> web/data/stacks.json
python -m core.cli web/data/building.json --stacks web/data/stacks.json
# review in the viewer, Export approvals, then
python -m core.cli web/data/building.json --stacks web/data/stacks.json --candidates approved_candidates.json
python scripts/bridge.py apply                       # dry run, then add --commit
python scripts/bridge.py results --run --design      # -> web/data/results.json
python -m report.build_report web/data/scenarios.json --results web/data/results.json --out report.md
```
