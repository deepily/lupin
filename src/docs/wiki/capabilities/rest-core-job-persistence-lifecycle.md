---
capability: rest-core-job-persistence-lifecycle
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.rest.job_persistence.is_agentic_job_type@bc8b85c8ae
  - cosa.rest.job_persistence.persist_job_created_from_metadata@5f170025d1
  - cosa.rest.job_persistence.persist_job_started_from_metadata@bab8c7c15c
  - cosa.rest.job_persistence.persist_job_stalled_from_metadata@30547f5b38
  - cosa.rest.job_persistence.persist_job_failed_from_metadata@8dd7662712
  - cosa.rest.job_persistence.persist_job_cancelled@3bf4ec24d2
  - cosa.rest.job_persistence.persist_job_paused_state@7f019a3215
  - cosa.rest.job_persistence.record_server_available@eca7376c32
  - cosa.rest.job_persistence.get_last_available@ef011522bb
  - cosa.rest.job_persistence.get_restorable_jobs@b0688202c2
  - cosa.rest.job_persistence.restore_pending_jobs@9d091bd8eb
---
# Job persistence: writing a job's life and restoring it

`job_persistence` keeps one `job_history` row per agentic job so a restart can restore it. The queues it mirrors are on [[cj-flow-queue]]. Every `persist_*` call logs and returns on failure; none raises into the queue.

## Writes, in lifecycle order
- `is_agentic_job_type( job_type )` is true only for the listed agentic types, false for `None`.
- `persist_job_created_from_metadata` inserts a `pending` row. `persist_job_started_from_metadata` sets `running` and `started_at`.
- `persist_job_stalled_from_metadata` sets `stalled` and merges the checkpoint, so the job stays resumable. `persist_job_failed_from_metadata` sets `failed` with the error.
- `persist_job_cancelled` sets `CANCELLED`. Without it a cancelled job stays `pending` and the next boot would run it.
- `persist_job_paused_state( job_id, paused )` records the pause flag, so a paused job comes back held.

## Restart
- `record_server_available` stamps one lifecycle row from the clock heartbeat and at clean shutdown. `get_last_available` reads it, or `None` on a first boot.
- `get_restorable_jobs` returns the rows still `pending` after `mark_interrupted_jobs` has run.
- `restore_pending_jobs( restorable, job_factory, ask_flow )` rebuilds each job from its stored `original_args` and its old `id_hash`, and re-holds a paused one. A row with no `routing_command`, or whose factory returns `None`, is skipped. It returns the count pushed.

## Don't
- Don't build a restored job from the whole metadata. The submit args live under `original_args`.
