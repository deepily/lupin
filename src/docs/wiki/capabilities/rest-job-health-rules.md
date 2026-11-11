---
capability: rest-job-health-rules
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.rest.job_health.grace_of@7d36fde368
  - cosa.rest.job_health.covered@b1d1c08698
  - cosa.rest.job_health.recents@9f1d8f3fdd
  - cosa.rest.job_health.silence@8600d126bd
  - cosa.rest.job_health.strip_of@0b1216a7c5
  - cosa.rest.job_health.reasons_for@d54d3a2082
  - cosa.rest.job_health.assess@e64dc33cac
---
# Background job health: states and silence

Decides the state of one job from its registry entry and its summary record. The scan and fix debt tests are in [[rest-job-health-debts]]; the schedule maths is in [[rest-job-cron-schedules]]. The caller supplies the clock, boot time, run lock age and unit state, so no rule reads the outside world.

## States
- First true wins, in this order: unknown, silent, failing, behind, healthy. Every true rule is also listed as a reason, so a job that is failing and growing says both.
- The reader decides a job is silent, not the job, because a dead job cannot say so.

## Helpers
- `parse_time` is the memento reaper's `_parse_iso_aware`, imported under that name. It returns an aware datetime, or `None` for a missing, unparseable or offset-less value.
- `grace_of` uses `grace_seconds` when the entry has it, else `grace_minutes`.
- `recents` returns the summary's recent attempts, or only its last attempt when there is no list.
- `covered( recent, due, mode, before )` is true when some attempt began at or after the due time. Any outcome counts. With `before`, a later run does not cover an earlier hole, and an attempt of another mode does not cover a named mode.

## Rules
- `silence` returns whether the job is silent, whether the machine was off, whether it is running, and the last and next due times. A job is silent when a due time is more than one grace old and nothing started since.
- A live run lock younger than the stale limit means running, never silent. A boot after the due time, for a job with an `after_boot` entry, means not silent. With no `after_boot` entry it marks silent as machine off.
- `strip_of` builds up to 14 recent attempts, oldest first, adding a `missed` hole for each cron due time that nothing covered. Holes start after the oldest recorded attempt, and a due time still inside its grace is not a hole.
- `reasons_for` lists each true rule as state, rule and text, in the order silent, failing, then the behind rules.
- `assess` builds the whole job entry for the jobs endpoint. A job with a liveness block is healthy when its unit is up, silent when down, and unknown when the answer is missing. A job with no summary is unknown, never reported.
