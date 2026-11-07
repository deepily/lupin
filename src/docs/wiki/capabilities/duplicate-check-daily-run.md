---
capability: duplicate-check-daily-run
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.duplicate_check_daily.Counting@006524b7c4
  - lupin_mcp.duplicate_check_daily.findings_of@25bb8dd399
  - lupin_mcp.duplicate_check_daily.failed_prerequisite@93f71d7cf3
  - lupin_mcp.duplicate_check_daily.run@1bc1cd0cef
  - lupin_mcp.duplicate_check_daily.cron_lines@2cb4000121
  - lupin_mcp.duplicate_check_daily.install_mode@628a527e77
  - lupin_mcp.duplicate_check_daily.live_parts@2818695534
  - lupin_mcp.duplicate_check_daily.live_filer@832dcfdc1a
  - lupin_mcp.duplicate_check_daily.live_auditor@46c2ce1135
  - lupin_mcp.duplicate_check_daily.main@d320aa5be8
  - lupin_mcp.duplicate_check_daily.record@0c6e420b03
  - lupin_mcp.duplicate_check_daily.rising_guard@12bac2b343
  - lupin_mcp.duplicate_check_daily.status_text@52fb6e12ce
  - lupin_mcp.duplicate_check_daily.limit_flag@4dc500630b
---
# Duplicate check daily: run, cron and live parts
The second half of `lupin_mcp.duplicate_check_daily`. The window is in [[duplicate-check-daily-window]]; rows are in [[duplicate-check-filing]].

## What it does
- `failed_prerequisite` checks, in order, that the embedding endpoint answers, the Claude binary reports a version and the frozen configuration matches the live one. It returns None or `{ prerequisite, detail }` for the first that fails.
- `Counting` wraps the judge backend and counts the calls made through it.
- `findings_of` makes one finding per new definition that sits in a cluster. `others` is the rest of the cluster. Without `session_of` the session is None.
- `run( root, now, trigger, cap, cli_path, parts, ... )` first runs the branch guard of [[duplicate-check-branch-guard]]. Then it writes `<date>-<time>-<trigger>.json` under `duplicate-check-daily` in the data folder. A trigger other than `cron`, `reboot` or `hand` raises `ValueError`.
- Before judging, a judge ledger written under another Claude Code version is renamed aside (see `rotate_ledger_for_new_cli` in [[duplicate-check-proof-command]]) and a new one started. The result then holds `ledger_rotated`. A failed prerequisite writes that file with status `failed` and changes nothing else.
- An error while reading the frozen configuration, choosing the window or making the worktree writes status `failed`, stage `setup`. An error while building the pool, embedding or judging writes stage `judging`. `last-success.json` does not move.
- Otherwise status is `ok`, or `carried` when the cap left definitions. `last-success.json` advances to the last commit fully judged.
- A filer or auditor that raises is caught and recorded as `filing` or `audit` with an `error`. The run still advances. The findings are kept in the file on every run; the weekly page counts them and [[duplicate-check-refile]] can file them again.
- With `ceiling` (`--ceiling N`, instead of `--cap`) the cap is the number of definitions to judge, up to N. That is the carried backlog plus the day's inflow. Finished calls are in the ledger, so nothing is paid for twice.
- With `baseline` (`--baseline`) the definitions are every one in the tree, drained over runs. `last-success.json` stays put; `baseline.json` says `in_progress` or `complete`, and a complete baseline judges nothing.
- `rising_guard` alerts through the notifier when the carried count rose on the last `--rise-limit` (3) measured daily runs. The result then holds `rising`.
- The detached worktrees are removed whether the run ends or fails.
- `record` writes the result file with `schema_version`, `started_at` and `mode`, and `None` for each measure a run that stopped early never reached. Then it appends the run's line to `runs.jsonl` (see [[duplicate-check-run-history]]).
- `cron_lines` returns two daily lines (12:07 and 18:07, trigger `cron`) and a reboot line 300 seconds after boot. `--with-baseline` adds a 20:07 line with `--baseline`. A branch other than `main` is added to every line as `--branch`, shell-quoted. `install_mode` prints, installs, removes or reports them through the librarian's locked crontab editor; `status_text` reads "installed" from three lines up.
- `live_parts` builds the real parts and makes no call. `live_filer` files rows over HTTP. `live_auditor` queues known-miss audits (see [[duplicate-check-audit]]), with no model call.
- `main` needs `--cap` or `--ceiling`, neither with a default, unless it only removes or reports the cron lines. It exits 3 when the branch guard refused, 1 when anything else failed, else 0. (argparse's usage errors are 2.)
- A night's findings are ruled on with verdict lines; the writer is described in [[duplicate-check-verdict-lines]].
