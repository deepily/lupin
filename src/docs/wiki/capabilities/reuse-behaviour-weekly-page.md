---
capability: reuse-behaviour-weekly-page
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.reuse_behaviour.read_refusals@ad3803c166
  - lupin_mcp.reuse_behaviour.reason_label@2baa431ee4
  - lupin_mcp.reuse_behaviour.count_lookups@4e8867f87f
  - lupin_mcp.reuse_behaviour.count_outcomes@58cdf68a73
  - lupin_mcp.reuse_behaviour.count_refusals@102848752c
  - lupin_mcp.reuse_behaviour.report@34018e2cd0
  - lupin_mcp.reuse_behaviour.local_tz@c03dc55518
  - lupin_mcp.reuse_behaviour.week_of@deafbd155c
  - lupin_mcp.reuse_behaviour.last_complete_week_end@2e4e6ecfe2
  - lupin_mcp.reuse_behaviour.day_of@c12c13ce25
  - lupin_mcp.reuse_behaviour.in_week@c1a0ce6077
  - lupin_mcp.reuse_behaviour.count_audits@ab2d088c69
  - lupin_mcp.reuse_behaviour.weekly_report@3d68e374f4
  - lupin_mcp.reuse_behaviour.cron_lines@1b21643193
  - lupin_mcp.reuse_behaviour.main@9bed3e9e73
---
# Reuse behaviour weekly page
`lupin_mcp.reuse_behaviour` makes one page a week on how the fleet used the reuse checks. It counts the fleet, never a seat. It sends nothing and runs no model. See [[reuse-merge-gate]].

## What it does
- A report is seven calendar days ending on a date, in the host's zone (`local_tz`, `week_of`). The default end is the Sunday that closes the last complete Monday-to-Sunday week (`last_complete_week_end`).
- `day_of` reads a stamp's day, or None without an offset. `in_week` splits items into those in the week and those with no readable date. The undated go on their own row.
- `read_refusals` reads `refusals.jsonl`, skips lines that are not JSON objects, and returns an empty list for a missing file.
- `count_lookups` counts calls to each lookup tool that logged no error, then the failed ones. Looking up the same need twice counts twice.
- `count_outcomes` counts scanned lines as `REUSED`, `EXTENDED`, `WROTE_NEW` or `unparsed`. `count_refusals` counts reasons under the labels from `reason_label`. A record with two reasons counts under each.
- `report` draws four tables: lookups, scanned lines by status, outcomes by kind and refusals by reason.
- `count_audits` counts the shadow-audit receipts audited in the week, split by the known-miss flag. `weekly_report` adds a title, the audits and the left-out table.
- `cron_lines( root, python, log_path )` returns a line for every day at 18:00 and a reboot line six minutes after boot. Both run with `--write --skip-if-saved`, so the page is made on the first run after its week closes and later runs skip.
- `main` prints the page. `--write` saves it under `reuse-behaviour/` in the data folder, replacing that day's file. `--print-cron` prints the two lines and installs nothing.
- `--skip-if-saved`, with `--write`, reads no data and prints one `SKIPPED` line when that file exists and is not empty. An empty file is written over. Without `--write` it is a usage error.

## Exit codes
- 0: the page was made.
- 3: it could not be. Causes: a date that is not a date, a corrupt receipt, an unwritable page, or `--print-cron` without `--log-path`.
