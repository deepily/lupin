---
capability: duplicate-check-daily-budget
pin_algorithm: py3.13.x095bff/ts5.9.3
pins:
  - lupin_mcp.duplicate_check_daily.calls_left@0ae75e1843
  - lupin_mcp.duplicate_check_daily.SpendRefused@71a0de09ed
  - lupin_mcp.duplicate_check_history.calls_on@7b43c5f0c9
  - cosa.repo.code_health_settings.daily_call_budget@0abcde900c
---
# Duplicate check daily budget
A daily limit on the judge calls the check may start, one figure per model. It sits above the per-run ceiling of [[duplicate-check-daily-slots]]. The run it guards is in [[duplicate-check-daily-run]].

## What it does
- `daily_call_budget( config, model )` reads the INI key `duplicate check daily call budget`, comma-separated `<model id>=<calls>` pairs. It returns the calls listed for that model.
- A blank key, a bad pair, a repeated model or a count below one raises `CodeHealthSettingError` naming the key. A model the key does not list raises too, so a model with no budget does not run.
- `calls_on( lines, day, model )` sums `judge_calls` over the history lines that started on one date and name that model. A line naming no model counts against every model.
- `calls_left( folder, parts, model, now )` returns the budget minus today's calls, failed calls included. It reads the budget from `parts[ "config" ]`, else the live INI.
- A spent budget raises `SpendRefused`. `run` catches it after the frozen configuration is verified and before any pool or worktree work.
- The slot is then recorded `skipped` with a note, `judge_calls` 0 and `judge_model`. Nothing moves and no call is made.
- A missing or bad budget fails the run at stage `setup`, naming the key.
- Otherwise the run's cap is lowered to the calls left, so one run cannot overspend the day.
- Every result file and history line carries `judge_model`; see [[duplicate-check-run-history]].

## Limits
- A run killed mid-judge leaves no history line, so its calls are not counted. The host powers off nightly.
- Two overlapping runs can both read the history before either writes. The run lock of [[duplicate-check-daily-slots]] stops a second run only while the first holds it.
- History lines written before `judge_model` existed name no model. They count against every model, so a day that holds them can read as spent.
