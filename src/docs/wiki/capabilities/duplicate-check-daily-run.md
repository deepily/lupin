---
capability: duplicate-check-daily-run
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.duplicate_check_daily.Counting@f2ca3e39f1
  - lupin_mcp.duplicate_check_daily.findings_of@cfdb1b0bd4
  - lupin_mcp.duplicate_check_daily.failed_prerequisite@63584b8a94
  - lupin_mcp.duplicate_check_daily.run@df142a5380
  - lupin_mcp.duplicate_check_daily.cron_lines@5d30783eec
  - lupin_mcp.duplicate_check_daily.install_mode@8a07fed64c
  - lupin_mcp.duplicate_check_daily.live_parts@d30d313817
  - lupin_mcp.duplicate_check_daily.live_filer@ae7b324cde
  - lupin_mcp.duplicate_check_daily.live_auditor@4cc714910e
  - lupin_mcp.duplicate_check_daily.main@183e409cd2
  - lupin_mcp.duplicate_check_daily.resolve_ceiling@8514765a03
  - lupin_mcp.duplicate_check_daily.append_manifest@25912ae6d8
  - lupin_mcp.duplicate_check_daily.record@0c6e420b03
  - lupin_mcp.duplicate_check_daily.rising_guard@9bf675aa57
  - lupin_mcp.duplicate_check_daily.limit_flag@4dc500630b
---
# Duplicate check daily: run, cron and live parts
The second half of `lupin_mcp.duplicate_check_daily`. The window is in [[duplicate-check-daily-window]]; rows are in [[duplicate-check-filing]]; the hourly slots, back-off and lock are in [[duplicate-check-daily-slots]].

## What it does
- `failed_prerequisite` checks, in order, that the embedding endpoint answers, the Claude binary reports a version and the frozen configuration matches the live one. A judge model with no frozen file fails the third. It returns None or `{ prerequisite, detail }` for the first that fails.
- `Counting` wraps the judge backend and counts the calls. After a rate or usage limit refusal it counts that in `limited` and refuses every later call of the run at once. Any failed call, a limited one included, is counted in `failed`.
- `findings_of` makes one finding per cluster that holds a new definition: the new definition with the lowest id, with `others` the rest. A cluster is left out when any of its new definitions already has a verdict line, so a verdict on either side settles the pair. Without `session_of` the session is None.
- `run( root, now, trigger, cap, cli_path, parts, ... )` first runs the guards of [[duplicate-check-branch-guard]]. It then writes `<date>-<time>-<trigger>.json` under `duplicate-check-daily`. A trigger other than `cron`, `reboot` or `hand` raises `ValueError`.
- A run whose every new call failed, with no limit to explain it, is recorded `failed`. Rulings replayed from the ledger do not hide it. A limited run stays `carried`. A complete baseline judges nothing. A run inside a rate-limit back-off is recorded `skipped` and judges nothing. A failed prerequisite writes status `failed` and changes nothing else.
- The judge ledger survives a Claude Code update; see [[duplicate-check-daily-ledger]]. No ledger is renamed aside.
- An error while reading the configuration, choosing the window or making the worktree writes status `failed`, stage `setup`. An error while building the pool, embedding or judging writes stage `judging`. `last-success.json` does not move. Worktrees are removed either way. The result holds `test_code_dropped` with `owed` and `pool`: the test-code definitions left out of the owed set and of the comparison pool.
- Otherwise status is `ok`, or `carried` when the cap left definitions. `last-success.json` advances to the last commit fully judged and records the branch. `append_manifest` writes one line per judged definition to `interim-judge-manifest.jsonl` through `append_line` of [[duplicate-check-run-history]]. A line holds the id, file, run file, model id, config sha and time, and each finding carries `judge_model`.
- A filer or auditor that raises is caught and recorded with an `error`; the run still advances. Findings stay in the result file, and [[duplicate-check-refile]] can file them again.
- With `ceiling` (`--ceiling N`) the cap is the number of definitions to judge, up to N. `limit_flag` gives `--ceiling N` when a ceiling is set, else `--cap N`, for the cron lines. With `baseline` (`--baseline`) the definitions are every one in the tree, drained over runs; `baseline.json` says `in_progress` or `complete`.
- `rising_guard` alerts through the notifier when the carried count rose on the last `--rise-limit` (3) measured daily runs. It alerts on the first crossing only; later runs hold `rising` with `repeat`.
- `record` adds `schema_version`, `started_at` and `None` for each measure the run never reached, writes the file, then appends the run's line to `runs.jsonl` ([[duplicate-check-run-history]]).
- `cron_lines` returns a 10:00 daily line and a reboot line 300 seconds after boot, which catches up from the last successful run. `--with-baseline` adds an 11:07 line. With `adaptive` it returns an hourly line (10:00 to 22:00) and the reboot line, both with `--adaptive`. A branch other than `main` is added as `--branch`.
- `install_mode` handles `--print-install`, `--uninstall` and `--status` through the librarian's locked crontab editor. `--install` is retired: it prints where the installer went on stderr and returns 1, because `cron_generate` writes every cron line now. The cron work is done by `manage_cron` of [[repo-tools-symindex-librarian-tick-run]].
- `live_parts` builds the real parts without a call. `live_filer` files the run's one triage row over HTTP, with the configured `duplicate check triage owner` and the project's manager roster. It raises `NoTriageOwner` when there are findings and the owner is unset or not on the roster. The findings stay in the result file for a refile, and `run` records that as the filer's error. `live_auditor` queues known-miss audits ([[duplicate-check-audit]]) with no model call. It names each finding by its id in the symbol index the sweep reads. That is not the checker's own `d-` id, so the sweep knows every queued item.
- `main` takes at most one of `--cap` and `--ceiling`. With neither, `resolve_ceiling` reads the lupin ceiling key; a blank or invalid key refuses the run naming it. A flag wins over the key. `--adaptive` needs a ceiling. Verdict lines are in [[duplicate-check-verdict-lines]].
