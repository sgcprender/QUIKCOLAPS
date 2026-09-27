# web/

Two front ends: `app/` is the demo app (plan item F), served by `python -m server`
from `ap/` (FastAPI, `ap/server`); `index.html` below is the original static viewer.

`app/`: `index.html` + `app.css` + `app.js` (landing page, steps, results, log) +
`viewer.js` (three.js; one InstancedMesh for all members; picking by the nearest member
axis to the ray, since members are a pixel wide at full view). Member rows come from
`/api/projects/<id>/viewer` (ap/server/viewer.py); the viewer does no engineering.

Views (`MODES` in viewer.js) are enabled only when their files exist (`available()` in app.js),
and clicking a step opens its view: 0 model, 1–2 UFC locations, 3 influence area, 4 ratio (first
design), 5 ratio (latest), 6 what changed, 7 added weight. The user can switch freely afterwards;
reloads after a job keep the view, scenario and story range. The story/group filter hides members
(a faint wireframe of the whole frame stays). Step and results panels render with a token, so an
older, slower render never overwrites a newer one.


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
