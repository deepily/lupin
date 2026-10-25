---
capability: claude-code-hooks
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_cli.claude_code.hooks.register_session.main@f7a90a1c55
  - lupin_cli.claude_code.hooks.stop.main@9c612736e2
  - lupin_cli.claude_code.hooks.pre_tool_use.main@0ec609b9fd
  - lupin_cli.claude_code.hooks.post_tool_use.main@dcc0e51181
  - lupin_cli.claude_code.hooks.user_prompt_submit.main@ba91d0665b
  - lupin_cli.claude_code.hooks.permission_request.main@f56dbd56a6
  - lupin_cli.claude_code.hooks.notification.main@8d3acf075d
  - lupin_cli.claude_code.hooks.session_end.main@d004d8396b
---
# Claude Code hook entry points

Each file in `src/lupin_cli/claude_code/hooks/` is one hook that Claude Code runs as a command. Each reads a JSON payload from stdin and prints a JSON reply.

## Session lifecycle
- `register_session.py` runs at session start. It writes the session bridge file, starts the notification listener and allocates a voice persona. See [[cc-session-bridge]].
- It also finds the seat's saved memento and injects it as context, and emits a marker after a context clear.
- `session_end.py` releases the voice persona, but not on `clear` or `compact`. It kills any idle waiter and stops the listener processes.
- It also schedules the seat's worktree teardown and removes the voice buffer file when that file is empty.

## Turn boundaries
- `user_prompt_submit.py` runs when a prompt is submitted. It cancels the idle waiter, drains the voice buffer and injects buffered voice messages as extra context.
- `stop.py` runs when Claude finishes a turn. If voice messages are buffered, it blocks the stop and hands them to Claude as the reason.
- A run of consecutive blocks is capped at `MAX_STOP_BLOCKS`, which is 3, and a re-entry flag prevents blocking again.
- The same hook hosts the owed-work poke described in [[cc-hooks-heartbeat]].

## Tool calls
- `pre_tool_use.py` runs before a tool call. Its git guards are covered in [[cc-hooks-git-guards]].
- `post_tool_use.py` runs after every tool call. It refreshes the bridge file's modification time, announces by voice and drains the voice buffer.
- Read-type tools are silent, shell and file edits are announced with detail, and other tools are announced by name.
- A write to the task store emits a progress event for the fleet watcher.

## Prompts and notifications
- `permission_request.py` auto-allows Read, Grep and Glob. If voice input is buffered, it denies and redirects Claude to that input.
- Otherwise it asks the user a blocking yes/no with a 25 second wait, and denies on timeout.
- `notification.py` relays Claude Code system notifications as speech: permission prompts, idle prompts and others. Its output is ignored by Claude Code.
