---
capability: job-alert-watcher
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_arbiter_app.job_alert_watcher.flatten@61d8734154
  - lupin_arbiter_app.job_alert_watcher.alert_key@5c15922f5c
  - lupin_arbiter_app.job_alert_watcher.alert_message@ae2216a65e
  - lupin_arbiter_app.job_alert_watcher.due_alerts@717ac0c90b
  - lupin_arbiter_app.job_alert_watcher.decide@495d06cf93
  - lupin_arbiter_app.job_alert_watcher.delivered@35e5670140
  - lupin_arbiter_app.job_alert_watcher.read_state@513473dd08
  - lupin_arbiter_app.job_alert_watcher.write_state@1ecf1cec88
  - lupin_arbiter_app.job_alert_watcher.make_live_summary_fn@ba181b86a9
  - lupin_arbiter_app.job_alert_watcher.JobAlertLoop@8f2e4c72ae
---
# Job alert watcher

Tells Rick when a background job goes bad. It runs inside the :8001 arbiter ([[arbiter-app-service]]) so a bounce of the dev server cannot silence it.

## What it alerts on
- Each poll reads the same job summary the jobs accordion shows. Failing, silent and behind entries are alerted; unknown and healthy never are.
- `flatten` uses a job's targets when it has any, else the job itself, so one bad target is one alert.
- `alert_key` is the job id, plus `/target` for a target. `alert_message` names the job, target, state and first reason, cut to 300 characters with an ellipsis.
- `due_alerts` sends one message for an entry with no stored time or whose own notification interval has passed. A time that cannot be read counts as due; a time in the future does not. `decide` returns the messages alone.
- The new state holds only keys that are bad now, so a recovered job alerts at once next time.

## Delivery and state
- `delivered` is true when any channel outcome is a delivered one or the durable post.
- `JobAlertLoop.poll_once` sends each due alert, then saves the state. A crash re-alerts and never loses one.
- An alert that reached no channel is logged `job_alert_undelivered` and keeps its old state, so the next poll retries. It logs `job_alert` per message and returns the number delivered.
- `read_state` returns an empty dict for a missing, unreadable or non-dict file. `write_state` replaces `io/jobs/alert-state.json` by rename and makes the folder.
- `start` and `stop` run the loop on a daemon thread, every 300 seconds by default.

## Wiring
- `make_live_summary_fn` builds the list `GET /api/jobs/summary` answers with, in this process. It imports the job service on first call.
- The arbiter builds the loop only when `arbiter job alert enabled` is true; it ships false.
