---
capability: job-summary-adapters
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.job_summary_adapters.aware@63bad172e5
  - lupin_mcp.job_summary_adapters.outcome_of@2e31777aef
  - lupin_mcp.job_summary_adapters.report@2c1131cf2c
  - lupin_mcp.job_summary_adapters.record_librarian@bca08586f5
  - lupin_mcp.job_summary_adapters.record_refresh@9e0c57da2d
  - lupin_mcp.job_summary_adapters.record_behaviour@6277c6f449
---
# Job summary adapters

Turn the result of three jobs into a record; the writer is [[job-summary-record]]. The jobs are the wiki librarian, the vector refresh and the reuse-behaviour page.

## What it does
- Each adapter is called once at the end of a run from the job's own `main`. It takes the result the job already computed and reads no log file.
- `outcome_of` returns the outcome and failure. A run that finished is clean, or carried when its exit code is the held code (2 by default). A run that did not finish is skipped for "not due", "switched off" or "BUILD_LOCK_HELD", else failed with its reason.
- `report` writes `job-summary.json` into the job's folder, with trigger cron unless `LUPIN_JOB_TRIGGER` says hand. It returns None when the write fails.
- After writing, it asks [[job-host-snapshot]] to refresh the crontab copy.
- `aware` takes a naive time as local.

## Per job
- `record_librarian`: scan debt is the open findings, drained is the cleared count. Fix debt is the rows created, with deferred rows as unfiled.
- `record_refresh`: the debt is staleness. It carries `built_at` (from the run, else the state file) and a 36 hour limit; the reader computes the age. This record also covers the symbol index, which the refresh rebuilds.
- `record_behaviour`: clean, skipped or failed with a reason. It names no debt.
- A failed run carries the old debts forward.

## Not here
- The duplicate check writes its own record.
