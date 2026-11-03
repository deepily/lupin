---
capability: duplicate-check-verdict-lines
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.duplicate_check_verdicts.parse_line@aaba3c7c88
  - lupin_mcp.duplicate_check_verdicts.finding_ids@2bce6f3244
  - lupin_mcp.duplicate_check_verdicts.write_verdict@fed99252a1
  - lupin_mcp.duplicate_check_verdicts.LiveAmender@eda00319f1
  - lupin_mcp.duplicate_check_verdicts.main@e7f577b7f9
---
# Duplicate check: verdict lines and their writer
The triage seat rules on each finding of a run with one line. `python -m lupin_mcp.duplicate_check_verdicts` writes it. The run is in [[duplicate-check-daily-run]]. The weekly page that counts the lines is in [[reuse-behaviour-duplicate-check-table]].

## The line
`DUPCHECK-VERDICT run=<result file stem> finding=<findings[].id> verdict=DUPLICATE|EXTEND|DISTINCT class=<kebab-case reason> by=<persona key> ts=<ISO-8601 UTC>`
- The fields are space-separated `key=value` pairs in that order, with no spaces inside a value.
- `DUPLICATE` and `EXTEND` count as real on the weekly page. `DISTINCT` counts as not. `class` is free text for now.
- `ts` ends in `Z` or `+00:00`.

## What it does
- `parse_line` refuses a line of any other shape, order or verdict word. It also refuses a date or time that does not exist.
- `finding_ids` reads the ids of `<run>.json` in the result folder. A run with no readable result file is refused.
- `write_verdict` refuses a finding id that is not in that run. It also refuses a finding that already has a line.
- It amends the line onto the triage row (`--row <uuid>`) first. Then it appends the record to `verdicts.jsonl` in the result folder.
- A store that refuses the amend leaves the file unwritten, so the file and the row cannot disagree.
- `--file-only` writes the file alone, for a back-fill. The command needs exactly one of `--row` and `--file-only`.
- `LiveAmender` posts the line as the amendment note over HTTP, with the hooks' own client.
- Exit 0 means the line was written. Exit 3 means it was refused and nothing was written.

## Back-fill
- The 3 Nov run `2026-11-03-111218-hand` was back-filled file-only from the per-finding rulings of that day.
- It holds 41 lines: 4 `DUPLICATE` and 37 `DISTINCT`, so precision reads 4 of 41.
