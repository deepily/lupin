---
capability: job-backfill-readers
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.job_backfill.librarian_steps@9ea493e487
  - lupin_mcp.job_backfill.refresh_steps@86e3a94968
  - lupin_mcp.job_backfill.behaviour_steps@5b73e3d496
  - lupin_mcp.job_backfill.shadow_steps@58cae4d748
  - lupin_mcp.job_backfill.sweep_steps@019d2d82bf
  - lupin_mcp.job_backfill.report_steps@c6fda8575f
---
# Job backfill readers

The per-source readers of [[job-backfill]]. Each returns a list of steps, or None when its source has nothing usable. Records go out through [[job-summary-record]].

## Readers
- `librarian_steps` reads the last JSON line of the librarian log. If that tick ran, it is one clean step. If it did not, the last good tick from `tick-state.json` comes first, dated by `last_run_date` at local midnight, then the failed or skipped tick. "not due" and "switched off" are skipped; any other reason is failed.
- `refresh_steps` reads `refresh-state.json`. A failed last run is preceded by the good build it did not replace, dated by `built_at`. Freshness carries `built_at` and the 36 hour limit; the reader works out the age.
- `behaviour_steps` reads `weekly.log`, which has no times or counts. The last line starting `REFUSING` (failed, with the line as the failure), `SKIPPED` or "Reuse behaviour," decides.
- `shadow_steps` reads the last JSON line of the shadow-audit log: failed when it counts failed audits, else clean with the audited count as drained.
- `sweep_steps` reads the last "eligible" and "reclaimed" figures. Scan debt is eligible minus reclaimed, never below 0; drained is reclaimed. No eligible line means None.
- `report_steps` returns failed when the log shows a Traceback, an error word or a non-2xx notify; else clean. A missing or empty log gives None, because an empty log's time is not a run time.

## Invariants
- Unless a source holds its own time, the step is dated by the log's last write.
