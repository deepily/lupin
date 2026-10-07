---
capability: worktree-lifecycle
pin_algorithm: py3.13.xf75af6/ts5.9.3
pins:
  - cosa.utils.seat_worktree.provision_seat_worktree@eed42d08b9
  - cosa.utils.worktree_artifacts.provision_worktree_artifacts@fd62ae8430
  - cosa.agents.shared.worktree_context.WorktreeContext@f26451f4ff
  - cosa.agents.shared.seat_teardown.retire_seat_worktree@ec2c282603
  - cosa.agents.shared.worktree_reaper.drain_then_remove@7a42533c79
  - cosa.agents.shared.worktree_reaper.reconcile_worktrees@d7ff867a1c
  - cosa.agents.shared.worktree_reaper.sweep_merged_branches@02e1d8c83d
  - cosa.agents.shared.worktree_refusal_ledger.report_refusals@08e4b0b1dd
  - cosa.agents.shared.worktree_straggler_tickets.sync_straggler_tickets@197e32f45b
---
# Worktree lifecycle

Git worktrees are made for each spawned seat and for each BFE or TFE job. They are removed by the seat teardown, the reaper and the arbiter's janitor. Seat trees live under the main checkout's `.claude/worktrees`. The job sandbox root is an INI value that ships as `.claude/worktrees`. The fix pipelines that use them are [[fix-expediter-bfe]] and [[fix-expediter-tfe]]. The janitor runs inside the [[heartbeat-arbiter]].

## Making a tree
- `provision_seat_worktree` runs `provision-seat-worktree.sh`. That script adds `.claude/worktrees/seat-<slug>` with `git worktree add --detach` at the main checkout's HEAD and locks it as `lupin-seat:<seat name>`.
- It reuses a registered tree but answers `occupied` when a process has its working directory inside, or the tree is dirty with no newer memento. `spawn_sessions` then tries the next index.
- If provisioning fails, the seat runs in the spawn's own work directory.
- `provision_worktree_artifacts` symlinks `node_modules`, `src/scripts/cloud-run.env` and the Terraform providers cache from the main checkout. Nothing else is linked, and a missing source is reported but does not fail the script.
- `WorktreeContext` is an async context manager that BFE and TFE use. It adds `<sandbox root>/<job id>` from the base ref, raises `WorktreeCollisionError` if that path exists, and then links the venv and artifacts.
- The INI ships `cosa worktree enabled` true and `auto cleanup` false. So these job trees stay after exit, and the exit never swallows the caller's exception.

## Retiring a seat's tree
- `retire_seat_worktree` keeps the tree if it is the main one or lacks this seat's lock. It also keeps it if the seat is still alive after the wait, 10 seconds by default and 120 from the SessionEnd hook. It keeps it with uncommitted work, an unmerged branch, or other ignored files. Build artifacts, mirrored mementos and the tree's own run output do not count: `tmp/`, `io/test-suite/`, `io/swe-team/`, `io/claude_code_hooks/`, `src/docs/index/`, `.claude-session.md`.
- Otherwise it unlocks and runs `git worktree remove` without force, re-locking on failure. A seat tree is detached, so usually there is no branch. A merged, unprotected branch is deleted with `git branch -d`.
- The SessionEnd hook runs it detached for a seat under `.claude/worktrees/`, but not on clear or compact.
- `dismiss_sessions` is meant to call it after a reap. It passes the session name and the directory in the wrong order, so that door keeps the tree without a notice (store id 74c1bf37-a3b3-4c3a-90db-5a5f05dcd084).

## Reaper and janitor
- `drain_then_remove` puts a detached HEAD on a `wt-rescue/` branch and commits a dirty tree as a WIP commit. It then runs `git worktree remove`, and refuses on ignored files unless given an evacuation root. The same three classes (artifacts, run output, mirrored mementos) are exempt there.
- `reconcile_worktrees` supplies that root, `io/worktree-evacuated`. It skips the main tree, trees outside the sandbox, non-seat locks, live seats, trees a live process has as its cwd, and recently active trees.
- An unmerged branch is archived under `refs/archive/<date>/`. Archive refs and evacuation folders older than 14 days are deleted.
- The janitor ships on, with a 6 hour age threshold and the repos `lupin`, `lupin-mobile` and `planning-is-prompting`. It runs each poll.
- `report_refusals` records refused trees in `io/worktree-janitor/refused.json`. `sync_straggler_tickets` opens a P3 task after 24 hours of refusal.
