---
capability: cc-task-store-client-and-spool
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_cli.claude_code.hooks.lib.task_store_client.read_api_key@6b300c3e0c
  - lupin_cli.claude_code.hooks.lib.task_store_client.create_task@fa5ccfb844
  - lupin_cli.claude_code.hooks.lib.task_store_client.transition_task@0d3908eff8
  - lupin_cli.claude_code.hooks.lib.task_store_client.correlate_task@5466fdecbe
  - lupin_cli.claude_code.hooks.lib.task_store_client.amend_task@e02875bd11
  - lupin_cli.claude_code.hooks.lib.task_store_client.query_tasks@67f912d34b
  - lupin_cli.claude_code.hooks.lib.task_store_client.query_by_correlation_key@b5ece8dcc3
  - lupin_cli.claude_code.hooks.lib.task_store_client.query_blocked_user_rows@672046a4e4
  - lupin_cli.claude_code.hooks.lib.task_store_client.query_owed@9e73ec7e08
  - lupin_cli.claude_code.hooks.lib.task_store_client.query_owed_breakdowns@5603479ccf
  - lupin_cli.claude_code.hooks.lib.task_store_client.fetch_board@a7e7282b71
  - lupin_cli.claude_code.hooks.lib.task_store_settings.load_task_store_settings@bd2a3519b6
  - lupin_cli.claude_code.hooks.lib.task_store_spool.spool_path@24c1d67cc5
  - lupin_cli.claude_code.hooks.lib.task_store_spool.append_entry@a72e72b67e
  - lupin_cli.claude_code.hooks.lib.task_store_spool.read_entries@0bc515eede
  - lupin_cli.claude_code.hooks.lib.task_store_spool.rewrite_entries@5a52298398
  - lupin_cli.claude_code.hooks.lib.task_store_spool.partition_expired@63b960f040
---
# Task-store hook client and spool
The hook side of the unified task store: a stdlib REST client for `/api/tasks`, its settings, and an on-disk spool for writes lost in transit.
## What it does
- Every client call returns `( ok, status_code, body )` and never raises. A `status_code` of `None` means the transport failed, which is the only spool trigger.
- `read_api_key()` reads the hook-writer key file under `LUPIN_ROOT` and returns an empty string when it is missing.
- `create_task`, `transition_task`, `correlate_task` and `amend_task` POST to the matching task endpoints.
- `query_tasks()` and `query_by_correlation_key()` GET `/api/tasks`; the second one is the replay idempotency probe.
- `query_owed()` asks the server for the owed set in one request. `query_owed_breakdowns()` adds the priority breakdown. A failed read gives `( False, 0, ... )`, so the caller does not poke.
- `query_blocked_user_rows()` returns an owner's blocked rows, from which the user-chase time is derived.
- `fetch_board()` pages the whole board and returns `( rows, truncated )`. It raises `RuntimeError` on a non-ok response.
- `load_task_store_settings()` reads the `task_store` block of `~/.claude/settings.json`. Defaults are off, and a bad timeout or URL raises `ValueError`.
- The spool file is `.task-store-spool-<session>.jsonl`. `append_entry` adds a line and `read_entries` returns them oldest first.
- `rewrite_entries()` replaces the file atomically and removes it when empty. `partition_expired()` splits live and expired entries; a missing `ts` counts as expired.
## Don't
- Do not treat a 4xx or 5xx as a transport loss. It is a server verdict and is not spooled.
## Invariants
- `append_entry` and `rewrite_entries` may raise `OSError`; their caller wraps them.
