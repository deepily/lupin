---
capability: duplicate-check-branch-guard
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.duplicate_check_daily.other_branches@92d9e02451
  - lupin_mcp.duplicate_check_daily.branch_guard@3f4d857df9
  - lupin_mcp.duplicate_check_daily.continuity_guard@e6fc5a4f1c
  - lupin_mcp.duplicate_check_daily.resolve_branch@9a4142b845
  - lupin_mcp.duplicate_check_daily.reinstall_command@8bfd412466
  - lupin_mcp.duplicate_check_daily.refusal_message@cbdcf6a0b1
  - lupin_mcp.duplicate_check_daily.live_notifier@0be36b1b8e
  - lupin_mcp.duplicate_check_daily.baseline_installed@a2a6e85774
---
# Duplicate check daily: the branch guards
The cron lines are pinned to one branch with `--branch <name>`. The run itself is in [[duplicate-check-daily-run]].

## Why it exists
When a new working branch starts, the pinned one goes quiet and a plain run would report a clean, empty day. A person must then move the pin to the new branch. The guards are what tell you.

## What it does
- `resolve_branch( root, name )` turns `--branch` into a branch name. `auto` picks the local `wip-*` branch with the newest tip (ties by name), else `main`. Any other name is used as given.
- `other_branches( root, branch )` lists the local branches under `refs/heads`, leaving out `main` and the pinned one. The newest tip comes first, and ties go by name.
- `branch_guard( root, branch, now )` runs first in `run`, ahead of the prerequisites. It returns None or a refusal.
- `stale_branch`: the pinned tip is 3 days old or older (`STALE_DAYS`) and another local branch has a newer commit.
- `missing_branch`: the pinned name resolves to no commit.
- An old pin with nothing newer beside it is not refused. `main` is never named as the branch to move to, and a pin of `main` is judged like any other.
- `continuity_guard( root, branch, previous, commit )` refuses a run that would carry another branch's progress onto this one. `branch_changed`: the branch recorded in `last-success.json` or `baseline.json` is not this one. `commit_not_on_branch`: the last judged commit is not an ancestor of the branch tip. A record with no branch, written before branches were kept, is not refused.
- A refusal writes the result file with status `failed`, stage `branch_guard`, the refusal, the branch, `reinstall` and `notified`. `reinstall` is None when no other branch exists.
- Nothing is judged and `last-success.json` does not move. `main` exits 3, which differs from 1 (failed) and 2 (usage).
- `reinstall_command` builds the text that moves the check to the newest branch. It names a registry edit of `--branch` in the duplicate-check entry, and the librarian tick's install command (`install_command` in [[repo-tools-symindex-librarian-tick-config]]) for a changed schedule. The cron lines read the registry when they run. `baseline_installed` says whether the crontab holds the baseline line.
- `refusal_message` makes the spoken line and the card text, including the two continuity cases. Either keep the old branch in the registry, or delete the two progress files to start fresh.
- `live_notifier` sends one alert through `/api/notify`, high priority unless told otherwise, and returns True on HTTP 200. It never raises.
- A continuity refusal goes through the urgent hook and is not sent again while the next run refuses the same way. A stale or missing branch repeats the alert every run until someone moves the pin.
- A missing or raising notifier leaves `notified` False. The file and the exit code still say it.
