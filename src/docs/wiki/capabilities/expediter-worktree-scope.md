---
capability: expediter-worktree-scope
pin_algorithm: py3.13.xaad549/ts5.9.3
pins:
  - cosa.agents.shared.worktree_context.worktree_scope@96a8b9a478
  - cosa.agents.shared.worktree_context.run_command_in@192ba63655
---
# Expediter worktree scope

An async context manager that gives an expediter orchestrator worktree isolation for one block. The worktree lifecycle is in [[worktree-lifecycle]].

## What it does
- `worktree_scope( orchestrator, label )` opens a `WorktreeContext` for the orchestrator's job id and yields it.
- When isolation is on, it sets the orchestrator's `_worktree_cwd` to the worktree path and prints that with `debug`.
- When isolation is off, `_worktree_cwd` is `None` and the orchestrator's uncommitted-changes warning runs.
- `run_command_in( cwd, command, *args, timeout )` runs a command in a directory without blocking the event loop and returns `{ success, stdout, stderr, returncode }`. A command past the timeout is killed and answers return code -1. It never raises. The worktree's git calls and the expediter's `git_ops` both go through it.

## Don't
- Don't read `_worktree_cwd` after the block. The scope clears it.

## Invariants
- `_worktree_cwd` is `None` on exit, even when the block raised.
- The orchestrator needs `job_id`, `debug`, `_worktree_cwd` and an async `_warn_on_uncommitted_changes_if_any`.
