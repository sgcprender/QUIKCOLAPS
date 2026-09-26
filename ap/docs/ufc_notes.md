# UFC 4-023-03 notes (2009, Change 4)

The rules this tool implements, in our own words, with clause numbers. This file
is also sent to Claude as reference in the candidate review call, so keep it
accurate and short. The full document is in `docs/reference/`.

## Applicability and design level

- Applies to new buildings of three or more stories. Occupied basements and
  penthouses count as stories; unoccupied ones (mechanical, storage) don't. (1-2, 1-2.1)
- The design requirement depends on the Risk Category (Table 2-2):
  - RC I: nothing.
  - RC II: Option 1 (tie forces + Enhanced Local Resistance) **or** Option 2 (Alternate Path only).
  - RC III: Alternate Path + Enhanced Local Resistance for all first-story perimeter columns.
  - RC IV: Tie forces + Alternate Path + Enhanced Local Resistance.
- **This tool covers Alternate Path only.** That is complete for RC II Option 2 and
  partial for RC III and IV.

## Which columns to remove (3-2.9.2.2)

- At minimum, remove an external column near the middle of the short side, near
  the middle of the long side, and at a corner.
- Also remove columns where the plan geometry changes significantly (abrupt
  decrease in bay size, re-entrant corners), and where adjacent columns are
  lightly loaded, bays have different tributary sizes, or members frame in at
  different orientations or elevations. These last conditions are engineering
  judgment.
- Any other column within 30% of the largest dimension of the associated bay
  from the removal location must be removed at the same time.
- For each plan location, analyze these stories (one analysis each):
  1. first story above grade
  2. story directly below the roof
  3. story at mid-height
  4. story above a column splice or change in column size
- Beam continuity is kept across the removed column (Fig. 3-8): only the column
  segment for one story is removed; beams above stay connected.
- Internal columns are removed only where there is underground parking or
  uncontrolled public access (3-2.9.2.3). Out of scope for the hackathon.
- For RC II Option 2, if several locations give similar results because of
  redundancy, one typical analysis plus a note in the design documents is
  enough (2-2.2.2).

## Loads for the linear static procedure (3-2.11.4)

- Bays immediately adjacent to the removed column, at all floors above it,
  get the increased load: Ω × [1.2 D + (0.5 L or 0.2 S)].
- All other bays get 1.2 D + (0.5 L or 0.2 S).
- D includes façade loads. There is no wind in these combinations.
- Ω for steel frames (Table 3-4): 2.0 for force-controlled actions;
  0.9 m_LIF + 1.1 for deformation-controlled actions.
- Live load reduction is permitted but must be based on the structure before
  removal (3-2.3). We don't use it.
- P-Δ is not required for the linear static procedure (3-2.11.3). Local
  stability (lateral-torsional buckling) must still be considered.

## Acceptance (3-2.10, 3-2.11.7)

- The building passes only if no element, component or connection exceeds its
  acceptance criteria. There is no allowable collapse area.
- If an element fails, the structure is redesigned. For RC III/IV the fix is
  applied to similar columns too, not just the one that failed (2-2.3.1).

## Our simplification (see decisions.md, D1)

We use Ω = 2.0 for everything and check every member with Φ R_n ≥ R_u using
nominal strengths, i.e. all m-factors = 1.0 and expected strength = nominal.
For the 2009 linear procedure this is the most conservative case: at m = 1 the
deformation-controlled factor 0.9 m + 1.1 is exactly 2.0, and larger m values
raise capacity (× m) faster than they raise the load factor.

## Submittals (1-8)

The design narrative must state the Risk Category, the design approach (AP) and
the method (linear static), list the software, and provide the electronic input
files.
