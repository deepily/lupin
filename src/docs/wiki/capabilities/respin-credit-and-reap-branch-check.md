---
capability: respin-credit-and-reap-branch-check
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.respin_credit.credit_dir@3a81d5e79d
  - lupin_mcp.respin_credit.mint@f8d572608c
  - lupin_mcp.respin_credit.find@80c1af7d05
  - lupin_mcp.respin_credit.spend@31b5c70d5c
  - lupin_mcp.respin_credit.restore@1ddd79b36c
  - lupin_mcp.respin_credit.respin_slug@8b137cd201
  - lupin_mcp.respin_credit.env_value@57696e5e8d
  - lupin_mcp.respin_credit.parse_env_value@3055e28244
  - lupin_mcp.reap_branch.default_sweep_git@570571f03c
  - lupin_mcp.reap_branch.seat_branch@779a466834
  - lupin_mcp.reap_branch.commits_ahead@482a36d37e
  - lupin_mcp.reap_branch.main_tree_branch@7e55e4310f
  - lupin_mcp.reap_branch.resolve_target_branch@716be898fc
  - lupin_mcp.reap_branch.unpicked_commits@623286711d
  - lupin_mcp.reap_branch.probe_seat_branches@e0a6533b31
  - lupin_mcp.reap_branch.branch_alarm@6e01ce5537
---
# Re-spin credit and reap branch check

Two helpers of the reap path ([[mcp-session-spawn-and-reap]]). The credit lets a one-for-one re-spin through skeleton crew. The branch check names a reaped seat's unmerged work.

- Skeleton crew refuses every spawn except a re-spin. When a manager dismisses a seat and names its persona to re-spin, `mint( manager_session_id, slugs )` writes one credit per reaped persona. It skips an unsafe slug and returns the slugs written.
- `credit_dir` is the `LUPIN_RESPIN_CREDIT_DIR` override, else a `respin-credits` folder beside the launch reservations. `find` returns the credit for that manager and persona while it is under fifteen minutes old. It returns None when absent, expired, garbled or minted in the future.
- `spend` uses the credit once, with one atomic removal, so racing launchers cannot share it. Given a session name, it keeps a claim file instead.
- `restore` returns a claimed credit when the launch started no session. It refuses while the launcher is still running, when a live session carries the name, or when a newer credit exists.
- `respin_slug( persona_preference, seed_memento, count )` returns the slug only for one named persona, a seed memento and one child. `env_value` and `parse_env_value` carry manager and slug to the launcher.
- The credit is a record, not a lock: every seat runs as one operating-system user. It stops a manager that follows the tool, not one set on defeating it.

## Reap branch check
- The check never withholds the kill. The commits stay in git, so it names them for the manager and the reap goes on.
- `seat_branch( cwd, git_fn )` returns the branch checked out in the seat's worktree, or a reason: no cwd, not a worktree, or detached.
- `main_tree_branch` and `resolve_target_branch` find the working line. That is the given target, else `CONTEXT_TICK_TARGET_BRANCH`, else the main tree's branch. There is no fixed fallback.
- `commits_ahead( repo, target, branch, git_fn )` counts commits the target lacks, None when git fails. `unpicked_commits` lists commits with no equivalent patch on the target, by `git cherry`.
- `default_sweep_git` loads the session-end sweep's git runner, so both ask the same question. It returns None when that module is missing.
- `probe_seat_branches( identities )` returns, for each seat, a status, branch, commit count and the `git log` line a successor runs. A detached seat is judged by patch equivalence.
- `branch_alarm( outcomes )` is one sentence for the top of the reap result naming every seat that leaves commits behind. It is None when all are merged.
