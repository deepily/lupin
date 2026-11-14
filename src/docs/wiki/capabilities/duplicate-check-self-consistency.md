---
capability: duplicate-check-self-consistency
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.duplicate_check_self_consistency.own_lines@f9690710b3
  - lupin_mcp.duplicate_check_self_consistency.sample_ids@c36476c3fc
  - lupin_mcp.duplicate_check_self_consistency.runs_of@d061a1ffeb
  - lupin_mcp.duplicate_check_self_consistency.flagged_by_definition@2c18c7f7cd
  - lupin_mcp.duplicate_check_self_consistency.flagged_pairs@bf7b425fca
  - lupin_mcp.duplicate_check_self_consistency.compare@60d8ffad6a
  - lupin_mcp.duplicate_check_self_consistency.render@337a8fb1ee
  - lupin_mcp.duplicate_check_self_consistency.rejudge_run@4133a59e3f
  - lupin_mcp.duplicate_check_self_consistency.second_pass@085a3e3650
  - lupin_mcp.duplicate_check_self_consistency.live_run@7772ac309d
  - lupin_mcp.duplicate_check_self_consistency.main@a797c91fb2
---
# Duplicate check self-consistency
Asks whether the interim judge gives the same answer twice. It draws a seeded sample of definitions the model judged itself, judges them again on a second slot, and compares the two passes. Without `--go` it prints the sample and the plan and makes no call. The weekly flag rates are in [[duplicate-check-drift-report]]; the same code judges a sample with another model in [[duplicate-check-sample-rejudge]]; the run it re-judges is in [[duplicate-check-daily-run]].

## What it does
- `own_lines` reads `interim-judge-manifest.jsonl` and keeps, for each definition, the last line whose `model_id` is the model and which has no `reused_from_model`. `sample_ids` draws up to 30 of them without replacement, sorted first, so the same folder, model, size and seed give the same sample. The seed defaults to the date, so each week draws its own.
- `runs_of` groups the sample by the result file of the run that judged it.
- `rejudge_run` rebuilds one run from its window in a worktree of its own and removes the worktree afterwards, even after an error. A baseline run takes every definition of the tree, as the baseline did; a daily run takes the definitions new in its window.
- Pass one replays slot 0 from the judge ledger with no call allowed. Pass two judges the second slot with up to the cap. A sampled definition that the window no longer yields, or that a pass left unjudged, is left out and named.
- `flagged_by_definition` says whether a definition has any flagged row, and `flagged_pairs` lists the flagged definition and candidate pairs. `compare` counts the four cells over the definitions both passes hold: flagged both times, first pass only, second pass only, neither. It returns the agreement, kappa and the exact McNemar p.
- `second_pass` bounds all the runs by the calls left in the day's budget, then appends one history line, mode `self-consistency`, with the calls made. The line is written even when a later run file raises, with status `failed` and the calls made so far. A model other than the interim one can make the second pass, and then the budget and the history line name that model.
- `live_run` takes the daily check's run lock first and raises when another run holds it. `main` prints the plan or, with `--go` and `--claude-cli-path`, the comparison. It returns 3 with the reason when the model key, the sample, the lock or the budget refuses.

## Limits
- Calls made inside a run file that raises are not counted in the history line.
- It has not been run live. Until then the plan is the only output.
