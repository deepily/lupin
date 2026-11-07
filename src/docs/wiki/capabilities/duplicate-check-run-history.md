---
capability: duplicate-check-run-history
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.duplicate_check_history.failure_of@43157d9e67
  - lupin_mcp.duplicate_check_history.counts_of@7147132f71
  - lupin_mcp.duplicate_check_history.started_from_name@a7bba8bc4c
  - lupin_mcp.duplicate_check_history.line_of@39d984af13
  - lupin_mcp.duplicate_check_history.append_line@8af6d2a2ba
  - lupin_mcp.duplicate_check_history.read_lines@79db3e6ff4
  - lupin_mcp.duplicate_check_history.backfill@0454cced16
  - lupin_mcp.duplicate_check_history.rising_run@d0c7dbcf68
  - lupin_mcp.duplicate_check_history.table@adf6469d04
  - lupin_mcp.duplicate_check_history.main@d1cea0560f
---
# Duplicate check run history
`lupin_mcp.duplicate_check_history` keeps `runs.jsonl` in the check's record folder (`io/duplicate-check-daily`): one JSON line per run, failed runs included. The run itself is in [[duplicate-check-daily-run]].

## What it does
- `line_of( doc, run_file )` flattens a result file to one line with `schema_version` 1. The keys are the same for every run. A number the run could not measure is `None`, never zero.
- A line holds `started_at`, `elapsed_seconds`, `trigger`, `mode` (`daily` or `baseline`), `status` and `failure`. It holds the window (`window_start`, `window_end`, `commits`) and `judged`, `carried`, `cap`, `ceiling` and `judge_calls`.
- It also holds `findings`, `groups`, `group_sizes`, `findings_by_commit`, the four filing counts, `unreadable` and `backfilled`.
- `failure_of( doc )` gives `<stage or prerequisite>: <error, refusal or detail>` for a failed run, else `None`.
- `counts_of( filing )` turns the filer's lists into counts. A run with no filer, or a filer that raised, has `None` counts.
- `append_line( folder, line )` appends and keeps earlier lines. `read_lines( folder )` reads them back, or `[]`.
- `backfill( folder )` adds a line for each result file the history lacks, oldest first, taking `started_at` from the file name. It skips files already listed, so a second call adds nothing. Each added line says `backfilled`.
- `rising_run( lines, runs )` returns the carried series when the carried count rose on each of the last `runs` measured daily runs. Failed and baseline runs are skipped. The guard of [[duplicate-check-daily-run]] uses it.
- `table( lines )` and `main` print the series: `python -m lupin_mcp.duplicate_check_history` (add `--backfill` to add the missing lines, `--folder` to read another folder).
