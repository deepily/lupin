---
capability: job-backfill
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.job_backfill.is_file@512d237ed5
  - lupin_mcp.job_backfill.mtime_of@a0a07f82d6
  - lupin_mcp.job_backfill.attempt@17149fe91c
  - lupin_mcp.job_backfill.step@7387c85ac0
  - lupin_mcp.job_backfill.last_json_line@4d8f6bfc2c
  - lupin_mcp.job_backfill.sources@18c22d518d
  - lupin_mcp.job_backfill.replay@4831da7158
  - lupin_mcp.job_backfill.backfill@1c369b4b53
  - lupin_mcp.job_backfill.main@65702016d1
---
# Job backfill

One-time backfill of `job-summary.json` from the records jobs already leave. The per-job readers are in [[job-backfill-readers]]; the writer is [[job-summary-record]].

## What it does
- It starts no job and edits no store row. Each source becomes one or two attempts, written through the shared writer, so the file looks like a job's own run.
- `backfill` returns `(job, status, detail)` rows. Status is `written`, `would-write` (dry run), `skipped` (already has a summary) or `no-record`.
- `--force` overwrites an existing summary. `--dry-run` writes nothing. `main` prints one line per job and returns 0.
- A source whose record cannot be read is `no-record` with the reason (cut to 120 characters); the other jobs still run.
- The duplicate check is not read from a log. When its folder holds `runs.jsonl`, its own status writer makes the record.

## Helpers
- `sources` maps registry job ids to readers: wiki-librarian, vector-refresh, reuse-behaviour, shadow-audit, io-tmp-sweep, hook-log-sweep, disk-report and worktree-census.
- `attempt` builds one backfilled attempt: it starts and finishes at one time, trigger is cron, and the evidence says "trigger not recorded".
- `step` pairs an attempt with scan debt, fix debt and the work count.
- `replay` writes steps oldest first and returns the last record, or None when the file cannot be written.
- `last_json_line` returns the last line of a file that parses as a JSON object, or None.
- `mtime_of` gives the file's last write as an aware time; It uses `aware` of [[job-summary-adapters]], which takes a naive time as local.
- `is_file` returns False for a missing file or an unreadable folder.

## Invariants
- A log with no time inside it is dated by the file's last write, and the evidence says so.
