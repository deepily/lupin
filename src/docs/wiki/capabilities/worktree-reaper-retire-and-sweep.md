---
capability: worktree-reaper-retire-and-sweep
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.agents.shared.worktree_reaper.find_ignored_blockers@3ebcc3852e
  - cosa.agents.shared.worktree_reaper.default_evacuation_root@bff6e0e00d
  - cosa.agents.shared.worktree_reaper.evacuate_blockers@3bfccfc6f0
  - cosa.agents.shared.worktree_reaper.archive_branch@20bd74c14e
  - cosa.agents.shared.worktree_reaper.retire_branch@b9426eba89
  - cosa.agents.shared.worktree_reaper.branch_created_ts@57e2aaff41
  - cosa.agents.shared.worktree_reaper.sweep_archive@64fdc5fe54
---
# Worktree reaper retire and sweep

How the janitor saves a tree's data files and unmerged branches before it removes anything, and how it clears the saved copies later. Companion pages: [[worktree-reaper-branch-queries]] and [[worktree-lifecycle]].

## What it does
- `find_ignored_blockers` lists the ignored files in a tree that a removal would destroy. Build artifacts, run output and mirrored memento records are not blockers.
- `evacuate_blockers` moves those files to `<root>/io/worktree-evacuated/<day>-<tree>-<stamp>`, keeping each relative path.
- `default_evacuation_root` returns that folder under the main tree.
- `archive_branch` moves a branch to `refs/archive/<day>/<branch>`. It writes the archive ref and reads it back before it removes the branch.
- `retire_branch` deletes a merged branch and archives an unmerged one. The outcome says whether the commits had landed by content.
- `branch_created_ts` returns the epoch seconds of the oldest reflog entry, so the janitor can judge a branch's age.
- `sweep_archive` deletes dated archive refs and evacuation folders older than the retention window of 14 days.

## Invariants
- `find_ignored_blockers` reports `ok` false when git could not list the files, and the caller must then refuse the removal.
- `evacuate_blockers` never merges into or overwrites an earlier evacuation. A failed move leaves the tree in place.
- `archive_branch` keeps the branch when a commit landed on it after the sha was archived. A clashing ref gets a sha suffix.
- A branch with an empty but readable reflog returns 0.0, which is old. An unreadable one returns `None`, which is too young to delete.
- None of these push, and none raise.
