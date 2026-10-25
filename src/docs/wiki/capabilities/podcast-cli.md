---
capability: podcast-cli
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.agents.podcast_generator.__main__.extract_user_id_from_path@8b67e6a3e6
  - cosa.agents.podcast_generator.__main__.main@314f628317
  - cosa.agents.podcast_generator.__main__.parse_languages_arg@3e2fd92963
  - cosa.agents.podcast_generator.__main__.run_all_smoke_tests@834c9f5708
  - cosa.agents.podcast_generator.__main__.run_audio_generation@a2612993c1
  - cosa.agents.podcast_generator.__main__.run_podcast_generation@e02d27cb9f
  - cosa.agents.podcast_generator.__main__.run_script_editing@d11cb746df
---
# Podcast generator command line

`python -m cosa.agents.podcast_generator` runs the podcast generator from a terminal, with no queue. The code is in `__main__.py`. The workflow itself is described in [[podcast-generation]]. Each mode returns exit code 0 on success and 1 on a missing file, a cancel, an interrupt or an error.

## What it does
- `main` picks a mode from the flags: `--smoke-test`, then `--generate-audio`, then `--edit-script`, then `--research`. With none of them it prints help and exits 1.
- `--user-visible-args` is handled before argument parsing and prints the `USER_VISIBLE_ARGS` list as JSON: research, languages, audience and audience_context.
- `run_podcast_generation` is the full run. It resolves a relative `--research` path against the project root and builds a `PodcastConfig`. The CLI audience flags override the INI keys `podcast generator audience` and `podcast generator audience context`. `--dry-run` only prints the planned steps and returns 0; it does not call the orchestrator.
- `run_script_editing` loads a saved script with `from_saved_script` and calls `do_review_only_async`. `run_audio_generation` loads one and calls `do_audio_only_async`, honouring `--max-segments` and `--languages`.
- `run_all_smoke_tests` imports ten modules and calls each one's `quick_smoke_test`. It runs through `run_import_smoke_suite` ([[agent-smoke-helpers]]), cutting each error text to 60 characters. It prints a table and returns True only if none failed. `orchestrator` is in that list; `job` and `mock_clients` are not.
- `parse_languages_arg` splits a comma list, strips blanks and returns `None` for an empty string. Unknown codes are only warned about, in `run_podcast_generation`.
- `extract_user_id_from_path` returns the email segment from a `/podcasts/{email}/` path, or `None`. Audio-only mode uses it when `--user-id` is still the default `user@example.com`.

## Don't
- Don't expect `--cli-mode` in the job path: it only calls `voice_io.set_cli_mode( True )` in these three runners.
