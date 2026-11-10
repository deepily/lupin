---
capability: duplicate-check-status-rates
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.duplicate_check_status.measured_daily@72c9e84974
  - lupin_mcp.duplicate_check_status.baseline_remaining@b22bd8d786
  - lupin_mcp.duplicate_check_status.inflow_per_day@8b631961b3
  - lupin_mcp.duplicate_check_status.judged_per_day@88cfcf61ea
  - lupin_mcp.duplicate_check_status.projected_zero@65e3d3b0ae
  - lupin_mcp.duplicate_check_status.slipped@009bbbe098
  - lupin_mcp.duplicate_check_status.median_seconds_per_call@9bd7301eed
  - lupin_mcp.duplicate_check_status.per_day_usage@006d2f6a57
  - lupin_mcp.duplicate_check_status.installed_crons@05cf68552f
  - lupin_mcp.duplicate_check_status.expected_by@0b0ec8b700
  - lupin_mcp.duplicate_check_status.health_of@359f3dcf7e
---
# Duplicate check status: rates, health and the schedule
The first half of `lupin_mcp.duplicate_check_status`. Every function works only from the run-history lines ([[duplicate-check-run-history]]) and the clock. So the status page, the note after a run and the slip alert read the same numbers. A number the history cannot give is None, never a made-up zero. The page and the summary are in [[duplicate-check-status-snapshot]].

## Backlog and rates
- `measured_daily( lines )` keeps the daily-mode lines whose carried count is a measurement, oldest first. `baseline_remaining` is the newest measured baseline carried count, or None.
- `inflow_per_day( lines, now )` estimates new definitions a day. An arrival is a measured daily run's owed count less the carried count of the daily run before it, never below 0. It averages the days that have one within the last 7 days. A run with no owed count gives none.
- `judged_per_day( lines, now )` sums `judged` over every run of each calendar day in the last 3 days. It averages over the days that have a run.
- `projected_zero( backlog, drain, inflow, today )` is today when the backlog is 0. It is None when the backlog or the clearing rate is unknown, or when clearing less inflow is not above 0. Otherwise it is the date that many whole days ahead.
- `slipped( before, after )` is False with no earlier date. It is True when the later date is None or more than a day after the earlier one. The slip alert uses it ([[duplicate-check-daily-slots]]).
- `median_seconds_per_call( lines )` takes the last five lines that made at least 20 calls and recorded their time, failed runs left out. It returns the median of seconds over calls, or None.
- `per_day_usage( lines )` totals runs, judge calls, token counts and notional cost by calendar day, oldest first. A number no run recorded adds nothing; a day with none shows None.

## Health and schedule
- `installed_crons( crontab_text )` reads the five-field schedules off the lines that end with this job's tag. An `@reboot` line adds none. It gives an empty list for None or no tagged line.
- `expected_by( last, now, crons )` is the earliest firing of any schedule after the newest run, plus 30 minutes of grace. It is None when no schedule fires within a month, so lateness is then not judged.
- `health_of` answers `silent` with no run, or none started by that time. It answers `failing` when the newest run failed, `falling_behind` when a backlog exists and clearing does not beat inflow, else `healthy`.
