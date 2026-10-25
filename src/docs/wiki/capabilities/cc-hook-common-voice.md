---
capability: cc-hook-common-voice
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_cli.claude_code.hooks.lib.hook_common.get_buffer_path@a60aa36be7
  - lupin_cli.claude_code.hooks.lib.hook_common.drain_voice_buffer@90ae279139
  - lupin_cli.claude_code.hooks.lib.hook_common.peek_voice_buffer@e81b6da82f
  - lupin_cli.claude_code.hooks.lib.hook_common.acknowledge_drained@774b388c48
  - lupin_cli.claude_code.hooks.lib.hook_common.drain_and_acknowledge@33aed83a01
  - lupin_cli.claude_code.hooks.lib.hook_common.format_backlog_header@776c6fa03f
  - lupin_cli.claude_code.hooks.lib.hook_common.format_voice_context@f50cd6e199
  - lupin_cli.claude_code.hooks.lib.hook_common.build_additional_context@760fd3a960
  - lupin_cli.claude_code.hooks.lib.hook_common.enrich_voice_context@e56f50338a
  - lupin_cli.claude_code.hooks.lib.hook_common.build_voice_deny_response@556f303a37
  - lupin_cli.claude_code.hooks.lib.hook_common.is_mcp_voice_tool@9b92303f1a
  - lupin_cli.claude_code.hooks.lib.hook_common.build_peer_dm_reminder@91a7f32b68
  - lupin_cli.claude_code.hooks.lib.hook_common.is_injected_peer_dm@525e625907
  - lupin_cli.claude_code.hooks.lib.hook_common.inject_qualifier_via_tmux@8d5d742130
  - lupin_cli.claude_code.hooks.lib.hook_common.deliver_pending_peer_dms@b4bbe2f5a1
  - lupin_cli.claude_code.hooks.lib.hook_common.spoken_word_budget@44f2367c3f
  - lupin_cli.claude_code.hooks.lib.hook_common.sanitize_for_wrap@c4188ea162
  - lupin_cli.claude_code.hooks.lib.hook_common.speakerphone_wrap@ef9218879b
  - lupin_cli.claude_code.hooks.lib.hook_common.speakerphone_exit_reminder@ddbdcebfbc
  - lupin_cli.claude_code.hooks.lib.hook_common.speakerphone_reminder_block@644d4e9286
---
# Hook common: voice buffer, peer DMs, speakerphone
`hook_common` also drains the voice buffer, delivers peer direct messages and wraps inbound text with the speakerphone rider.
## What it does
- `get_buffer_path` gives a session's JSONL buffer path. `drain_voice_buffer` drains it atomically. `peek_voice_buffer` reads without consuming.
- `drain_and_acknowledge` drains the buffer. `acknowledge_drained` is a no-op kept for API compatibility.
- `format_backlog_header` discloses how deep a drained backlog is. `format_voice_context` formats drained messages for injection.
- `build_additional_context` builds the `additionalContext` output. `enrich_voice_context` appends a notification reminder.
- `build_voice_deny_response` denies a PreToolUse call when the buffer has content. `is_mcp_voice_tool` spots cosa-voice tools.
- `build_peer_dm_reminder` builds the peer-DM reminder block. `is_injected_peer_dm` tells an injected envelope from user typing.
- `inject_qualifier_via_tmux` types text into the tmux input from a detached process.
- `deliver_pending_peer_dms` drains the buffer and delivers pending peer DMs by tmux, with no voice rider.
- `spoken_word_budget` converts the server's spoken character cap into a word budget.
- `sanitize_for_wrap` cuts text at the first voice-message or system-reminder marker.
- `speakerphone_wrap` wraps inbound text with the per-turn rider. `speakerphone_reminder_block` returns the reminder alone.
- `speakerphone_exit_reminder` builds the reminder sent when a session leaves speakerphone mode.
