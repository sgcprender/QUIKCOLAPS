# core/

Deterministic engineering rules. No ETABS, no network, no LLM calls here.

- `model.py`: loading the building JSON and config, lookups
- `geometry.py`: 2D plan helpers (point on segment/boundary, convexity, area)
- `stories.py`: which stories to analyze per location (UFC 3-2.9.2.2)
- `candidates.py`: rule-based removal locations and difficult-geometry flags
- `regions.py`: 30% simultaneous removal, amplified region, region from approved bays
- `loads.py`: increment load spec for one scenario
- `scenarios.py`: candidates → scenarios
- `cli.py`: building JSON → web/data/scenarios.json

Rules for changes here:
- Every rule change needs a hand-calculated test in `tests/test_core.py`, with
  the arithmetic in a comment.
- Cite the UFC clause in the docstring of any function implementing a clause.
- Tie-breaks must be deterministic (same input → same scenarios, same order).
- Load math: increment = (amplification_factor − 1) × base combination on the
  region. Keep `region_amplified_total_kn == amplification_factor × region_base_total_kn`.
- Known limitations (good next tasks): outline taken from the first above-grade
  level only; bay-size change only checked along the outline; no internal removals.
