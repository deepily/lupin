---
capability: deep-research-narrowing-harness
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.agents.deep_research.narrowing_harness.NarrowingHarness@ebcfc407a9
  - cosa.agents.deep_research.narrowing_harness.NarrowingResult@2ef3e57a19
  - cosa.agents.deep_research.narrowing_harness.parse_args@33761fcaa5
  - cosa.agents.deep_research.narrowing_harness.run_cli@f6d95f1ceb
  - cosa.agents.deep_research.narrowing_mocks.MockResearchAPIClient@fb2ac85d57
  - cosa.agents.deep_research.narrowing_mocks.get_mock_subqueries@a690fc1592
  - cosa.agents.deep_research.narrowing_mocks.get_mock_theme_response@72c3f55699
---
# Deep research narrowing harness

A stand-alone test rig for the topic-narrowing step of [[deep-research]]. It groups planned subqueries into themes, lets a person pick, and returns the chosen subset, with or without real model calls.

## What it does
- `NarrowingHarness.run_theme_clustering` sends the subqueries through `get_theme_clustering_prompt` and returns the model's theme JSON.
- `run_full_narrowing` runs clustering, theme selection, topic refinement and final filtering. `run_from_plan_file` loads the subqueries from a saved plan first.
- With `auto_approve` the harness accepts every selection and asks nobody.
- `NarrowingResult` keeps every intermediate stage, the call count and duration, and whether the run was cancelled. `to_dict` makes it JSON-safe.
- `parse_args` and `run_cli` are the command line: `--input`, `--phase themes` or full, `--mock`, `--cli-mode`, `--output`. Without `--input` it uses sample subqueries.
- `MockResearchAPIClient` answers `call_with_json_output` with a canned theme reply. It reads the topic count from the text "N research topics" and counts its calls.
- `get_mock_theme_response` picks a canned reply by variant (`balanced`, `minimal`, `maximal`, `empty`). `get_mock_subqueries` returns 5 or 8 sample subqueries.

## Don't
- Don't treat the mock reply as model output. It ignores the system prompt and the topic text.
