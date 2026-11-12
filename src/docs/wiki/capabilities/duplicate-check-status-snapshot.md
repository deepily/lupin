---
capability: duplicate-check-status-snapshot
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.duplicate_check_status.snapshot@d6bb53e02b
  - lupin_mcp.duplicate_check_status.job_summary@1053d7d438
  - lupin_mcp.duplicate_check_status.write_job_summary@100e2842c2
  - lupin_mcp.duplicate_check_status.note_of@e229d27d85
  - lupin_mcp.duplicate_check_status.number@0044f93728
  - lupin_mcp.duplicate_check_status.render_html@809b5d47ac
  - lupin_mcp.duplicate_check_status.folder_of@75dee1c79a
  - lupin_mcp.duplicate_check_status.subdir_of@9c74e74620
---
# Duplicate check status: snapshot, summary and page
The second half of `lupin_mcp.duplicate_check_status`. The rate and health functions it uses are in [[duplicate-check-status-rates]]; the history is in [[duplicate-check-run-history]].

## What it does
- `snapshot( folder, now, crontab_text )` works out everything the page, the note and the accordion show. It returns the job, the time and the backlog (carried, baseline remaining, their total, inflow a day). It also returns the clearing rate, the projected zero, the health and the schedule. The rest are the recent runs, the usage by day, the summary and the numbers of unreadable history lines.
- `schedule.verified` is False when no schedule could be read, so the page says the schedule is unknown instead of showing one that is not installed.
- The recent runs are the last 12 lines, newest first, each with its owed, judged and carried counts, calls and tokens. Each also has calls an hour, the rate-limit flag and the branch it judged.
- `job_summary( lines, now, rows, subdir )` builds the record in the fleet's `job-summary/1` format. It holds the last attempt, the last one that finished and the failures since. It also holds the scan debt: the carried count, the baseline remainder, how many were drained and how many arrived.
- Its fix debt holds the rows queued for retry, the rows filed in the last finished run and the ledger's filed total. With `rows` (the store count of `live_rows_by_mark`) it adds the rows found and open by the filer's mark. It also adds the gap to the ledger's filed total. Without it those three are None, never a gap of 0.
- A ledger line is cited as `code-health/duplicate-check-daily/runs.jsonl:<n>`. A `boot` trigger is named so. The reader works out health; the record has no health field.
- `write_job_summary( folder, now, rows )` writes `job-summary.json` beside the ledger by temporary file and rename. So a reader sees the old file or the new one.
- `note_of( line, snap )` is one sentence on a run: definitions judged, calls, the backlog left and the zero date. It returns None for a quiet run that judged nothing, made no call and left no backlog.
- `render_html( snap )` makes one HTML page with no script and no outside file. It shows the backlog, the projected zero, the recent runs, the tokens by day and the installed schedule. Every history value is escaped.
- `number( value, spec )` formats a value or gives a dash for None. `folder_of( root )` is the run folder `duplicate-check-daily` under the code-health data folder of a project root. `subdir_of( folder )` names that code-health folder from the path, for the evidence label.
