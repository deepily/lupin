---
capability: cc-hook-deny-envelopes
pin_algorithm: py3.13.xaad549/ts5.9.3
pins:
  - lupin_cli.claude_code.hooks.lib.hook_common.build_deny_response@691d431e89
  - lupin_cli.claude_code.hooks.lib.subagent_governance.subagent_deny_reason@d3bc6f3964
---
# Hook deny envelopes

A PreToolUse hook refuses a tool call by returning a deny envelope. Every guard answers through one builder, `build_deny_response` in `hook_common`, and puts its own reason in it.

## What it does
- The envelope is `hookSpecificOutput` with `hookEventName` set to `PreToolUse`, `permissionDecision` set to `deny` and the reason text.
- `build_deny_response` is that builder. The kill guard's reason comes from `kill_deny_reason`. That guard denies four shapes: a `kill` of a live Claude process, and a system-wide listing that feeds a kill. It also denies a `pkill` or `killall` with no own-children scoping, and `kill $(pgrep ...)`.
- It allows any listing with no kill downstream, and killing your own children.
- The merge guard's reason comes from `merge_head_deny_reason`. That guard denies a Bash `git commit` while a merge or squash is staged and unconcluded in the target tree.
- The merge reason names the merge sha when `MERGE_HEAD` is set. A squash has no sha to name.
- The stash guard's reason comes from `stash_deny_reason`. That guard denies mutating `git stash` commands, because the stash stack is shared by every worktree. Read-only `list` and `show` stay allowed.
- `subagent_deny_reason` returns a reason only when governance is enabled, the tool is the Agent or Task tool and the session is a crew manager. Otherwise it returns None.
- A crew manager has a non-empty spawn manifest or a standing manager-figure persona. The reason redirects to `spawn_sessions`, and `build_deny_response` wraps it.

## Don't
- Don't build the envelope by hand in a new guard. Call `build_deny_response` so every guard answers the same way.
- Don't use a broad pattern sweep to find a process. Read-only `ps` and `pgrep` are allowed for that.

## Invariants
- The kill guard fails open: any error allows the call.
- Its escape hatch is `LUPIN_ALLOW_UNSCOPED_KILL=1`.
- The subagent check fails open too: an unexpected error allows the call. It does not block a worker, who may use the Agent tool for their own task.
