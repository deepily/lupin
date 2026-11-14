---
capability: quiet-workers-by-default
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.worker_voice_mode.resolve_worker_voice_mode@02b7cc6141
  - lupin_mcp.worker_voice_mode.worker_voice_env@2f30f24666
  - lupin_mcp.worker_voice_mode.speakerphone_for_mode@09638c8c92
  - lupin_mcp.worker_voice_mode.is_quiet_worker_bridge@3371415e1b
  - lupin_cli.claude_code.hooks.lib.session_bridge.is_quiet_worker@3b43e97c50
---
# Quiet workers by default

A session started by `spawn_sessions` begins quiet, so Rick hears his managers and not the workers. Quiet means speakerphone off with the ding kept. It does not mean silent: an urgent notify from a quiet worker still speaks.

## The key
- `cc session worker default voice mode` in `lupin-app.ini` holds `quiet`, `speakerphone` or `inherit`. `resolve_worker_voice_mode` refuses a missing, blank or unknown value and names the key. There is no default in code.
- `spawn_sessions` reads it through ConfigurationManager and forwards it as `COSA_VOICE_WORKER_VOICE_MODE`. A role equal to `manager` forwards `inherit` without reading the key.

## The bridge
- The SessionStart hook turns the word into `speakerphone_on`. An absent word keeps the old false.
- After the voice persona is allocated, a spawned session whose persona is a standing manager is set to the mode-aware default. This catches a manager spawned with any role. Cheech was measured as role `author`.

## The stamp
- `is_quiet_worker_bridge` is true for a bridge with `spawned_by` and a role that is not exactly `manager`.
- It also needs a manager stamp that is explicitly false and `speakerphone_on` false.
- An absent stamp is not quiet.
- The notification queue reads the sender's bridge at push and adds `worker_quiet: true` to the event.

## The clients
- Legacy: a stamped event sets the session quiet, and the rewrite lowers `high` to `medium` only. A session Rick quieted by hand has no stamp, so its `urgent` is lowered as before.
- Multiplexer: the sender card shows a quiet chip, and the speech gate skips a quiet worker's `high` and keeps its `urgent`. The multiplexer has no ding of its own. `conversation_mode_active` is the pinned-conversation flag and is not used.

## Don't
- Don't test for a manager by role alone. Use the persona stamp as well.
- Don't read a missing stamp as not a manager when deciding to quiet a seat.
