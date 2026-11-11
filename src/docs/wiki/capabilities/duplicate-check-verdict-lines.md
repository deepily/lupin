---
capability: duplicate-check-verdict-lines
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.duplicate_check_verdicts.parse_line@aaba3c7c88
  - lupin_mcp.duplicate_check_verdicts.finding_ids@2bce6f3244
  - lupin_mcp.duplicate_check_verdicts.VerdictRefused@8abf07bd31
  - lupin_mcp.duplicate_check_verdicts.put_back@9629c3aa81
  - lupin_mcp.duplicate_check_verdicts.write_verdict@cb725534b7
  - lupin_mcp.duplicate_check_verdicts.main@27ac48a8ed
  - lupin_mcp.duplicate_check_verdicts.seat_actor@e2029f1991
  - lupin_mcp.duplicate_check_verdicts.SeatStore@e1fe8da4c8
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
- `write_verdict` refuses a finding id that is not in that run. It also refuses a finding that already has a line, unless `correct` is set.
- A correction (`--correct`) is the same line shape with its own `by=` and `ts=`. It is appended after the earlier line, which stays. The record also carries `corrects`, the verdict it replaces, and the row amend adds `corrects=<verdict>`. It refuses a finding with no earlier line, and a verdict equal to the one it replaces. A finding may be corrected again. Every reader takes the last line per finding, so the weekly page and the settled keys follow the correction.
- It appends the record to `verdicts.jsonl` in the result folder first. Then it amends the line onto the triage row (`--row <uuid>`).
- If the amend is refused or raises, `put_back` cuts the file to its earlier size, or removes it if it was new. It returns the error text instead of raising, so the refusal still reaches the caller. The file is put back as it was, so the file and the row cannot disagree.
- A file that cannot be written is refused with the row untouched. Every refusal names what was and was not written.
- `--file-only` writes the file alone, for a back-fill. The command needs exactly one of `--row` and `--file-only`.
- The amend goes through `LiveStore.amend` of [[duplicate-check-filing]], the hooks' own client over HTTP. A live `--row` amend uses `SeatStore`. It is a `LiveStore` whose every amend carries the calling seat as its `actor`, because the store refuses an amend with none.
- `seat_actor` names that seat the way the `task_amend` tool does: `<persona key> <8-hex session id>`, read from the session bridge. It raises `VerdictRefused` when the session id came from a fallback, which could name another seat. It also raises when the bridge holds no voice persona for the session.
- Exit 0 means the line was written. Exit 3 means it was refused and nothing was written.

## Back-fill
- The 3 Nov run `2026-11-03-111218-hand` was back-filled file-only from the per-finding rulings of that day.
- It holds 41 lines: 4 `DUPLICATE` and 37 `DISTINCT`, so precision reads 4 of 41.
