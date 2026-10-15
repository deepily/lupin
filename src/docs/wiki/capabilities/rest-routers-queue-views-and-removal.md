---
capability: rest-routers-queue-views-and-removal
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.rest.routers.queues.get_todo_queue@9bc801466a
  - cosa.rest.routers.queues.get_running_queue@f682d441a0
  - cosa.rest.routers.queues.get_done_queue@7111b92331
  - cosa.rest.routers.queues.get_dead_queue@590e0083a7
  - cosa.rest.routers.queues.get_notification_queue@419a0b0054
  - cosa.rest.routers.queues.get_pool_status@b2d3b51239
  - cosa.rest.routers.queues.get_queue@4841811c76
  - cosa.rest.routers.queues.reset_queues@081b88f384
  - cosa.rest.routers.queues.delete_all_queue_jobs@482669c82e
  - cosa.rest.routers.queues.delete_queue_job@88ffe92290
  - cosa.rest.routers.queues.pause_job@a1e917052a
  - cosa.rest.routers.queues.resume_job@45c90a952e
---
# Queue views and removal

The queue-reading and queue-clearing doors under `/api` in `routers/queues.py`. Every one needs a signed-in user. See [[cj-flow-queue]] for the queues themselves.

## What it does
- `get_todo_queue`, `get_running_queue`, `get_done_queue`, `get_dead_queue` and `get_notification_queue` fetch the singleton queues from `lupin_app.main`. They stand in for dependency injection.
- `get_pool_status` answers `GET /api/queue/pool-status` with `inflight_agentic_jobs`, `max_agentic_workers` and `pending_in_pool`.
- `get_queue` answers `GET /api/get-queue/{queue_name}` for `todo`, `run`, `done` or `dead`. A bad name is 400. `user_filter` is checked by `authorize_queue_filter`: omitted means your own jobs, and `*` or another user id needs admin, else 403.
- `delete_queue_job` answers `DELETE /api/queue/{queue_name}/{job_id}`. It is 404 for an unknown job and 403 for a job you do not own unless you are admin. A running agentic job is sent its cancel signal first. A job leaving `todo` is also marked cancelled in the history table.
- `delete_all_queue_jobs` answers `DELETE /api/queue/{queue_name}/all`. An admin clears the whole queue. Anyone else removes only their own jobs.
- `pause_job` and `resume_job` answer `PATCH /api/queue/todo/{job_id}/pause` and `/resume`. They flip the job between paused and queued, emit `job_state_transition`, and record the pause durably so a restart keeps it. Resume wakes the consumer.
- `reset_queues` answers `POST /api/reset-queues` and clears all five queues.

## Don't
- Don't call `reset_queues` casually. It checks only that you are signed in, and it empties every user's queues.
- Don't expect pause to work on a running job. Both doors look in `todo` only and answer 404 otherwise.

## Invariants
- `get_queue` never ignores a filter you may not use. It refuses with 403.
- Deleting from `todo` always updates the history row, so a restart does not bring the job back.
