# Background-job reporting: the backend

How the jobs report, how health is computed, and where each piece lives. The design is `planning-is-prompting/src/rnd/2026.11.07-background-job-reporting-format.md` (sections 1, 3, 11.1, 12.4, 12.7).

## The pieces

| Piece | File | Job |
|---|---|---|
| Registry | `src/conf/job-registry.json` | The promise of each of the 23 jobs: owner, schedule, grace, notification interval, summary path, run command |
| Overrides | `io/jobs/registry-overrides.json` | Per-job `grace_minutes` and `notify_interval_minutes`, read on every request, no restart |
| Writer | `src/lupin_mcp/job_summary.py` | Writes the `job-summary/1` record by rename; a write failure never fails the job |
| Adapters | `src/lupin_mcp/job_summary_adapters.py` | Wiki librarian, vector refresh, reuse-behaviour call these at the end of `main` |
| Wrapper | `src/lupin_mcp/job_run.py` | Gives a shell job a record: `python -m lupin_mcp.job_run --job <id> -- <command>` |
| Health | `src/cosa/rest/job_health.py` | The rules, with an injected clock: unknown, silent, failing, behind (A to D), healthy |
| Service | `src/cosa/rest/job_service.py` | Registry plus summaries plus boot time, systemd, lock probe and store counts |
| Router | `src/cosa/rest/routers/job_summary.py` | `GET /api/jobs/summary`, `POST /api/jobs/{job}/run` |

## Rules worth knowing

- A job with a schedule is **silent** when it was due, the grace passed, and no attempt began since. Any outcome counts, and a skipped run is a run.
- Suppose the machine booted after the due time. A job with a boot catch-up entry that is not yet due is not yet late. A job with no boot entry is silent, with "missed while the machine was off".
- A held run lock (a non-blocking `flock` probe) makes a job **running**, not silent, until the lock is older than `lock_stale_seconds`.
- Fix debt counts only rows carrying the job's own mark (`fix_debt_key`). If the store cannot be read, the page says "not reported", never zero.
- A looping job uses `every_seconds` with `grace_seconds`. A systemd service uses `liveness` and shows up or down only. A job over several targets lists them under one line.
- Run now is the only management action. It is refused for any login but the operator's, refused while the job's run lock is held, and records trigger `hand` through `LUPIN_JOB_TRIGGER`.

## What rebuilds the symbol index

The vector refresh does. `vector_refresh.run_refresh` calls `build.ensure`, which rebuilds the index when it is stale. So one run refreshes both the index and the vectors, by cron at 10:47 daily and 240 seconds after boot. The wiki librarian tick also calls `build.ensure` before it syncs. There is no separate index job, so the `vector-refresh` entry covers both.

## Not yet reporting

Only the wiki librarian, the vector refresh and reuse-behaviour write their own record. The duplicate check writes its own record. The other jobs show "never reported". They need to be put behind `job_run`, or to write a record themselves. A person edits cron lines, not a seat.
