---
capability: duplicate-check-daily-run
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.duplicate_check_daily.Counting@006524b7c4
  - lupin_mcp.duplicate_check_daily.findings_of@25bb8dd399
  - lupin_mcp.duplicate_check_daily.failed_prerequisite@93f71d7cf3
  - lupin_mcp.duplicate_check_daily.run@c271ba4808
  - lupin_mcp.duplicate_check_daily.cron_lines@2f36b1fdd1
  - lupin_mcp.duplicate_check_daily.install_mode@29fb4b6ed4
  - lupin_mcp.duplicate_check_daily.live_parts@e52091d0c2
  - lupin_mcp.duplicate_check_daily.live_filer@832dcfdc1a
  - lupin_mcp.duplicate_check_daily.live_auditor@46c2ce1135
  - lupin_mcp.duplicate_check_daily.main@6a402753b1
---
# Duplicate check daily: run, cron and live parts
The second half of `lupin_mcp.duplicate_check_daily`. The window is in [[duplicate-check-daily-window]]; rows are in [[duplicate-check-filing]].

## What it does
- `failed_prerequisite` checks, in order, that the embedding endpoint answers, the Claude binary reports a version and the frozen configuration matches the live one. It returns None or `{ prerequisite, detail }` for the first that fails.
- `Counting` wraps the judge backend and counts the calls made through it.
- `findings_of` makes one finding per new definition that sits in a cluster. `others` is the rest of the cluster. Without `session_of` the session is None.
- `run( root, now, trigger, cap, cli_path, parts, ... )` writes `<date>-<time>-<trigger>.json` under `duplicate-check-daily` in the data folder. A trigger other than `cron`, `reboot` or `hand` raises `ValueError`.
- A failed prerequisite writes that file with status `failed` and changes nothing else.
- An error while building the pool, embedding or judging writes status `failed`, stage `judging`. `last-success.json` does not move.
- Otherwise status is `ok`, or `carried` when the cap left definitions. `last-success.json` advances to the last commit fully judged.
- A filer or auditor that raises is caught and recorded as `filing` or `audit` with an `error`. The run still advances.
- When a filer is present, the findings are kept in the file so [[duplicate-check-refile]] can file them again.
- The detached worktrees are removed whether the run ends or fails.
- `cron_lines` returns a daily line at 12:07 and a reboot line 300 seconds after boot. `install_mode` prints, installs, removes or reports them through the librarian's locked crontab editor.
- `live_parts` builds the real parts and makes no call. `live_filer` files rows over HTTP. `live_auditor` queues known-miss audits (see [[duplicate-check-audit]]), with no model call.
- `main` needs `--cap`, which has no default, unless it only removes or reports the cron lines. It exits 1 when status is `failed`, else 0.
