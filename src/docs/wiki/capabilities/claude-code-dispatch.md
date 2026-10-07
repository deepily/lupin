---
capability: claude-code-dispatch
pin_algorithm: py3.13.xf75af6/ts5.9.3
pins:
  - cosa.orchestration.claude_code.dispatcher.ClaudeCodeDispatcher@4917d3e67e
  - cosa.orchestration.claude_code.dispatcher.ClaudeCodeDispatcher.dispatch@06780c00bc
  - cosa.orchestration.claude_code.dispatcher.ClaudeCodeDispatcher.inject@293ad2efde
  - cosa.orchestration.claude_code.dispatcher.Task@85461d6614
  - cosa.orchestration.claude_code.dispatcher.TaskResult@3cae189ac0
  - cosa.orchestration.claude_code.dispatcher.TaskType@516e546e49
  - cosa.orchestration.claude_code.message_history.MessageHistory@8e4f5bfd84
  - cosa.orchestration.claude_code.message_history.MessageHistory.get_context_prompt@91ce45a3f6
---
# Claude Code dispatch

`ClaudeCodeDispatcher` runs one Claude Code task and returns a `TaskResult`. A task is either `BOUNDED`, a `claude -p` subprocess, or `INTERACTIVE`, an SDK client session. The queue job that wraps it is described in [[bounded-claude-code-jobs]]. The only other module that uses it is `ClaudeCodeJob`; the dispatcher file's own `main()` also calls `dispatch`.

## The task
- `Task` carries an id, project, prompt and type. The defaults are 50 turns, a 3600 second timeout and `LUPIN_ROOT` as the working directory, else `/home/projects`.
- `ClaudeCodeDispatcher()` raises `RuntimeError` when `LUPIN_ROOT` is unset or empty. Unless an `mcp_config_path` is passed, it picks `cosa_mcp_docker.json` when the root is exactly `/var/lupin`, else `cosa_mcp.json`.
- Bounded runs and the interactive session loop catch their errors and return them in `TaskResult.error`. An interactive task without the SDK, or an unknown type, also returns an error result.

## Bounded mode
- It starts `claude -p <prompt>` in the working directory with stream-json output, `--max-turns`, accept-edits permission and the MCP config.
- The allowed tools are `Read`, `Write`, `Bash` and the `converse`, `notify` and `ask_yes_no` voice tools.
- Each non-blank stdout line goes to the `on_message` callback, as parsed JSON or as a `text` record. The record of type `result` supplies the session id, text and cost.
- Past the timeout it kills the process and returns exit code -1. Otherwise exit code 0 is success, with or without a result record. Any other code returns stderr as the error, else `Unknown error`.
- The bounded path prints `[DEBUG]` lines whatever the `debug` flag says.

## Interactive mode
- It opens a `ClaudeSDKClient` with the same tools, a stdio `cosa-voice` server and a system prompt that names the task's `sender_id`.
- It streams every message to `on_message`, then sends the next queued message, if any. It succeeds only if a result message arrived; otherwise the error is `No result received`.
- `inject`, `interrupt`, `end_session` and `get_active_sessions` work on the open session. `inject` queues the message and, by default, interrupts the session. With `preserve_context` on, its default, and some history, it prepends `MessageHistory.get_context_prompt`. No code outside the tests calls them.
- `MessageHistory` keeps the original prompt and the turns. By default it keeps the first 500 characters of each and adds `...` to any that were longer.
