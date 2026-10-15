---
capability: presentation-cli
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.agents.presentation_generator.__main__.main@403b5ac1b0
  - cosa.agents.presentation_generator.__main__.run_all_smoke_tests@aaccbbd394
  - cosa.agents.presentation_generator.__main__.run_presentation_generation@0c79dce3b4
  - cosa.agents.presentation_generator.api_client.APIResponse@983d368321
---
# Presentation generator command line

`python -m cosa.agents.presentation_generator` builds a deck from a terminal. The code is in `__main__.py`. The workflow is described in [[presentation-generation]].

## What it does
- `main` handles `--user-visible-args` first and prints `USER_VISIBLE_ARGS` as JSON: source, target_duration_minutes, target_slide_count, audience, audience_context and theme. Then `--smoke-test` runs `run_all_smoke_tests`. Without `--source` it prints help and exits 1.
- `run_presentation_generation` resolves a relative `--source` against the project root and returns 1 if the file is missing. It builds a `PresentationGeneratorJob` and awaits `_execute()` directly, so no queue is involved.
- It returns 0 when the job gives a non-empty summary and 1 on an empty result, an interrupt or an exception. With `--debug` the traceback is printed.
- `--dry-run` is handed to the job as `dry_run`. The job then sends low-priority breadcrumb notifications and returns a mock summary, with no model calls.
- `--user-email`, `--user-id`, `--session-id` and `--no-confirm` are hidden flags for the expeditor. The user and session defaults are `user@example.com` and `cli-session`.
- `run_all_smoke_tests` calls `quick_smoke_test` in six modules: config, state, `cosa_interface`, `voice_io`, orchestrator and job. It prints a table and returns True only if none failed.
- `APIResponse` is one content-phase model reply: content, model, token counts, a stop reason, the SDK cost and the raw response. The stop reason is `None` when the end state is unknown; it is not turned into `end_turn`.

## Don't
- Don't look for a voice or CLI-mode flag here: the presentation runner has none.
