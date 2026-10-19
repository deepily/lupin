---
capability: cc-git-guard-envelopes
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - lupin_cli.claude_code.hooks.lib.branch_lock_guard.configured_hooks_dirs@037a3c1155
  - lupin_cli.claude_code.hooks.lib.branch_lock_guard.build_branch_lock_deny_response@e7b1c204c7
  - lupin_cli.claude_code.hooks.lib.commit_scope_guard.git_commit_start@d81ee8867a
  - lupin_cli.claude_code.hooks.lib.commit_scope_guard.CommitScopeVerdict@b5fc33e365
  - lupin_cli.claude_code.hooks.lib.commit_scope_guard.commit_scope_deny_reason@3d74f78ffe
  - lupin_cli.claude_code.hooks.lib.commit_scope_guard.build_commit_scope_notice_response@800921605e
  - lupin_cli.claude_code.hooks.lib.commit_scope_guard.build_commit_scope_deny_response@14308348e5
---
# Git guard helpers and response envelopes
Helpers behind the branch-lock and commit-scope guards described in [[cc-hooks-git-guards]].
## What it does
- `configured_hooks_dirs` returns the folder `core.hooksPath` names, and its real path if different, so the branch-lock guard can protect it.
- It returns an empty list when the setting is unset, unreadable or already under `.git/hooks`.
- `build_branch_lock_deny_response` wraps a reason in the PreToolUse deny envelope.
- `git_commit_start` returns where the text before a `git commit` ends, at the start of the blank run before the match.
- `CommitScopeVerdict` holds a `deny_reason`, where None means allow, and a `notice`, a non-blocking note for a commit the guard could not review.
- `commit_scope_deny_reason` returns only the deny half of `evaluate_commit_scope`.
- `build_commit_scope_deny_response` builds the deny envelope.
- `build_commit_scope_notice_response` builds an allow envelope with `additionalContext`, so the seat is told, not blocked.
## Don't
- Don't treat silence as review: an unreviewed commit gets a notice.
## Invariants
- `configured_hooks_dirs` fails open: any error or timeout gives an empty list.
- The notice envelope carries no `permissionDecision`.
