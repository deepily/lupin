---
capability: cc-hook-deny-and-markers
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - lupin_cli.claude_code.hooks.lib.stash_guard.build_stash_deny_response@4ed03566b3
  - lupin_cli.claude_code.hooks.lib.subagent_governance.subagent_deny_reason@d3bc6f3964
  - lupin_cli.claude_code.hooks.lib.subagent_governance.build_subagent_deny_response@4abb9ffeb5
  - lupin_cli.claude_code.hooks.notification.beacon_idle_message@7862fadb9a
  - lupin_cli.claude_code.hooks.register_session.emit_context_clear_marker@095c2a651d
---
# Hook deny responses and small hook helpers
Pre-tool guards that deny a call with a reason, plus two helpers for the notification and session-start hooks.
## What it does
- `build_stash_deny_response()` and `build_subagent_deny_response()` return a PreToolUse envelope with `permissionDecision` set to `deny` and the reason text.
- The stash guard denies mutating `git stash` commands, because the stash stack is shared by all worktrees. Read-only `list` and `show` stay allowed.
- `subagent_deny_reason()` returns a reason only when governance is enabled, the tool is the Agent or Task tool, and the session is a crew manager. Otherwise it returns `None`.
- A crew manager has a non-empty spawn manifest or a standing manager-figure persona. The reason redirects to `spawn_sessions`.
- `beacon_idle_message()` picks the idle-beacon text. Unknown owed state gives the neutral message, owed work gives "Idle, but N item(s) owed", else the neutral message.
- `emit_context_clear_marker()` writes one `context_cleared` marker line when the SessionStart `source` is `clear`. It returns `True` if it wrote.
## Don't
- Do not rely on the subagent check to block a worker. Workers may use the Agent tool for their own task.
## Invariants
- The subagent check fails open: an unexpected error allows the call.
