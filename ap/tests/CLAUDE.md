# tests/

- `pytest` from the repo root.
- Tests for engineering rules include the hand calculation in a comment.
- No network or ETABS in tests. Claude responses are faked.
- Fixture: `fixtures/demo_building.json` (synthetic). If you change the
  generator, regenerate and update expected numbers deliberately.
