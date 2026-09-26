# claude_client/

Claude API calls. Needs `ANTHROPIC_API_KEY` in the environment.

- `review.py`: step 3 candidate review. Structured output via a forced tool call
  (`TOOL`), system prompt includes `docs/ufc_notes.md`.
- `validate.py`: deterministic checks on Claude's output. Nothing from Claude
  reaches the user or ETABS without passing through here.

Rules:
- Claude never computes loads, capacities or story selection. Added locations
  get stories from `core.stories.select_stories`.
- Send compact data: building summary + local neighbourhood only for flagged
  candidates. Don't send the full building JSON.
- Test with fake responses (see `tests/test_claude_client.py`); keep real API
  calls out of the test suite.
- Model name and max_tokens come from `config/config.toml`.

Next tasks: redesign-pattern summary (step 9) and report narrative (step 13),
both using the same forced-tool pattern.
