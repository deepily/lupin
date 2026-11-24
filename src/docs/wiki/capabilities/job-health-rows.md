---
capability: job-health-rows
pin_algorithm: py3.13.xaad549/ts5.9.3
pins:
  - lupin_arbiter_app.job_alert_watcher.reasons_text@d9c44dda9b
  - lupin_arbiter_app.job_alert_watcher.row_fingerprint@75a515662e
  - lupin_arbiter_app.job_alert_watcher.compose_job_row@82539f4c5d
  - lupin_arbiter_app.job_alert_watcher.sync_job_rows@1958b2a3a7
  - lupin_arbiter_app.job_alert_watcher.make_row_sync@946181c1b4
  - lupin_arbiter_app.job_alert_watcher.registry_owners@07688d1027
---
# Job health rows

The row half of [[job-alert-watcher]]: one store row for each failing or silent job.

## Building a row
- `reasons_text` joins the text of an entry's failing and silent reasons with spaces.
- `row_fingerprint` is the state, the reasons and the last attempt's start, or `never`, joined by bars.
- `compose_job_row` returns the fields the store's create takes. Owner and accountable are both the registry owner, and the key is `job-health:<job>`.
- The row body gives the reasons and says when the owner is unconfirmed. It also says the row closes by itself.

## Keeping rows in step
- `sync_job_rows` opens a row for a failing or silent job with none, and amends one only when the fingerprint changed.
- It drops the open row of a healthy job. Behind and unknown jobs are left alone.
- A fault on one job goes into `errors`, its fingerprint is not recorded, and the other jobs still run.
- `make_row_sync` returns the function the poll calls with the jobs and the time. It returns one failure line when the registry is unreadable. An error reading or writing the state file is not caught.
- An unreadable registry is one failure line. The fingerprint file is written only when it changed.

## Owners
- `registry_owners` maps each job id to its owner and whether the registry confirms that owner. `mr-radio` becomes `mr radio`.
- It raises what the registry loader raises when the registry is unreadable or invalid.
