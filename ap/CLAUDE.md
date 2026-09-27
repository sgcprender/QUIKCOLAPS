# ap/ (Python side of the Alternate Path pipeline)

Automates the progressive collapse Alternate Path check of a steel frame per
UFC 4-023-03 (2009, Change 4). Python owns the rules, Claude calls, viewer and
report; the C# bridge (`../tools/Quikcolaps.Bridge`) owns everything that
touches ETABS. They exchange JSON (`docs/schema/`).

Read before changing engineering logic:
- `docs/scope_and_flow.md`: scope, 13-step flow, build order, status
- `docs/ufc_notes.md`: the clauses we implement
- `docs/decisions.md`: why things are the way they are (D12–D16 cover the bridge)

## Hard rules

- Geometry, story selection, regions and loads are deterministic code in
  `core/`. LLM output never sets loads, capacities or story selection.
- Claude's output always goes through `claude_client/validate.py` and user
  approval before it affects a scenario.
- AP combinations have no wind; live load is not reduced.
- Numbers from the code come from `config/config.toml`, except load factors:
  an ETABS export carries its initial case as `combination` and those win (D17).
- SI (kN, m, kPa) everywhere here; the bridge converts.
- Mandatory candidates (corner, mid long side, mid short side) can't be dropped.
- Names: case `AP_SCnn`, group `AP_SCnn_LOAD`, combo `AP_SCnn_CMB` (D16).
- When `stacks.json` exists, ETABS influence areas define regions (D12).

## Modules

| Module | Owns | Reads | Writes |
|---|---|---|---|
| `core/` | candidates, stories, 30% rule, regions, increment totals, condition table | building, stacks, approvals, intact_axial | scenarios, web/data/building, conditions |
| `claude_client/` | Claude calls + validation | building, candidates, conditions | review_<mode>.json |
| `server/` | demo app (FastAPI): projects, steps, jobs, viewer data | project folders | project folders, projects.json |
| `web/` | viewer (`index.html`), demo app front end (`app/`) | web/data/*.json, server API | approved_candidates.json |
| `report/` | submittal report | scenarios, results | report.md |
| `scripts/` | fixture generator, bridge wrapper, force comparison | | |

## Commands (run from ap/)

- Tests: `pytest` (before every commit)
- Scenarios: `python -m core.cli <building.json> [--stacks stacks.json] [--candidates approved.json]`
- Demo app: `python -m server` (opens http://127.0.0.1:8765/); register the AP2 work once with `python -m server.demo`
- Viewer: `python -m http.server 8000`, open `http://localhost:8000/web/`
- Bridge: `python scripts/bridge.py export|stacks|apply|results [...]` (Windows + ETABS)
- Report: `python -m report.build_report web/data/scenarios.json --out report.md`
- Condition table: `python -m core.conditions web/data/building.json --axial web/data/intact_axial.json`
- Propagation: `python -m core.propagate` → `web/data/propagation.json` (no ETABS)
- Finalize (ETABS): `python scripts/finalize.py --model "progressive collapse - AP2"` → `web/data/finalize.json`
- Claude review: `python -m claude_client.run_review --mode raw|conditions` (costs money; ask first)

## Lessons learned

(Add a line whenever Claude repeats a mistake.)
