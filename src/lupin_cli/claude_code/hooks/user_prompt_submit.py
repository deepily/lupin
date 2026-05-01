#!/usr/bin/env python3
"""
UserPromptSubmit hook: drain voice buffer and inject as additionalContext.

Fires when the user submits a prompt (including empty prompts triggered by
the tmux Enter keystroke from CCNotificationListener). Drains the JSONL
voice buffer and injects formatted voice content as additionalContext so
Claude processes the voice command.

When no buffered voice messages exist, emits {} for normal prompt flow.

Install in ~/.claude/settings.json:
    "hooks": {
        "UserPromptSubmit": [{
            "hooks": [{
                "type": "command",
                "command": "python3 \"$LUPIN_ROOT/src/lupin_cli/claude_code/hooks/user_prompt_submit.py\""
            }]
        }]
    }
"""
import os
import sys

# Bootstrap: ensure src/ is on PYTHONPATH for lupin_cli imports
_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from lupin_cli.claude_code.hooks.lib.hook_common import (
    read_hook_input, log_payload, emit_json, drain_and_acknowledge,
    format_voice_context, enrich_voice_context, build_additional_context,
    write_turn_start_marker, conv_mode_reminder_block
)
from lupin_cli.claude_code.hooks.lib.session_bridge import (
    get_claude_session_id, resolve_stable_session_id,
    kill_idle_waiter, set_idle_detection_field,
)


def main():

    payload = read_hook_input()
    if not payload:
        emit_json( {} )
        sys.exit( 0 )

    # Log full payload for empirical analysis
    log_payload( "user_prompt_submit", payload )

    # Resolve session_id: payload first (future-proof), then session bridge fallback
    session_id = resolve_stable_session_id( payload.get( "session_id", "" ) ) or get_claude_session_id()

    # Idle-aware Stop hook: user activity resets the idle-detection timer.
    # Kill any pending waiter (UserPromptSubmit means the user is back, so
    # the deferred "Anything else?" is moot), reset backoff_index to 0
    # (next idle cycle starts fresh), and bump last_interaction_at. The
    # next Stop hook will respawn a fresh waiter at index 0 when this turn
    # ends. See: src/rnd/v0.1.7/2026.04.29-idle-aware-stop-hook/01-design.md
    import datetime as _dt
    kill_idle_waiter( session_id )
    set_idle_detection_field(
        session_id,
        last_interaction_at = _dt.datetime.now().astimezone().isoformat( timespec="seconds" ),
        backoff_index       = 0,
    )

    # Record turn start time for stop hook duration gating
    write_turn_start_marker( session_id )

    # Drain voice buffer and inject as additionalContext
    messages  = drain_and_acknowledge( session_id )
    voice_ctx = format_voice_context( messages )

    # Phase 2 — Layer 1 threading: append conv-mode reminder to additionalContext
    # for terminal-typed prompts when conv mode is active. The user's actual
    # typed prompt cannot be transformed via this hook (Claude Code only
    # accepts additionalContext, not prompt replacement) — but appending the
    # reminder via additionalContext is functionally equivalent: Claude sees
    # the reminder alongside the user prompt and applies the conv-mode
    # contract on its response.
    # See: src/rnd/v0.1.7/2026.04.30-conv-mode-three-layer-enforcement/01-design.md
    reminder = conv_mode_reminder_block( "terminal-typed", session_id )

    if voice_ctx and reminder:
        enriched = enrich_voice_context( voice_ctx )
        emit_json( build_additional_context( enriched + "\n\n" + reminder, "UserPromptSubmit" ) )
    elif voice_ctx:
        enriched = enrich_voice_context( voice_ctx )
        emit_json( build_additional_context( enriched, "UserPromptSubmit" ) )
    elif reminder:
        emit_json( build_additional_context( reminder, "UserPromptSubmit" ) )
    else:
        emit_json( {} )


if __name__ == "__main__":
    main()
