---
capability: shared-utilities
pin_algorithm: py3.13.x60338d/ts5.9.3
pins:
  - cosa.utils.util.get_project_root@ebedf9487b
  - cosa.utils.bounded_retry.retry_call@9fd1ae9583
  - cosa.utils.checked_hash_pyc.install@4bdf801a3a
  - cosa.utils.cc_memory_watch.run_once@ee71902825
  - cosa.utils.vertex_logging.run_probe@0bf010a8b0
---
# Shared helpers in cosa.utils and cosa.tools

Small helpers that other code imports directly. Config loading, redaction and spend caps are in [[utils-config-secrets-and-vertex]].

## Paths, files and time
- `util.get_project_root()` returns `LUPIN_ROOT` when set. Otherwise it prints a warning and returns `/var/lupin`. Build paths from it, not from `__file__`.
- `util` also holds file readers and writers such as `get_file_as_string`, `get_file_as_json` and `write_string_to_file`.
- `edt_timestamp` stamps and splits the bracketed EDT prefix on a DM body. `dm_text.dm_word_count` counts words.

## Retry and rate limits
- `bounded_retry.retry_call` and `retry_call_async` run a function under a `RetryPolicy`, bounded by attempts, a deadline, or both. The last exception is re-raised unchanged.
- `api_resource_manager.get_arm()` returns the singleton that wraps the web search rate limiter. Its own header says no agent calls it yet.

## Test and tree hygiene
- `checked_hash_pyc.install()` patches the bytecode write so new pycs are checked-hash. It returns True only when it newly took effect.
- `tree_state.tree_state_line` renders the one line naming which tree and bundle a test run measured.
- `coverage_contention` refuses a coverage run while a foreign pytest is live. `coverage_frame` asserts the coverage frame measures every file it claims.
- `worktree_artifacts` and `seat_worktree` provision worktrees; see [[worktree-lifecycle]].

## Process watching
- `cc_memory_watch.run_once` samples memory of live Claude Code processes and writes a line per runaway. It kills nothing.

## Database and Vertex
- `db_grants`, `db_roles`, `db_secret_files` and `dotenv_password` check or provision database roles and passwords.
- `vertex_logging.run_probe` returns proven, refuted or inadmissible for request logging. It reaches the network only through injected callables.
- `vertex_env.compose_vertex_env` composes the Vertex environment for one process and raises on any hazard.

## Search tools
- `cosa.tools.search_kagi.KagiSearch` wraps Kagi; `search_lupin.LupinSearch` is the vendor-neutral wrapper. See [[web-search-tools]].
