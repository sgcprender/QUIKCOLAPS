# web/

Static single-page viewer: `index.html` (three.js from a CDN via import map).
Serve from the repo root (`python -m http.server 8000`) so it can fetch
`../fixtures/demo_building.json` and `data/scenarios.json`.

- Z is up (ETABS convention). Cameras set `up` accordingly.
- Every mesh keeps its ETABS object in `userData`; clicks map straight to ids.
- Colors are CSS variables in `:root`; the 3D scene reads them, so change them
  in one place.
- The viewer never computes engineering values. It displays what core/ and
  the C# bridge (tools/Quikcolaps.Bridge) produced and exports user decisions (approved_candidates.json).

Next tasks: results view (color members by `results.json` ratios, step 8),
redesign approval (step 10), before/after toggle (step 12), story filter.
