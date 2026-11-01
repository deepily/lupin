---
capability: needset-member-text
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.reuse_needset.strip.module_of@5a0e6e5001
  - lupin_mcp.reuse_needset.strip.src_root_of@cfeae4d6fb
  - lupin_mcp.reuse_needset.strip.dotted_id@8fb5c908be
  - lupin_mcp.reuse_needset.strip.python_text@6e9b11a162
  - lupin_mcp.reuse_needset.strip.script_results@5fffc8a0cf
  - lupin_mcp.reuse_needset.strip.strip_members@da1db082ae
  - lupin_mcp.reuse_needset.strip.strip_member@af135d14ff
  - lupin_mcp.reuse_needset.strip.bodies_for@895645cb16
  - lupin_mcp.reuse_needset.source_at.full_sha@a62c6baa15
  - lupin_mcp.reuse_needset.source_at.worktree_path@c8746cca3e
  - lupin_mcp.reuse_needset.source_at.at_commit@cecd336fdf
  - lupin_mcp.reuse_needset.source_at.lock@bdbac1f4f9
  - lupin_mcp.reuse_needset.source_at.unlock@5148a0c4db
  - lupin_mcp.reuse_needset.source_at.ensure_worktree@0f1e2fbd60
---
# Need set: member text

Prepares member text for the need set. The drafter gets stripped names, and search gets raw bodies. Python members go through the existing need-input step. Script members go through `needset_strip.js`, one node start per call.

## Locating a member
- `module_of` reads the module path out of a record's id, which is the id without the name.
- `src_root_of` finds the directory the module ids are rooted at, or the root itself when the module starts at the top.
- `dotted_id` returns the id without a repeat suffix, the id the need-input step resolves.

## Reading text
- `python_text` reads a Python member's source as written, with decorators and docstring, dedented. A member that cannot be found raises `STRIP_FAILED`.
- `script_results` runs the script once over a list of script records, in one of three modes: strip, text or shape. An empty list starts no process.
- A member not found comes back as not ok, or raises `STRIP_FAILED` when strict is set. A missing node or TypeScript compiler raises `DependencyMissing`.

## Stripping
- `strip_members` returns, for each id, the kind, the text and the forbidden names. The text holds none of the forbidden names, and all script records share one node start. `strip_member` strips one member through the same path.
- `bodies_for` returns each member's source as written, Python by the need-input lookup and script members through one node start.

## The source commit
- `ensure_worktree` makes a detached worktree at the source commit under `.claude/worktrees/needset-run-<sha>`. It reuses one already there when `at_commit` says its tracked files are unchanged, and refuses any other with `SOURCE_TREE_MISMATCH`. It locks the worktree with `lock`, and the run frees it with `unlock` when it ends, so the janitor cannot sweep a run's root.
- A live run takes that worktree as its root before the context is built. So the index, strips, trace and probe cannot move when peers merge. A worktree also keeps the data folder and spend ledger of the parent checkout.
