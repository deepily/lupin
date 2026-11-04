---
capability: fleet-hygiene-scripts
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - scripts.apply_claude_permissions.default_source_path@6ceb20dc59
  - scripts.apply_claude_permissions.default_target_path@c6d96e21c3
  - scripts.apply_claude_permissions.find_non_portable@940cc8a5fe
  - scripts.apply_claude_permissions.load_stanza@d464b4a952
  - scripts.apply_claude_permissions.compute_merge@e53ee6f79c
  - scripts.apply_claude_permissions.missing_rules@2f41548468
  - scripts.apply_claude_permissions.apply@ea27cdf793
  - scripts.apply_claude_permissions.main@19db68a9e0
  - scripts.check-arbiter-venv.follow_through_enabled@b9e7737217
  - scripts.check-arbiter-venv.check_modules@90b867daf9
  - scripts.check-arbiter-venv.main@9d09c5b11d
  - scripts.stale-seat-scan.current_branch@80b84194c3
  - scripts.stale-seat-scan.worktree_roots@9022219f16
  - scripts.stale-seat-scan.occupied_worktrees@80a1137e2e
  - scripts.stale-seat-scan.behind_commits@845dc81b41
  - scripts.stale-seat-scan.files_touched_by@f23de82f17
  - scripts.stale-seat-scan.files_this_seat_touched@da01c2a52b
  - scripts.stale-seat-scan.scan@80a1c4c797
  - scripts.stale-seat-scan.main@f4e5346961
---
# Seat, venv and permission hygiene scripts
Three host scripts under `src/scripts/` that keep the fleet's tools in a known state.
- `stale-seat-scan.py` finds live seats editing files that moved on the delivery branch. A seat is live when a process stands in its worktree, read from `/proc/<pid>/cwd`.
- `current_branch` returns the delivery target and raises when HEAD is detached. `worktree_roots` lists every worktree, longest path first.
- `occupied_worktrees` keeps the worktrees with a live process. `behind_commits` lists commits the target has that a worktree lacks.
- `files_touched_by` lists paths touched by commits. `files_this_seat_touched` covers dirty, untracked and undelivered files.
- `scan` reports only seats that are both behind and overlapping. `main` prints its denominators on every run.
- `check-arbiter-venv.py` imports every module the arbiter needs, in the venv that will run it. `follow_through_enabled` reads the flag that sets the required set, and `check_modules` collects the failures.
- `apply_claude_permissions.py` merges the portable permission stanza into `~/.claude/settings.json`. `default_source_path`, `default_target_path`, `find_non_portable` and `load_stanza` locate, check and read it.
- `compute_merge` computes the merge without writing. `missing_rules` is the `--verify` check. `apply` merges and `main` returns the exit code.
