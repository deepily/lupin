---
capability: cc-listener-and-ask
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_cli.claude_code.hooks.lib.cc_notification_listener.read_self_rss_mb@9b99f68aad
  - lupin_cli.claude_code.hooks.lib.cc_notification_listener.read_proc_starttime@29fadc096c
  - lupin_cli.claude_code.hooks.lib.cc_notification_listener.owner_is_alive@98a34f4d6c
  - lupin_cli.claude_code.hooks.lib.cc_notification_listener.CCNotificationListener@efd5358c08
  - lupin_cli.claude_code.hooks.lib.cc_notification_listener.CCNotificationListener.run@4b82f66e1c
  - lupin_cli.claude_code.hooks.lib.cc_notification_listener.parse_args@44579eee0c
  - lupin_cli.claude_code.hooks.lib.cc_notification_listener.main@042630e4cd
  - lupin_cli.claude_code.hooks.lib.anything_else_ask.AnythingElseResult@54205ced63
  - lupin_cli.claude_code.hooks.lib.anything_else_ask.summarize_task@3cb53f26ff
  - lupin_cli.claude_code.hooks.lib.anything_else_ask.get_session_context@2ca2ad7cc0
  - lupin_cli.claude_code.hooks.lib.anything_else_ask.build_ask_request@b2be90519e
  - lupin_cli.claude_code.hooks.lib.anything_else_ask.fire_anything_else_ask@95c70f0588
---
# Session listener and the Anything else ask
The background WebSocket listener for one Claude Code session, and the shared "Anything else?" prompt used when a session goes idle.
## What it does
- `CCNotificationListener` receives `user_initiated_message` notices for its session. A human message is typed into the tmux pane, and a peer DM or owed answer is appended to a JSONL buffer.
- `run` wraps the base listener in a restart loop. After the base gives up reconnecting, it waits and starts again until shutdown.
- `parse_args` and `main` are the entry point the SessionStart hook spawns, with the session hash, buffer path and owner pid.
- `read_proc_starttime` reads a process start-time from `/proc`. `owner_is_alive` compares it, so a recycled pid does not keep the listener alive.
- `read_self_rss_mb` reports the listener's memory in MB, or None.
- `fire_anything_else_ask` sends one blocking ask and returns an `AnythingElseResult` whose `answer` is `yes`, `no`, `timeout` or `error`.
- `build_ask_request` builds the request. `summarize_task` makes a short gist of the last message, and `get_session_context` reads the topic and git branch.
## Don't
- Don't treat an `error` answer as a no; it is a transport or parse failure.
## Invariants
- The listener buffers only messages whose job id matches its session hash or another accepted id.
- `fire_anything_else_ask` and `get_session_context` never raise.
