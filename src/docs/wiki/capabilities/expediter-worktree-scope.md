---
capability: expediter-worktree-scope
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.agents.shared.worktree_context.worktree_scope@96a8b9a478
---
# Expediter worktree scope

An async context manager that gives an expediter orchestrator worktree isolation for one block. The worktree lifecycle is in [[worktree-lifecycle]].

## What it does
- `worktree_scope( orchestrator, label )` opens a `WorktreeContext` for the orchestrator's job id and yields it.
- When isolation is on, it sets the orchestrator's `_worktree_cwd` to the worktree path and prints that with `debug`.
- When isolation is off, `_worktree_cwd` is `None` and the orchestrator's uncommitted-changes warning runs.

## Don't
- Don't read `_worktree_cwd` after the block. The scope clears it.

## Invariants
- `_worktree_cwd` is `None` on exit, even when the block raised.
- The orchestrator needs `job_id`, `debug`, `_worktree_cwd` and an async `_warn_on_uncommitted_changes_if_any`.
