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
if _src_path not in sys.path:                 # pragma: no cover - bootstrap-exception (PATH MANAGEMENT mandate): sets sys.path BEFORE the lupin_cli package is importable, so it is genuinely unreachable under pytest (src already on sys.path) — not a coverable branch
    sys.path.insert( 0, _src_path )

from lupin_cli.claude_code.hooks.lib.hook_common import (
    read_hook_input, log_payload, emit_json, drain_and_acknowledge,
    format_voice_context, enrich_voice_context, build_additional_context,
    write_turn_start_marker, speakerphone_reminder_block, is_injected_peer_dm
)
from lupin_cli.claude_code.hooks.lib.session_bridge import (
    get_claude_session_id, resolve_stable_session_id,
    kill_idle_waiter, set_idle_detection_field,
)
from lupin_cli.claude_code.hooks.lib.heartbeat_poke_cap import reset_poke_count
from lupin_cli.claude_code.hooks.lib.heartbeat_work_owed import is_heartbeat_poke_prompt
from lupin_cli.claude_code.hooks.lib.dm_inbox_reconcile import surface_dm_inbox


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

    # Heartbeat Hook: genuine user re-engagement reopens the self-poke budget.
    # Reset the per-session heartbeat poke-cap counter (separate file from the
    # voice MAX_STOP_BLOCKS counter) so a session that capped at N pokes during
    # quiescence gets a fresh budget once the user actually comes back —
    # mirrors the backoff_index=0 reset above. See:
    # src/rnd/v0.1.8/2026.06.04-heartbeat-hook/02-stop-py-seam-factoring-proposal.md
    #
    # c121037b (2026-06-16): SKIP the reset when this prompt is the heartbeat's
    # OWN self-poke. The poke rides the Stop-hook `reason` field and is
    # re-submitted as a prompt via tmux send-keys, which fires THIS hook —
    # resetting the cap on the heartbeat's own poke made the counter reset every
    # turn so the cap NEVER halted (empirically poke_count stuck at 1 across 23
    # consecutive pokes spanning ~9h). Gating on the poke sentinel keeps the cap
    # accumulating across pokes (1→2→3→halt) while a real user prompt still
    # reopens the budget.
    # d0d7f068 Part 2 (option C): a heartbeat/arbiter poke OR an injected peer-DM is
    # NOT genuine user re-engagement — none may reopen the poke budget (that
    # misclassification reset the cap on every inbound DM/tap so the relief valve
    # never engaged). Only real USER typing resets. Both predicates match on SHARED
    # constants (no re-typed frame literals — 46a17f5a).
    _prompt = payload.get( "prompt", "" )
    if not is_heartbeat_poke_prompt( _prompt ) and not is_injected_peer_dm( _prompt ):
        reset_poke_count( session_id )

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
    reminder = speakerphone_reminder_block( "terminal-typed", session_id )

    # Store-backed DM inbox reconcile (bug 59f355e0, Option A — Mr. Radio ruling
    # 2026-07-02): the durable notifications store is the delivery guarantee the
    # lossy voice buffer never was. Surface any peer DMs the buffer dropped
    # (recipient mid-turn → buffered → never drained, or drained at low salience)
    # as additionalContext at start-of-turn, with NO interrupt/deny. The buffer/
    # inject/PreToolUse-deny paths stay UNTOUCHED — this is purely additive.
    # extra_surfaced_ids = the ai_to_ai ids drained THIS turn (above), so a DM
    # delivered by BOTH paths in one turn is not shown twice. Fail-open — never
    # raises. See: src/rnd/v0.1.9/2026.07.02-dm-loss-surfacing-leg-triage.md
    drained_dm_ids = [ m.get( "notification_id" ) for m in messages
                       if m.get( "direction" ) == "ai_to_ai" ]
    dm_ctx = surface_dm_inbox( session_id, extra_surfaced_ids=drained_dm_ids )

    if voice_ctx:
        voice_ctx = enrich_voice_context( voice_ctx, messages )

    # Assemble additionalContext: human voice first, then reconciled peer DMs,
    # then the conv-mode rider. Any subset may be empty; {} when all are.
    parts = [ part for part in ( voice_ctx, dm_ctx, reminder ) if part ]
    if parts:
        emit_json( build_additional_context( "\n\n".join( parts ), "UserPromptSubmit" ) )
    else:
        emit_json( {} )


if __name__ == "__main__":
    main()
