---
capability: duplicate-check-daily-slots
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.duplicate_check_daily.adaptive_run@9ef5851f1f
  - lupin_mcp.duplicate_check_daily.chunk_for@77597b14ca
  - lupin_mcp.duplicate_check_daily.announce@aca958e049
  - lupin_mcp.duplicate_check_daily.backoff_until@934c9d09e7
  - lupin_mcp.duplicate_check_daily.usage_since@b98940389b
  - lupin_mcp.duplicate_check_daily.live_noter@616613f854
  - lupin_mcp.duplicate_check_daily.live_urgent@6453f12e3d
  - lupin_mcp.duplicate_check_daily.live_rows_by_mark@afbe80fda0
  - lupin_mcp.duplicate_check_daily.finish@c3a210a521
  - lupin_mcp.duplicate_check_daily.run_lock@819b3ad17e
  - lupin_mcp.duplicate_check_daily.exit_code@5ef0282ce7
---
# Duplicate check daily: hourly slots, alerts and the run lock
The hourly mode of `lupin_mcp.duplicate_check_daily` (`--adaptive`), the alerts it sends and the lock that keeps two runs apart. The single run is in [[duplicate-check-daily-run]].

## Hourly slots
- `chunk_for( folder, ceiling )` sizes one slot's judge calls to fill 80 percent of an hour at the recent speed of a call. The speed is the median of the last five sizeable runs ([[duplicate-check-status-rates]]), or 3.5 seconds with none. The answer is at least 1 and at most the ceiling.
- `adaptive_run` runs a daily run with that chunk as its ceiling. A baseline run takes what is left only if all three hold. The daily run finished everything owed (`ok`). The baseline is not complete. At least 20 calls are left. A backed-off, failed or carried daily run is not followed by a baseline run. A baseline run that raises does not take the daily record with it. It is recorded as its own failed run: stage `baseline`, the error text, `judge_calls` None. The daily record and its last-success stand. `announce` and the job summary still happen, and `exit_code` reads 1.
- With nothing owed the daily run ends in seconds with no judge call. The two result files get distinct names, one second apart. `announce` runs once after both.
- `backoff_until( folder, now )` looks at the newest run that was not itself skipped. It returns that run's `backoff_until` when it is later than now, else None. A run that hits a rate limit sets it 90 minutes ahead, and the next slots are recorded `skipped`.
- `usage_since( before, after, calls )` is the difference of two usage tallies, with the cost rounded to four places. It returns None when calls were made and the SDK reported none, because then the tokens are unknown, not zero.

## Alerts and the summary
- `announce` sends an urgent alert for a failed run (a branch-guard refusal sent its own). It sends one for a rate limit and one for 20 or more calls that judged nothing. It sends one more when the projected zero date moves later by more than a day. A run that did something or left a backlog gets one low-priority note.
- A hook that is missing sends nothing, and one that raises is ignored, so a broken notifier never changes what a run recorded.
- `live_urgent` and `live_noter` send through `live_notifier` ([[duplicate-check-branch-guard]]) as an urgent alert and as a low-priority progress note.
- `live_rows_by_mark` counts the store rows whose key starts with the filer's prefix: `found`, held rows included, and `open`, those not done, dropped or wont_fix. It returns None when the store cannot be read in full, never a short count.
- `finish` rewrites the job summary after a run, using that count when the hook gives one. A failed write is printed to stderr and never fails the job ([[duplicate-check-status-snapshot]]).

## Lock and exit code
- `run_lock( data_dir )` takes an exclusive, non-waiting lock on `run.lock` in the check's folder. It yields True while held, or False at once when another live run holds it. The system drops the lock when its holder ends, so a killed run leaves nothing behind.
- `exit_code( docs )` is 3 when any run was refused by a guard, else 1 when any run failed, else 0.
