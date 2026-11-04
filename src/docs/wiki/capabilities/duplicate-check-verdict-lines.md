---
capability: duplicate-check-verdict-lines
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.duplicate_check_verdicts.parse_line@aaba3c7c88
  - lupin_mcp.duplicate_check_verdicts.finding_ids@2bce6f3244
  - lupin_mcp.duplicate_check_verdicts.VerdictRefused@8abf07bd31
  - lupin_mcp.duplicate_check_verdicts.put_back@9629c3aa81
  - lupin_mcp.duplicate_check_verdicts.write_verdict@f1844da0d1
  - lupin_mcp.duplicate_check_verdicts.main@6507b26c37
---
# Duplicate check: verdict lines and their writer
The triage seat rules on each finding of a run with one line. `python -m lupin_mcp.duplicate_check_verdicts` writes it. The run is in [[duplicate-check-daily-run]]. The weekly page that counts the lines is in [[reuse-behaviour-duplicate-check-table]].

## The line
`DUPCHECK-VERDICT run=<result file stem> finding=<findings[].id> verdict=DUPLICATE|EXTEND|DISTINCT class=<kebab-case reason> by=<persona key> ts=<ISO-8601 UTC>`
- The fields are space-separated `key=value` pairs in that order, with no spaces inside a value.
- `DUPLICATE` and `EXTEND` count as real on the weekly page. `DISTINCT` counts as not. `class` is free text for now.
- `ts` ends in `Z` or `+00:00`.

## What it does
- `VerdictRefused` (a `ValueError`) carries every refusal, with the reason in its message.
- `parse_line` refuses a line of any other shape, order or verdict word. It also refuses a date or time that does not exist.
- `finding_ids` reads the ids of `<run>.json` in the result folder. A run with no readable result file is refused.
- `write_verdict` refuses a finding id that is not in that run. It also refuses a finding that already has a line.
- It appends the record to `verdicts.jsonl` in the result folder first. Then it amends the line onto the triage row (`--row <uuid>`).
- If the amend is refused or raises, `put_back` cuts the file to its earlier size, or removes it if it was new. It returns the error text instead of raising, so the refusal still reaches the caller. The file is put back as it was, so the file and the row cannot disagree.
- A file that cannot be written is refused with the row untouched. Every refusal names what was and was not written.
- `--file-only` writes the file alone, for a back-fill. The command needs exactly one of `--row` and `--file-only`.
- The amend goes through `LiveStore.amend` of [[duplicate-check-filing]], the hooks' own client over HTTP.
- Exit 0 means the line was written. Exit 3 means it was refused and nothing was written.

## Back-fill
- The 3 Nov run `2026-11-03-111218-hand` was back-filled file-only from the per-finding rulings of that day.
- It holds 41 lines: 4 `DUPLICATE` and 37 `DISTINCT`, so precision reads 4 of 41.
