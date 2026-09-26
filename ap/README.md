# ap: Alternate Path pipeline

Progressive collapse Alternate Path check (UFC 4-023-03, 2009 Change 4) built
around the existing QUIKCOLAPS ETABS tools:

ETABS model → `bridge export` → removal scenarios (rules + ETABS stacks +
Claude review) → approval in a 3D viewer → `bridge apply` (staged cases from
the CS1 template) → `bridge results` (reaction check, steel ratios) → redesign
→ report with the tonnage premium from `quikcolaps weigh`/`compare`.

- Scope, flow and status: `docs/scope_and_flow.md`
- Team setup and branch: `docs/team_setup.md`
- C# bridge: `../tools/Quikcolaps.Bridge/CLAUDE.md`

Quick start without ETABS:
```
pip install -e ".[dev]" && pytest
python -m core.cli fixtures/demo_building.json
python -m http.server 8000     # open http://localhost:8000/web/
```
