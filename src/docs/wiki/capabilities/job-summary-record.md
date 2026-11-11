---
capability: job-summary-record
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.job_summary.iso_now@79805f657a
  - lupin_mcp.job_summary.read_summary@197f9caef9
  - lupin_mcp.job_summary.check_attempt@e674f456a4
  - lupin_mcp.job_summary.trigger_from_env@19ef499d42
  - lupin_mcp.job_summary.trimmed@6e4b8751ff
  - lupin_mcp.job_summary.scan_block@846436d66f
  - lupin_mcp.job_summary.fix_block@6c6588c557
  - lupin_mcp.job_summary.build_summary@c3e4376087
  - lupin_mcp.job_summary.write_atomic@04964a1f37
  - lupin_mcp.job_summary.write_summary@cdf5e287f2
  - lupin_mcp.job_summary.append_run@31fc796bb7
---
# Job summary record

The shared writer of the `job-summary/1` file each background job leaves after a run. See [[job-summary-adapters]], [[job-run-wrapper]] and [[job-backfill]] for the callers.

## The record
- One small file per job, replaced whole by rename (`write_atomic`), so a reader never sees half a file.
- It holds the last attempt, the last finished run, consecutive failures, a scan debt block, a fix debt block and the last 7 attempts.
- It has no health field. The reader works health out, because a dead job cannot write that it is dead. Null means not reported, never zero.
- `read_summary` returns None for a file that is missing, unreadable or of another schema.

## Attempts
- `check_attempt` fills every key; outcome must be clean, carried, failed or skipped, trigger must be cron, boot or hand, and a start time is required. Otherwise ValueError.
- `trigger_from_env` returns the value of `LUPIN_JOB_TRIGGER` when it names a trigger (Run now sets hand), else the default.
- `iso_now` gives local time with an offset, to the second.

## Building the next record
- `build_summary` moves `last_finished` only on clean or carried. Failures grow on failed, reset on clean or carried and hold on skipped.
- `scan_block` and `fix_block` keep the previous block when the run gave none or did not finish. A finished run adds one point; `trimmed` keeps the newest 14.
- A failed or skipped run keeps the old scan block and time: stale, not zero. Fix debt points add the opened rows to the previous total.
- Drained is never below the fall in the count: 168 to 3 drained at least 165, whatever the job reported. The wiki librarian reports 0. Arrivals are derived only when the job left them null and a previous count exists: count now minus count before plus drained. They are never negative.

## Writing
- `write_summary` returns the record, or None with a message when the file cannot be written. A write failure never fails the job. A malformed attempt still raises.
- `append_run` adds one line to a job's `runs.jsonl` and returns False on an I/O error.
