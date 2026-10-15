---
capability: fix-git-operations
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.agents.bug_fix_expediter.git_ops.GitOps@d5a6829611
  - cosa.agents.shared.git_strategist.GitStrategist@d015029753
---
# Fix git operations

Two cooperating classes turn an applied fix into a commit, a branch and optionally a pull request. `GitOps` runs the commands. `GitStrategist` decides which ones.

## What it does
- `GitOps` wraps the `git` and `gh` command-line tools as awaited subprocess calls, each with a timeout of 30 seconds by default.
- Every `GitOps` method returns a dictionary with a `success` flag and an `error` field. None of them raises.
- `commit_on_branch` stages the listed files and commits them. An empty file list is refused without running git.
- `create_fix_branch` checks out a new branch named exactly as the slug it is given.
- `push_branch` pushes one explicit refspec, never forces, and refuses any name that is not `fix/<name>`.
- `create_pr` calls `gh pr create`. It detects once whether `gh` is installed and reports failure when it is not.
- `GitStrategist.resolve_trust_level` reads the trust level from a decision proxy. It returns 1 for a missing proxy or any error.
- `GitStrategist.generate_slug` returns `fix/<date>-<up to three words>`, or `fix/<date>-fix` when the text has no words.
- At trust 1 or 2, `commit_and_pr_single` and `commit_and_pr_multi` commit on the current branch only.
- At trust 3 and above they make a fix branch and commit. With pushing enabled they push and open a pull request, or stop at the branch without `gh`.

## Invariants
- With pushing switched off, which is the default, nothing is pushed and no pull request is opened. The error names the flag.
- On an error at trust 3 and above, the original branch is checked out again before returning.
- The strategist never raises. Its result always has `git_strategy`, `commit_hash`, `branch_name`, `pr_url` and `error`.
