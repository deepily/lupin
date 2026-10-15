---
capability: worktree-reaper-branch-queries
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.agents.shared.worktree_reaper.list_worktrees@1d9cdb7186
  - cosa.agents.shared.worktree_reaper.checked_out_branches@289bd70835
  - cosa.agents.shared.worktree_reaper.main_worktree_branch@d13b43328a
  - cosa.agents.shared.worktree_reaper.merge_verdict@63cdf4940d
  - cosa.agents.shared.worktree_reaper.content_landed@94b2d0bdf6
  - cosa.agents.shared.worktree_reaper.is_protected_branch@2d1f9c0019
  - cosa.agents.shared.worktree_reaper.delete_merged_branch@177da4d671
---
# Worktree reaper branch queries

The janitor's read-only questions about worktrees and branches, plus the one safe branch delete. Each takes an injectable git runner and never raises. See [[worktree-lifecycle]].

## What it does
- `list_worktrees` parses `git worktree list --porcelain` into records with path, branch, lock state and an `is_main` flag. A git failure gives an empty list.
- `main_worktree_branch` returns the branch the main tree has checked out, or `None` when it is detached.
- `checked_out_branches` returns the set of branches some worktree holds, or `None` when git could not answer.
- `merge_verdict` answers `merged`, `unmerged` or `failed` using `git merge-base --is-ancestor`. An unmerged answer carries the count ahead.
- `content_landed` uses `git cherry`. It returns true when no commit is marked as missing, false when one is, and `None` when git could not say.
- `is_protected_branch` is true for `main`, `master`, the working branch and any name containing `wip` in any case.
- `delete_merged_branch` runs `git branch -d` and reports why it kept a branch otherwise.

## Invariants
- A failed look is never read as merged, landed or none checked out. Callers get `failed` or `None`.
- `delete_merged_branch` never uses `-D`, never pushes and never deletes a remote ref.
- It keeps a protected branch, a branch some worktree still has checked out and an unmerged branch.
- Refs are passed as `refs/heads/<name>` or a sha, because a bare name resolves to a same-named tag first.
