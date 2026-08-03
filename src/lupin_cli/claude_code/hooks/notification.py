#!/usr/bin/env python3
"""
Notification hook: message-aware TTS relay + voice buffer drain.

Relays CC system notifications with type-specific TTS content:
- permission_prompt: includes the full message text
- idle_prompt: announces idle state with message
- other: includes truncated message (80 chars)

Observation-only (output is ignored by CC).

Install in ~/.claude/settings.json:
    "hooks": {
        "Notification": [{
            "type": "command",
            "command": "python3 \"$LUPIN_ROOT/src/lupin_cli/claude_code/hooks/notification.py\""
        }]
    }
"""
import os
import sys

# Bootstrap: ensure src/ is on PYTHONPATH for lupin_cli imports
_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:   # pragma: no cover - bootstrap import-guard; src is always on sys.path under pytest
    sys.path.insert( 0, _src_path )

from lupin_cli.claude_code.hooks.lib.hook_common import (
    read_hook_input, log_payload, emit_json, send_tts, drain_and_acknowledge,
    deliver_pending_peer_dms
)
from lupin_cli.claude_code.hooks.lib.session_bridge import (
    get_claude_session_id, resolve_stable_session_id, get_voice_persona,
    get_session_metadata
)
from lupin_cli.claude_code.hooks.lib.heartbeat_events import emit_idle_prompt


def beacon_idle_message( owed, owed_unknown, total_owed, idle_msg ):
    """
    Pure idle-beacon message selection (bug aa403e03). Shared by the idle_prompt
    branch AND its tests so the test exercises the REAL logic — no hand-mirrored
    copy that can drift (the SAME anti-duplication lesson as this very bug).

    The owed flag / total_owed come from the shared HOLD-AWARE verdict
    (stop._resolve_owed_state); the phrasing matches the Stop idle-announce
    (_idle_sentence) for cross-hook consistency.

    Requires:
        - owed, owed_unknown are bools; total_owed is a non-negative int
        - idle_msg is the neutral fallback string (e.g. "Claude is waiting for input")

    Ensures:
        - owed_unknown True  → idle_msg (UNKNOWN ≠ idle; make NO owed claim)
        - owed True          → "Idle, but N item(s) owed" (or "Idle, but work owed"
          when total_owed is 0 — owed via a referent-less signal)
        - otherwise          → idle_msg (determinate not-owed, incl. an honored hold)
        - precedence is UNKNOWN → OWED → idle; never raises
    """
    if owed_unknown:
        return idle_msg
    if owed:
        if total_owed > 0:
            plural = "" if total_owed == 1 else "s"
            return f"Idle, but {total_owed} item{plural} owed"
        return "Idle, but work owed"
    return idle_msg


def main():

    payload = read_hook_input()
    if not payload:
        emit_json( {} )
        sys.exit( 0 )

    # Extract notification details
    notification_type = payload.get( "type", payload.get( "notification_type", "unknown" ) )
    message           = payload.get( "message", "" )

    # Log full payload for empirical analysis
    log_payload( "notification", payload )

    # Resolve session_id: payload first, then session bridge fallback
    session_id = resolve_stable_session_id( payload.get( "session_id", "" ) ) or get_claude_session_id()

    # Drain voice buffer. At idle_prompt the pane is sitting at a prompt, so any
    # pending peer DM (direction=ai_to_ai) must be tmux-DELIVERED, not discarded —
    # the Notification hook's emit_json is ignored by CC, so tmux-wake is the only
    # path to an idle pane (§6 of the notification-native AI↔AI design). Other
    # notification types keep the legacy drain-and-acknowledge (voice ack is a
    # no-op now; this just clears any stale buffer).
    if notification_type == "idle_prompt":
        deliver_pending_peer_dms( session_id )
    else:
        drain_and_acknowledge( session_id )

    # Type-specific TTS content (respects HOOK_TTS_ENABLED)
    # Permission prompts use high priority so TTS speaks them aloud —
    # the user needs to hear these to know Claude needs approval.
    if notification_type == "permission_prompt":
        tts_msg      = message if message else "Permission prompt"
        tts_priority = "high"
    elif notification_type == "idle_prompt":
        # bug aa403e03 (idle-status desync): consult the SAME HOLD-AWARE verdict the
        # Stop hook uses (_resolve_owed_state), NOT the raw store count. The prior
        # beacon called _owed_count_from_store ALONE — hold-BLIND — so a HELD /
        # blocked / hold-suppressed store row read N-owed HERE while the Stop hook
        # (which honors the .heartbeat-hold via decide_heartbeat) read 0-owed and
        # announced "Momentarily idle." ⇒ the two disagreed within ~60s. Routing
        # BOTH through _resolve_owed_state makes them agree by construction.
        # Resolve cwd + transcript_path from the bridge when the payload lacks them
        # so the hold read matches the Stop hook's (bug 1789f197: a worktree-cwd
        # hold is missed without the cwd). Lazy import keeps the heavy stop module
        # off the hot permission_prompt path (idle_prompt is a cold event).
        from lupin_cli.claude_code.hooks.stop import _resolve_owed_state
        _meta      = get_session_metadata()
        owed_state = _resolve_owed_state(
            session_id,
            transcript_path = payload.get( "transcript_path" ) or _meta.get( "transcript_path" ),
            cwd             = payload.get( "cwd" ) or _meta.get( "cwd" ),
        )
        idle_msg = message if message else "Claude is waiting for input"
        # Message selection is the PURE beacon_idle_message helper (shared with the
        # tests so they exercise the real logic, not a mirrored copy). Cases:
        # owed_unknown → neutral idle_msg (UNKNOWN ≠ idle, fail-safe); owed → "Idle,
        # but N owed" (hold-aware — cap reached / held obligation), matching the Stop
        # idle-announce phrasing; else determinate not-owed → plain idle_msg.
        tts_msg = beacon_idle_message(
            owed         = owed_state[ "owed" ],
            owed_unknown = owed_state[ "owed_unknown" ],
            total_owed   = owed_state[ "total_owed" ],
            idle_msg     = idle_msg,
        )
        tts_priority = "low"
        # Fleet liveness 4th signal (arbiter liveness fix, Part 7 / Step 1.3):
        # emit a kind-tagged idle_prompt recency event so the arbiter counts
        # this session as ALIVE-by-idle. kind="idle_prompt" keeps it OFF the
        # ACTIVITY axis (state) and the stop_event age — it feeds
        # idle_prompt_age_s ONLY. Fire-and-forget: emit_idle_prompt never raises
        # and the persona resolve is best-effort, so TTS is never affected.
        _persona      = get_voice_persona( session_id )
        _persona_name = _persona.get( "name" ) if isinstance( _persona, dict ) else None
        emit_idle_prompt( session_id, persona=_persona_name )
    else:
        if message:
            truncated = message[:80] + "..." if len( message ) > 80 else message
            tts_msg   = f"Notification ({notification_type}): {truncated}"
        else:
            tts_msg = f"Notification: {notification_type}"
        tts_priority = "low"

    send_tts( tts_msg, priority=tts_priority )

    # Observation-only — output is ignored by CC
    emit_json( {} )


if __name__ == "__main__":
    main()
