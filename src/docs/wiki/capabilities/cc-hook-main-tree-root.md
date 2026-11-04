---
capability: cc-hook-main-tree-root
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_cli.claude_code.hooks.lib.main_tree.main_tree_root@1928a26aa8
---
# Hook main tree root

Fleet-shared logs belong to the repo, not to the seat that wrote them. A seat pins its root to its own worktree, so a log written there is left behind when the tree is removed.

## What it does
- `main_tree_root( path )` returns the main working tree for a path.
- When the path sits under a `/.claude/worktrees/` lane, it returns the part before the outermost lane. A tree made inside a worktree still resolves to the main tree.
- Otherwise it returns the path unchanged, as a string.
- It uses a path rule only and makes no git call, so it is safe in hooks and at import time.

## Don't
- Don't join `io/...` onto a seat's pinned root for a fleet-shared log. Resolve the main tree first.

## Invariants
- Every worktree lives under `<main>/.claude/worktrees/<name>`, so the rule cannot disagree with itself.
