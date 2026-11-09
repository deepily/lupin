---
capability: duplicate-check-branch-guard
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.duplicate_check_daily.other_branches@92d9e02451
  - lupin_mcp.duplicate_check_daily.branch_guard@3f4d857df9
  - lupin_mcp.duplicate_check_daily.reinstall_command@e8cb2a2616
  - lupin_mcp.duplicate_check_daily.refusal_message@91639bbf76
  - lupin_mcp.duplicate_check_daily.live_notifier@b8141a2be0
  - lupin_mcp.duplicate_check_daily.baseline_installed@653a48e405
---
# Duplicate check daily: the branch guard
The cron lines are pinned to one branch with `--branch <name>`. The run itself is in [[duplicate-check-daily-run]].

## Why it exists
When a new working branch starts, the pinned one goes quiet and a plain run would report a clean, empty day. A person must then reinstall the lines for the new branch. The guard is what tells you.

## What it does
- `other_branches( root, branch )` lists the local branches under `refs/heads`, leaving out `main` and the pinned one. The newest tip comes first, and ties go by name.
- `branch_guard( root, branch, now )` runs first in `run`, ahead of the prerequisites. It returns None or a refusal.
- `stale_branch`: the pinned tip is 3 days old or older (`STALE_DAYS`) and another local branch has a newer commit.
- `missing_branch`: the pinned name resolves to no commit.
- An old pin with nothing newer beside it is not refused. `main` is never named as the branch to move to, and a pin of `main` is judged like any other.
- A refusal writes the result file with status `failed`, stage `branch_guard`, the refusal, the branch, the newest branch and its time, `reinstall` and `notified`. `reinstall` is None when no other branch exists.
- Nothing is judged and `last-success.json` does not move. `main` exits 3, which differs from 1 (failed) and 2 (usage).
- `reinstall_command` builds the text that moves the check to the newest branch. It names a registry edit of `--branch` in the duplicate-check entry. It adds the `cron_generate --install` command for a changed schedule. The cron lines read the registry when they run.
- `refusal_message` makes the spoken line and the card text.
- `live_notifier` sends one high priority alert through `/api/notify` and returns True on HTTP 200. It never raises.
- A missing or raising notifier leaves `notified` False. The file and the exit code still say it.
- Every day's run repeats the refusal and the alert until someone reinstalls or uninstalls.
