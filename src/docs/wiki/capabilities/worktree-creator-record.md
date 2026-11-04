---
capability: worktree-creator-record
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_cli.claude_code.hooks.lib.worktree_creator_record.ledger_path@d5a3b547ed
  - lupin_cli.claude_code.hooks.lib.worktree_creator_record.parse_worktree_adds@19e1929832
  - lupin_cli.claude_code.hooks.lib.worktree_creator_record.record_worktree_creator@92594e0b4c
  - lupin_cli.claude_code.hooks.lib.worktree_creator_record.spawning_manager@32e3e03259
  - lupin_cli.claude_code.hooks.lib.worktree_creator_record.write_entries@0ee8ba2c02
---
# Worktree creator record

A worker makes its own review tree with `git worktree add`. The janitor retires it hours later, after the worker's bridge is gone. This hook records which manager the tree belongs to while the seat still can say. See [[worktree-straggler-tickets]] and [[cc-hooks-git-guards]].

- `record_worktree_creator( tool_name, tool_input, cwd )` runs before a Bash call. It does nothing unless the command holds a `git worktree add` and a manager spawned this seat. It returns the tree paths recorded, and any failure returns an empty list without blocking the call.
- `parse_worktree_adds( command, cwd )` lists each `git worktree add` as an absolute path and a branch from `-b` or `-B`, or None. A leading `cd <dir>` and git's `-C <dir>` move the base. A segment it cannot read is skipped.
- `spawning_manager( env )` is the persona in `COSA_VOICE_SPAWNED_BY_PERSONA`. For an older seat with only `COSA_VOICE_SPAWNED_BY`, it reads the manager's voice persona from that session's bridge. A seat no manager spawned gives None.
- `write_entries( ledger, adds, manager )` adds the entries under a file lock and writes atomically. Entries past the retention window are dropped, and a repeated tree or branch is overwritten. It raises `OSError` when the folder is not writable, and the caller swallows that.
- `ledger_path( repo_root )` is `worktree-creators.json` in the repo's fleet data folder. A worktree resolves to its parent repo, so every seat shares one file, and a reap never deletes it.
