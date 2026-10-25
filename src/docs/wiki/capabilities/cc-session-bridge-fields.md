---
capability: cc-session-bridge-fields
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_cli.claude_code.hooks.lib.session_bridge.get_speakerphone@89e0092636
  - lupin_cli.claude_code.hooks.lib.session_bridge.set_speakerphone@0201ca8b58
  - lupin_cli.claude_code.hooks.lib.session_bridge.find_active_speakerphone_sessions@ab23e4fa65
  - lupin_cli.claude_code.hooks.lib.session_bridge.get_voice_persona@2ea96eeef2
  - lupin_cli.claude_code.hooks.lib.session_bridge.set_voice_persona@68f1c8359c
  - lupin_cli.claude_code.hooks.lib.session_bridge.find_active_voice_persona_sessions@f2ca237d8f
  - lupin_cli.claude_code.hooks.lib.session_bridge.set_user_id@40d1f8340e
  - lupin_cli.claude_code.hooks.lib.session_bridge.set_owner_user_id@9f200995a8
  - lupin_cli.claude_code.hooks.lib.session_bridge.set_manager_figure_implicit@1de85b9ad9
  - lupin_cli.claude_code.hooks.lib.session_bridge.get_last_autonarrated_turn_id@cf58e29700
  - lupin_cli.claude_code.hooks.lib.session_bridge.set_last_autonarrated_turn_id@65adf711a7
  - lupin_cli.claude_code.hooks.lib.session_bridge.get_idle_detection@1a48a892d6
  - lupin_cli.claude_code.hooks.lib.session_bridge.set_idle_detection_field@867c4fced3
  - lupin_cli.claude_code.hooks.lib.session_bridge.clear_idle_waiter_pid@0158f5ff52
  - lupin_cli.claude_code.hooks.lib.session_bridge.kill_idle_waiter@2987c05da3
---
# Claude Code session bridge fields
Per-session settings kept as fields in the bridge JSON, with a getter and setter for each. Setters read, change one field, and write back through the atomic writer in [[cc-session-bridge]].
## What it does
- `get_speakerphone()` and `set_speakerphone()` handle `speakerphone_on`. A missing field defaults to off in solo mode and on in chorus mode.
- `set_speakerphone()` stamps format version 2 and removes the legacy `conversation_mode_active` key.
- `find_active_speakerphone_sessions()` lists live bridges with speakerphone on, so solo mode can switch the others off.
- `get_voice_persona()` returns the persona dict or `None`. `set_voice_persona( sid, None )` stores null rather than deleting the key.
- `find_active_voice_persona_sessions()` lists live bridges that hold a persona, for pool occupancy.
- `set_user_id()` stamps the listener's service identity; `set_owner_user_id()` stamps the human owner, which the broadcast filter compares.
- `set_manager_figure_implicit()` stamps the manager-figure answer computed at SessionStart.
- `get_last_autonarrated_turn_id()` and its setter stop the Stop hook narrating one turn twice.
- `get_idle_detection()` and `set_idle_detection_field()` read and merge the `idle_detection` block.
- `clear_idle_waiter_pid()` returns the old waiter pid and clears it. `kill_idle_waiter()` then sends SIGTERM after a liveness check.
## Don't
- Do not expect a setter to create a bridge. It returns `False` when none matches.
## Invariants
- Setters preserve all other bridge fields and never raise.
