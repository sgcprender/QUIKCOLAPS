# claude_client/

Claude API calls. Needs `ANTHROPIC_API_KEY` in the environment or in `ap/.env`
(loaded with python-dotenv; never print or log the key).

- `review.py`: step 3 candidate review. Structured output
  (`output_config.format` with `TOOL["input_schema"]`): the configured model
  (claude-opus-5-5) rejects a forced `tool_choice` and can't disable thinking,
  so the call streams with adaptive thinking and `effort` from config. Two
  payloads: `mode="raw"` (geometry only, no candidates or forces) and
  `mode="conditions"` (geometry + rule candidates + `core.conditions` table).
  System prompt includes `docs/ufc_notes.md`.
- `validate.py`: deterministic checks on Claude's output. Nothing from Claude
  reaches the user or ETABS without passing through here. `check_evidence`
  compares every value Claude cites with the condition table / intact axial file.
- `run_review.py`: runs one mode and saves review + validation + usage + cost to
  `web/data/review_<mode>.json`; `--compare` prints the side-by-side table.

Rules:
- Claude never computes loads, capacities or story selection. Added locations
  get stories from `core.stories.select_stories`.
- Send compact data: `raw_geometry` dedupes identical levels; the condition
  table goes as header + rows. Don't send the full building JSON.
- Test with fake responses (see `tests/test_claude_client.py`); keep real API
  calls out of the test suite. Real runs cost money: ask first.
- Model, max_tokens, effort and prices come from `config/config.toml`.

Next tasks: redesign-pattern summary (step 9) and report narrative (step 13),
both with the same structured-output pattern.
