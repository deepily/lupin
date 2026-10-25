---
capability: seat-teardown-and-liveness
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.agents.shared.seat_teardown.main@47b8bf9ed8
  - cosa.agents.shared.seat_teardown.summarise_outcome@8be37bcfb4
  - cosa.agents.shared.seat_teardown.teardown_notice@6a91f637ac
  - cosa.agents.shared.worktree_reaper.seat_is_alive@e070303306
  - cosa.agents.shared.worktree_reaper.live_process_cwds@f237252ada
  - cosa.agents.shared.worktree_reaper.cwd_inside@f7f0efddaa
  - cosa.agents.shared.worktree_context.WorktreeCollisionError@0f0064309e
---
# Seat teardown and liveness

A seat removes its own worktree and merged branch when it ends. The janitor uses the same liveness test to decide whether a seat-locked tree is still in use. See [[worktree-lifecycle]].

## What it does
- `seat_teardown.main` is the command line door for the session-end hook. It takes `--path`, `--seat` and `--wait-seconds`.
- `main` prints the teardown result as one JSON line and exits 0 whatever the verdict. A kept tree is a report, not a failure.
- `summarise_outcome` cuts a teardown result's `ignored_blockers` and `errors` to a count and the first ten entries, and keeps every other key. A non-dict result is returned as it was.
- `teardown_notice` returns one sentence naming each seat whose tree was kept, with its reason and path.
- `teardown_notice` returns `None` when every tree was removed or was never a seat tree.
- `live_process_cwds` reads `/proc` once and returns the set of working directories of live processes.
- `cwd_inside` is true when any of those directories is the path itself or below it. A sibling with a similar name does not count.
- `seat_is_alive` is false only when tmux reports the session absent and `/proc` was readable. No process may stand inside the tree.
- `WorktreeCollisionError` is raised when the target worktree path already exists on entry.

## Invariants
- Liveness fails closed. Any error, or an unreadable `/proc`, reads as alive and the tree is kept.
- Teardown keeps a tree with uncommitted edits, ignored data files or commits the working branch lacks.
- It removes a clean, merged tree without `--force`, and deletes its branch with `git branch -d`.
