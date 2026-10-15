---
capability: rest-core-arbiter-bootstrap
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.rest.arbiter_bootstrap.arbiter_already_present@0ff460895d
  - cosa.rest.arbiter_bootstrap.build_arbiter_job@9bba03ca0a
  - cosa.rest.arbiter_bootstrap.submit_arbiter_if_absent@19f1a2d89f
  - cosa.rest.arbiter_snapshot_store.set_snapshot@22069518e0
  - cosa.rest.arbiter_snapshot_store.get_snapshot@216b6f51ea
  - cosa.rest.arbiter_snapshot_store.clear_snapshot@753dc959df
  - cosa.rest.code_identity.get_code_identity@35415edfa1
---
# Arbiter startup job, snapshot cache and code identity

Three small pieces the dev server holds for the heartbeat arbiter and for answering "which code am I running". The arbiter and its detectors are on [[cc-hooks-heartbeat]].

## Startup job
- `arbiter_already_present( todo_queue, run_queue )` is true when either queue holds a job whose `JOB_TYPE` is the arbiter job's. A queue without `queue_list` counts as empty.
- `build_arbiter_job( config_mgr )` builds the standing `ArbiterConsumerJob` from config and the file-backed commons gateway, with built-in defaults for absent keys.
- `submit_arbiter_if_absent( todo_queue, run_queue, config_mgr, ask_flow=... )` submits one through the v2 ask flow unless one is present. A failure is logged and swallowed, so the arbiter never blocks server boot.
- `submit_arbiter_if_enabled` wraps that behind the `arbiter in-process bootstrap enabled` flag, so the standalone arbiter and the in-process one never both act. The flag defaults true, and a value that is not true or false reads as false.

## Snapshot cache
- `set_snapshot( dict )` replaces the cached fleet snapshot, last writer wins. `get_snapshot` returns it, or `None` before the first push. `clear_snapshot` resets it.
- All three hold one lock and never raise. The in-process arbiter writes directly; the standalone one posts to the server.

## Code identity
- `get_code_identity` returns a fresh copy of the record captured at import: `git_sha`, `git_branch`, `git_sha_source`, `imported_at`, `pid`.
- It never reads git again. A value git could not answer is `unavailable`, never a guess.

## Don't
- Don't read a sha from the working tree to learn what runs. The tree can be newer than the process.
