---
capability: duplicate-check-daily-run
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.duplicate_check_daily.Counting@b972f2d227
  - lupin_mcp.duplicate_check_daily.findings_of@cfdb1b0bd4
  - lupin_mcp.duplicate_check_daily.failed_prerequisite@93f71d7cf3
  - lupin_mcp.duplicate_check_daily.run@0e3d95bce3
  - lupin_mcp.duplicate_check_daily.cron_lines@5d30783eec
  - lupin_mcp.duplicate_check_daily.install_mode@7596ab9118
  - lupin_mcp.duplicate_check_daily.live_parts@d30d313817
  - lupin_mcp.duplicate_check_daily.live_filer@832dcfdc1a
  - lupin_mcp.duplicate_check_daily.live_auditor@4cc714910e
  - lupin_mcp.duplicate_check_daily.main@7182ace7dc
  - lupin_mcp.duplicate_check_daily.record@0c6e420b03
  - lupin_mcp.duplicate_check_daily.rising_guard@9bf675aa57
  - lupin_mcp.duplicate_check_daily.limit_flag@4dc500630b
---
# Duplicate check daily: run, cron and live parts
The second half of `lupin_mcp.duplicate_check_daily`. The window is in [[duplicate-check-daily-window]]; rows are in [[duplicate-check-filing]]; the hourly slots, back-off and lock are in [[duplicate-check-daily-slots]].

## What it does
- `failed_prerequisite` checks, in order, that the embedding endpoint answers, the Claude binary reports a version and the frozen configuration matches the live one. It returns None or `{ prerequisite, detail }` for the first that fails.
- `Counting` wraps the judge backend and counts the calls. After a rate or usage limit refusal it counts that in `limited` and refuses every later call of the run at once.
- `findings_of` makes one finding per cluster that holds a new definition: the new definition with the lowest id, with `others` the rest. A cluster is left out when any of its new definitions already has a verdict line, so a verdict on either side settles the pair. Without `session_of` the session is None.
- `run( root, now, trigger, cap, cli_path, parts, ... )` first runs the guards of [[duplicate-check-branch-guard]]. It then writes `<date>-<time>-<trigger>.json` under `duplicate-check-daily`. A trigger other than `cron`, `reboot` or `hand` raises `ValueError`.
- A complete baseline judges nothing. A run inside a rate-limit back-off is recorded `skipped` and judges nothing. A failed prerequisite writes status `failed` and changes nothing else.
- A judge ledger written under another Claude Code version is renamed aside (see `rotate_ledger_for_new_cli` in [[duplicate-check-proof-command]]); the result then holds `ledger_rotated`.
- An error while reading the configuration, choosing the window or making the worktree writes status `failed`, stage `setup`. An error while building the pool, embedding or judging writes stage `judging`. `last-success.json` does not move. Worktrees are removed either way.
- The result holds `test_code_dropped` with `owed` and `pool`: the test-code definitions left out of the owed set and of the comparison pool.
- Otherwise status is `ok`, or `carried` when the cap left definitions. `last-success.json` advances to the last commit fully judged and records the branch.
- A filer or auditor that raises is caught and recorded with an `error`; the run still advances. Findings stay in the result file, and [[duplicate-check-refile]] can file them again.
- With `ceiling` (`--ceiling N`) the cap is the number of definitions to judge, up to N. With `baseline` (`--baseline`) the definitions are every one in the tree, drained over runs; `baseline.json` says `in_progress` or `complete`.
- `rising_guard` alerts through the notifier when the carried count rose on the last `--rise-limit` (3) measured daily runs. It alerts on the first crossing only; later runs hold `rising` with `repeat`.
- `record` adds `schema_version`, `started_at` and `None` for each measure the run never reached, writes the file, then appends the run's line to `runs.jsonl` ([[duplicate-check-run-history]]).
- `limit_flag` gives `--ceiling N` when a ceiling is set, else `--cap N`. The cron lines use it.
- `cron_lines` returns a 10:00 daily line and a reboot line 300 seconds after boot, which catches up from the last successful run. `--with-baseline` adds an 11:07 line. With `adaptive` it returns an hourly line (10:00 to 22:00) and the reboot line, both with `--adaptive`. A branch other than `main` is added as `--branch`.
- `install_mode` handles `--print-install`, `--uninstall` and `--status` through the librarian's locked crontab editor. `--install` is retired: it prints the `cron_generate` command, which writes every cron line now.
- `live_parts` builds the real parts without a call. `live_filer` files the triage rows over HTTP; `live_auditor` queues known-miss audits ([[duplicate-check-audit]]) with no model call. It names each finding by its id in the symbol index the sweep reads. That is not the checker's own `d-` id, so the sweep knows every queued item.
- `main` needs `--cap` or `--ceiling`, unless it only removes or reports the cron lines. `--adaptive` needs `--ceiling`. Verdict lines are in [[duplicate-check-verdict-lines]].
