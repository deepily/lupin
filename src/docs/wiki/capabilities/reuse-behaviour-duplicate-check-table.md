---
capability: reuse-behaviour-duplicate-check-table
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.reuse_behaviour.read_check_run@bd18dcdd6c
  - lupin_mcp.reuse_behaviour.read_check_runs@49ea76e6ce
  - lupin_mcp.reuse_behaviour.read_verdicts@c77f258c07
  - lupin_mcp.reuse_behaviour.verdict_of@76b1955199
  - lupin_mcp.reuse_behaviour.settled_keys@18b2a24036
  - lupin_mcp.reuse_behaviour.check_counts@cac51a4e97
  - lupin_mcp.reuse_behaviour.ruled_cells@76f4abe943
  - lupin_mcp.reuse_behaviour.check_table@77c7638106
---
# Reuse behaviour: the daily duplicate check table
`check_table` draws the `Daily duplicate check` table on the weekly page. It follows the audits. See [[reuse-behaviour-weekly-page]] and [[duplicate-check-daily-run]].

## What it does
- `read_check_runs` reads `<data dir>/duplicate-check-daily/<date>-<time>-<trigger>.json`; `--check-dir` moves the folder. It skips `last-success.json` and any other name. It keeps the runs whose `date` is in the week.
- A row is one run: date, trigger, commits judged, definitions judged, judge calls, minutes, findings, real duplicates, not duplicates, no verdict yet and precision. Commits judged is the window's commit count, 0 for a run with no window. Definitions judged is the check's `judged` count, the definitions it ruled on, so a window of 73 commits can show 100. A run that failed before judging shows 0 for definitions judged. A run with no findings is a row of zeros.
- The last row is `total`. Its precision comes from the summed counts, not from the rows. Precision is real out of real plus not, with a Wilson interval, and `n/a` when nothing is ruled.
- `read_verdicts` reads `verdicts.jsonl` beside the result files, the file of [[duplicate-check-verdict-lines]]. It returns `{ ( run stem, finding id ): verdict }`, and the last line for a pair wins.
- A line in that file that is not a verdict record stops the page with exit 3 and the line number.
- `verdict_of` takes a finding's own `verdict` field first, in any case. This is the form the report-only check can write.
- Next it takes the finding's line in `verdicts.jsonl`, matched on the run's file stem and the finding's `id`. This costs no store read.
- Otherwise it takes the last `VERDICT` word in the amendments of the finding's store row. The row is read by correlation key in every state, so held and closed rows count.
- `DUPLICATE` and `EXTEND` are real. `DISTINCT` is not. A finding with no word is counted under `no verdict yet`. So is one whose store read did not answer. Neither sits in precision.
- `settled_keys( folder )` collects the correlation keys of the findings that have a verdict line, whatever the word. It looks each line's finding up in its run's result file. The key holds the definition's text hash, so changed code is a new key. A run file that cannot be read adds nothing. The daily check and [[duplicate-check-refile]] leave those findings out.
- `check_counts` counts one run's findings by verdict.
- `ruled_cells` gives the real, not and precision cells. A run that has findings and not one verdict shows `not triaged` in all three, never 0, because nobody has looked yet. A run with no findings is still zeros, and a run with some verdicts shows counts with the rest under `no verdict yet`. The total row follows the same rule over the whole week.
- A result file that cannot be read is counted in the last row of `Left out of the week`. That means invalid JSON, a value that is not an object, or no readable `date`, `trigger`, `judge_calls` or `elapsed_seconds`.
- A run dated outside the week is in neither place.
