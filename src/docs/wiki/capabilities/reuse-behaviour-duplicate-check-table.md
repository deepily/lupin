---
capability: reuse-behaviour-duplicate-check-table
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.reuse_behaviour.read_check_run@f2f83dca58
  - lupin_mcp.reuse_behaviour.read_check_runs@49ea76e6ce
  - lupin_mcp.reuse_behaviour.verdict_of@b3c292e804
  - lupin_mcp.reuse_behaviour.check_counts@c5d16404c4
  - lupin_mcp.reuse_behaviour.check_table@70e4afd275
---
# Reuse behaviour: the daily duplicate check table
`check_table` draws the `Daily duplicate check` table on the weekly page. It follows the audits. See [[reuse-behaviour-weekly-page]] and [[duplicate-check-daily-run]].

## What it does
- `read_check_runs` reads `<data dir>/duplicate-check-daily/<date>-<time>-<trigger>.json`; `--check-dir` moves the folder. It skips `last-success.json` and any other name. It keeps the runs whose `date` is in the week.
- A row is one run: date, trigger, commits judged, definitions judged, judge calls, minutes, findings, real duplicates, not duplicates, no verdict yet and precision. Commits judged is the window's commit count, 0 for a run with no window. Definitions judged is the check's `judged` count, the definitions it ruled on, so a window of 73 commits can show 100. A run that failed before judging shows 0 for definitions judged. A run with no findings is a row of zeros.
- The last row is `total`. Its precision comes from the summed counts, not from the rows. Precision is real out of real plus not, with a Wilson interval, and `n/a` when nothing is ruled.
- `verdict_of` takes a finding's own `verdict` field first, in any case. This is the form the report-only check can write.
- Otherwise it takes the last `VERDICT` word in the amendments of the finding's store row. The row is read by correlation key in every state, so held and closed rows count.
- `DUPLICATE` and `EXTEND` are real. `DISTINCT` is not. A finding with no word is counted under `no verdict yet`. So is one whose store read did not answer. Neither sits in precision.
- `check_counts` counts one run's findings by verdict.
- A result file that cannot be read is counted in the last row of `Left out of the week`. That means invalid JSON, a value that is not an object, or no readable `date`, `trigger`, `judge_calls` or `elapsed_seconds`.
- A run dated outside the week is in neither place.
