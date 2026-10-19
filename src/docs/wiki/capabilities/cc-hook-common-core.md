---
capability: cc-hook-common-core
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - lupin_cli.claude_code.hooks.lib.hook_common.read_hook_input@a6ac4c963d
  - lupin_cli.claude_code.hooks.lib.hook_common.log_to_stream@42257bf060
  - lupin_cli.claude_code.hooks.lib.hook_common.log_payload@77a1f607fd
  - lupin_cli.claude_code.hooks.lib.hook_common.emit_json@52021360da
  - lupin_cli.claude_code.hooks.lib.hook_common.get_timestamp@39a92359ce
  - lupin_cli.claude_code.hooks.lib.hook_common.get_target_email@23cae205ec
  - lupin_cli.claude_code.hooks.lib.hook_common.is_tts_enabled@cd2388caa1
  - lupin_cli.claude_code.hooks.lib.hook_common.build_progress_group_id@830552c20b
  - lupin_cli.claude_code.hooks.lib.hook_common.send_tts@d458f34230
  - lupin_cli.claude_code.hooks.lib.hook_common.format_tool_summary@a4970dc736
  - lupin_cli.claude_code.hooks.lib.hook_common.build_stop_block@c3d0725819
  - lupin_cli.claude_code.hooks.lib.hook_common.build_stop_block_with_system_message@74e01337fb
  - lupin_cli.claude_code.hooks.lib.hook_common.get_stop_block_count@bbf9ab626e
  - lupin_cli.claude_code.hooks.lib.hook_common.increment_stop_block_count@b13057ad7b
  - lupin_cli.claude_code.hooks.lib.hook_common.reset_stop_block_count@353396c183
  - lupin_cli.claude_code.hooks.lib.hook_common.write_turn_start_marker@9ffd19a525
  - lupin_cli.claude_code.hooks.lib.hook_common.get_turn_elapsed_seconds@1c1a757b42
  - lupin_cli.claude_code.hooks.lib.hook_common.build_permission_decision@7ecbeb25fd
  - lupin_cli.claude_code.hooks.lib.hook_common.quiet_stdout@2e8c8b9d81
---
# Hook common: I/O, logging and Stop block
`hook_common` is the shared library for the Claude Code hook scripts. This page covers input, logging, TTS, Stop blocks and turn timing.
## What it does
- `read_hook_input` parses the JSON payload from stdin. `emit_json` writes the response to stdout.
- `log_to_stream` appends a one-line entry to a hook events file. `log_payload` writes a timestamped payload to the logs directory.
- `get_timestamp` returns the time in the Eastern zone. `get_target_email` resolves the notification target from the environment, then a file.
- `is_tts_enabled` reads `HOOK_TTS_ENABLED`. `send_tts` sends a fire-and-forget notification.
- `build_progress_group_id` joins a hook prefix and session id. `format_tool_summary` builds a one-line tool summary for announcements.
- `build_stop_block` and `build_stop_block_with_system_message` build the Stop hook's decision block.
- `get_stop_block_count`, `increment_stop_block_count` and `reset_stop_block_count` keep a per-session counter file.
- `write_turn_start_marker` and `get_turn_elapsed_seconds` time a turn from the user prompt.
- `build_permission_decision` builds the output of a PermissionRequest hook.
- `quiet_stdout` calls a function with its Python-level stdout writes discarded.
## Don't
- Do not print extra text to stdout in a hook. Stdout carries the JSON response.
