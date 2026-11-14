---
capability: job-run-wrapper
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.job_run.last_int@eaae30df87
  - lupin_mcp.job_run.stream_run@bdc5517dbe
  - lupin_mcp.job_run.recorded_since@780f57c2a5
  - lupin_mcp.job_run.run_and_report@f90c309b7d
  - lupin_mcp.job_run.with_trigger@3bf3b60abf
  - lupin_mcp.job_run.switched_on@0f42d5cc75
  - lupin_mcp.job_run.main@bcdd067dbe
---
# Job run wrapper

Runs a shell job and leaves it a job-summary record; the record format is in [[job-summary-record]], and [[job-cron-generate]] puts this wrapper in the cron lines.

## What it does
- Use it as `python -m lupin_mcp.job_run --job <id> -- <command>`. It runs the command, passes its output through and writes one record from the exit code.
- `stream_run` copies stdout and stderr line by line, flushed, while the command runs, so a log holds the run up to a crash. It returns the exit code and the kept text.
- `run_and_report` returns the command's exit code. A code in `clean_codes` (default only 0) is clean; any other code is failed, with the failure "exit <code>".
- A command that cannot start is failed with exit 127.
- `last_int` reads the last integer the first group of a pattern captures, commas removed, or None. `--count-re` gives the scan debt; `--drained-re` gives what the run drained.
- `with_trigger` swaps the value after a `--trigger` flag in the command: cron stays cron, boot becomes `reboot`.
- With `--from-registry`, a `--root <checkout>` flag is appended to the registry command, so a job of another repo runs against that repo's checkout.
- After the record, it asks [[job-host-snapshot]] for a fresh crontab copy.

## Jobs that write their own record
- With `own_summary` set in the registry, the wrapper writes nothing when the command was clean or the job wrote its record during this run.
- `recorded_since` tells that: true when the file holds a record whose last attempt finished at or after the start, to the second.
- A failing exit before the job wrote its record still gets a failed record, so a crash never leaves the old one standing.

## The run-time switch
- Each cron-managed registry job names an INI key in `enabled_key`, `cron job <job> enabled`. `switched_on` reads it through the configuration manager with no default in code. A missing or blank key stops the run.
- When the key is false the wrapper starts nothing. It writes one record with the outcome `disabled`, prints one line naming the key and returns 0. Cron, boot and manual runs all take this path.
- A `disabled` record counts as a run that happened, so the job reads as off and never overdue. It is not a finished run, so the last finish and the debt figures stay as they were.
- A job whose registry entry has no `enabled_key` has no switch and runs as before. Only the cron-managed jobs have one, because a key that controls nothing misleads.

## `main`
- `--from-registry` takes the command and environment from the job's registry entry, as Run now does; `--trigger` says how the run began.
- It returns the command's exit code, or 64 when the job is not in the registry or no command was given.
