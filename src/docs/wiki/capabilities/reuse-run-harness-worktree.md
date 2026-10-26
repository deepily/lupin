---
capability: reuse-run-harness-worktree
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.reuse_harness.worktree.Worktrees@1508294a96
  - lupin_mcp.reuse_harness.worktree.Worktrees.create@1f8b63b0d8
  - lupin_mcp.reuse_harness.worktree.Worktrees.remove@0d83c693c1
  - lupin_mcp.reuse_harness.worktree.Worktrees.client_entries@f5937877a2
  - lupin_mcp.reuse_harness.worktree.Worktrees.exists@9bb45c96b6
  - lupin_mcp.reuse_harness.commands.run_command@911f8f20a6
---
# Reuse run harness: the worktree

This page covers the tree each run builds in. See [[reuse-run-harness]] for the run.

## What a run is given
- `create` cuts a detached tree at the frozen sha under `.claude/worktrees/`.
- It runs the shared venv and artifact provisioners. A provisioner that does not answer `ok` removes the tree and refuses with `WORKTREE_NOT_READY`.
- It empties `src/lupin_app/static`, the client folder, then removes the arm's paths. A remove path that leaves the tree is refused.
- The arm without the tools has no `.claude/skills/reuse-reviewer` folder.

## What it keeps
- The tree stays after the run, because the scorer reads the client the run built. `remove` is for a dry run.
- With the client folder empty the server boots and answers `/health`. The `/app` pages and `/static` files answer 404 until a run builds them.
- `run_command` is the shared command runner. It answers 127 for a command that cannot start or runs out of time.

## Don't
- Don't link `src/conf/keys` or `.env` into a run's tree. A key a run needs is given by environment.
