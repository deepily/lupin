---
capability: reuse-orphaned-runs
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.reuse_orphans.pid_of@fa7161a151
  - lupin_mcp.reuse_orphans.orphans@99024f9e8f
  - lupin_mcp.reuse_orphans.close_orphans@158cd73d0d
  - lupin_mcp.reuse_orphans.main@83ec4380ee
---
# Reuse: orphaned spend-ledger runs
`lupin_mcp.reuse_orphans` lists open runs in the Jev spend ledger whose process is gone, and closes them when a person confirms. A lookup closes its run in a `finally` block. A seat killed, reaped or cleared mid-lookup never gets there, so its run holds its whole ceiling against the account until someone closes it. The ledger is in [[reuse-token-ceiling-and-spend-ledger]] and [[reuse-ledger-capacity-and-run-names]]. It sends nothing and runs no model.

## What it does
- `pid_of( run )` reads the process id from a run name: the digits after the date. It returns None when the name has no date followed by a number.
- `orphans( ledger, now, min_age_hours, proc_root )` walks `open_runs()`. It lists a run that is at least `MIN_AGE_HOURS` old (2.0) and whose process id has no entry under `/proc`. Each entry holds `run`, `pid`, `ceiling`, `spent` and `age_hours`, oldest first. It writes nothing.
- `close_orphans( ledger, found, confirmed_by )` closes each listed run under the confirming person's name. It returns the closed names and a map of skipped runs. A run another process closed in the meantime is skipped, not an error. An empty `confirmed_by` raises `ValueError`.
- `main` prints one JSON object with the cutoff, the orphans, and the runs closed or skipped. The ledger is written only when `--confirmed-by` is given. `--ledger` and `--min-age-hours` override the defaults.
- Exit 0 means it listed, or closed. Exit 3 means the ledger could not be read.

## Limits
- `/proc` answers only for this host. A run begun on another host would look dead.
- A recycled process id makes a dead run look alive, so the list can miss a run. It never names a live one.
- A run whose name carries no process id (set by hand through `LUPIN_REUSE_JEV_RUN_NAME`) is never listed.
