# report/

`build_report.py` turns scenarios (+ results when available) into Markdown
following the UFC 1-8 submittal list: Risk Category, approach, method,
software, input files.

- Keep the exclusions list in sync with `docs/scope_and_flow.md`.
- Narrative text comes from a Claude call (claude_client) fed with the table
  data; the tables themselves are generated here, never by Claude.
