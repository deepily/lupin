---
capability: rest-routers-job-control-and-history
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.rest.routers.queues.cancel_job@0b35accfde
  - cosa.rest.routers.queues.send_job_message@5d42595342
  - cosa.rest.routers.queues.get_job_interactions@612b661ae2
  - cosa.rest.routers.queues.get_job_history@995c132f87
  - cosa.rest.routers.queues.get_job_history_detail@18acf1faab
  - cosa.rest.routers.queues.delete_job_history_endpoint@a92dbf1593
  - cosa.rest.routers.queues.delete_all_job_history@934fd132a9
  - cosa.rest.routers.queues.push@7318d4cc0a
  - cosa.rest.routers.queues.push_agentic@7abddfc6fd
  - cosa.rest.routers.queues.retry_job_history@3bbfd41b04
  - cosa.rest.routers.queues.resume_stalled_job@cbc85a0cca
  - cosa.rest.routers.queues.resume_tfe_smart@2f3d0f271a
---
# Job control and job history

The per-job doors of `routers/queues.py`, plus the five retired doors that now answer 410. Every live door needs a signed-in user, and a job you do not own is 403 unless you are admin. See [[retired-queue-doors]] and [[cj-flow-queue]].

## What it does
- `cancel_job` answers `POST /api/jobs/{job_id}/cancel`. A running agentic job gets a cancel request and answers `cancel_requested`. A queued job is removed and answers `cancelled`. A running job of another type is 400, an unknown id is 404, and a removal that lost a race is 409.
- `send_job_message` answers `POST /api/jobs/{job_id}/message` with `{ "message", "priority" }`. Priority is `normal` or `urgent`, an empty message is 400, and the job must be running. It saves a `user_initiated_message` notification and returns its id.
- `get_job_interactions` answers `GET /api/get-job-interactions/{job_id}` with the job's metadata and its notifications, newest first, one per progress group. It looks in the running, done and todo queues, then the database. A failed notification query returns an empty list, not an error.
- `get_job_history` answers `GET /api/job-history`, paged (`limit` 1 to 100), with `status`, `job_type`, `days`, `exclude_ids` and `user_filter`. `get_job_history_detail` answers `GET /api/job-history/{job_id}`, 404 for an unknown id.
- `delete_job_history_endpoint` hard-deletes one record for its owner or an admin, 404 if unknown. `delete_all_job_history` answers `DELETE /api/job-history/all` for a `days` window of any whole number, or `all`, and 400 for anything else. An admin deletes across users, anyone else only their own.
- `push`, `push_agentic` and `retry_job_history` answer 410 and point to `/api/v2/ask` or `/api/v2/submit`. `resume_stalled_job` and `resume_tfe_smart` answer 410 and point to `/api/v2/resume-job`.

## Don't
- Don't use `DELETE /api/queue/run/{job_id}` to stop a job that `cancel_job` can stop. It removes the job and loses its work.
- Don't rely on `send_job_message` for a job that has not started. It is 404.

## Invariants
- Cancelling a queued job also marks its history row cancelled, so a restart does not run it.
- `get_job_history` refuses a `user_filter` you may not use with 403, and does not narrow it.
