"""
Unit tests for the Notification hook.

Tests cover:
    - Type-specific TTS: permission_prompt, idle_prompt, default, missing message
    - Message truncation at 80 chars
    - Voice drain called
    - Empty payload → immediate {}
"""

import sys
import pytest
from unittest.mock import patch, MagicMock

from lupin_cli.claude_code.hooks.notification import main


def _owed_bundle( owed=False, owed_unknown=False, total_owed=0 ):
    """
    A minimal stop._resolve_owed_state return (bug aa403e03) for driving the beacon
    HERMETICALLY — independent of ambient ~/.claude/settings.json heartbeat.enabled.
    The beacon now routes through the shared HOLD-AWARE verdict, so patching
    _resolve_owed_state (not the internal _owed_count_from_store) controls owed /
    owed_unknown / total_owed directly regardless of whether the heartbeat is enabled.
    """
    return {
        "config_error" : False, "enabled": True, "outcome": None,
        "owed"         : owed, "owed_unknown": owed_unknown, "total_owed": total_owed,
        "result"       : None, "verdict": None, "settings": None, "hold": None,
        "poke_count"   : 0, "task_state": { }, "owed_items": [ ], "delegations": [ ],
        "open_inbound" : [ ], "stale_inbound": [ ], "needs_verification": False,
        "open_gates"   : [ ], "due_gates": [ ],
    }


# ═════════════════════════════════════════════════════════════════════════════
# TestTypeSpecificTTS
# ═════════════════════════════════════════════════════════════════════════════

class TestTypeSpecificTTS:
    """Tests for type-specific TTS message formatting."""

    @patch( "lupin_cli.claude_code.hooks.notification.resolve_stable_session_id", side_effect=lambda x: x )
    @patch( "lupin_cli.claude_code.hooks.notification.emit_json" )
    @patch( "lupin_cli.claude_code.hooks.notification.send_tts" )
    @patch( "lupin_cli.claude_code.hooks.notification.drain_and_acknowledge", return_value=[] )
    @patch( "lupin_cli.claude_code.hooks.notification.get_claude_session_id", return_value="abc12345" )
    @patch( "lupin_cli.claude_code.hooks.notification.log_payload" )
    @patch( "lupin_cli.claude_code.hooks.notification.read_hook_input" )
    def test_permission_prompt_with_message( self, mock_read, mock_log, mock_session,
                                              mock_drain, mock_send, mock_emit, mock_resolve ):
        """permission_prompt includes the full message text with high priority."""
        mock_read.return_value = {
            "type"       : "permission_prompt",
            "message"    : "Claude Code needs your attention",
            "session_id" : "abc12345"
        }

        main()

        call_msg = mock_send.call_args[ 0 ][ 0 ]
        assert call_msg == "Claude Code needs your attention"
        assert mock_send.call_args[ 1 ][ "priority" ] == "high"

    @patch( "lupin_cli.claude_code.hooks.notification.resolve_stable_session_id", side_effect=lambda x: x )
    @patch( "lupin_cli.claude_code.hooks.notification.emit_json" )
    @patch( "lupin_cli.claude_code.hooks.notification.send_tts" )
    @patch( "lupin_cli.claude_code.hooks.notification.drain_and_acknowledge", return_value=[] )
    @patch( "lupin_cli.claude_code.hooks.notification.get_claude_session_id", return_value="abc12345" )
    @patch( "lupin_cli.claude_code.hooks.notification.log_payload" )
    @patch( "lupin_cli.claude_code.hooks.notification.read_hook_input" )
    def test_permission_prompt_no_message( self, mock_read, mock_log, mock_session,
                                            mock_drain, mock_send, mock_emit, mock_resolve ):
        """permission_prompt without message uses generic fallback with high priority."""
        mock_read.return_value = {
            "type"       : "permission_prompt",
            "session_id" : "abc12345"
        }

        main()

        call_msg = mock_send.call_args[ 0 ][ 0 ]
        assert call_msg == "Permission prompt"
        assert mock_send.call_args[ 1 ][ "priority" ] == "high"

    @patch( "lupin_cli.claude_code.hooks.stop._resolve_owed_state",
            return_value=_owed_bundle( owed=False, total_owed=0 ) )
    @patch( "lupin_cli.claude_code.hooks.notification.get_voice_persona", return_value={ "name": "Tiffany" } )
    @patch( "lupin_cli.claude_code.hooks.notification.emit_idle_prompt" )
    @patch( "lupin_cli.claude_code.hooks.notification.resolve_stable_session_id", side_effect=lambda x: x )
    @patch( "lupin_cli.claude_code.hooks.notification.emit_json" )
    @patch( "lupin_cli.claude_code.hooks.notification.send_tts" )
    @patch( "lupin_cli.claude_code.hooks.notification.drain_and_acknowledge", return_value=[] )
    @patch( "lupin_cli.claude_code.hooks.notification.get_claude_session_id", return_value="abc12345" )
    @patch( "lupin_cli.claude_code.hooks.notification.log_payload" )
    @patch( "lupin_cli.claude_code.hooks.notification.read_hook_input" )
    def test_idle_prompt_with_message( self, mock_read, mock_log, mock_session,
                                        mock_drain, mock_send, mock_emit, mock_resolve,
                                        mock_emit_idle, mock_get_persona, mock_owed ):
        """idle_prompt (nothing owed) includes the message text AND emits a
        kind-tagged fleet event."""
        mock_read.return_value = {
            "type"       : "idle_prompt",
            "message"    : "Waiting for response",
            "session_id" : "abc12345"
        }

        main()

        call_msg = mock_send.call_args[ 0 ][ 0 ]
        assert call_msg == "Waiting for response"
        # Step 1.3: the idle branch emits the 4th-signal event with the resolved
        # persona name (dict → name); TTS message is unchanged.
        mock_emit_idle.assert_called_once_with( "abc12345", persona="Tiffany" )

    @patch( "lupin_cli.claude_code.hooks.stop._resolve_owed_state",
            return_value=_owed_bundle( owed=False, total_owed=0 ) )
    @patch( "lupin_cli.claude_code.hooks.notification.get_voice_persona", return_value=None )
    @patch( "lupin_cli.claude_code.hooks.notification.emit_idle_prompt" )
    @patch( "lupin_cli.claude_code.hooks.notification.resolve_stable_session_id", side_effect=lambda x: x )
    @patch( "lupin_cli.claude_code.hooks.notification.emit_json" )
    @patch( "lupin_cli.claude_code.hooks.notification.send_tts" )
    @patch( "lupin_cli.claude_code.hooks.notification.drain_and_acknowledge", return_value=[] )
    @patch( "lupin_cli.claude_code.hooks.notification.get_claude_session_id", return_value="abc12345" )
    @patch( "lupin_cli.claude_code.hooks.notification.log_payload" )
    @patch( "lupin_cli.claude_code.hooks.notification.read_hook_input" )
    def test_idle_prompt_no_message( self, mock_read, mock_log, mock_session,
                                      mock_drain, mock_send, mock_emit, mock_resolve,
                                      mock_emit_idle, mock_get_persona, mock_owed ):
        """idle_prompt without message (nothing owed) uses generic fallback; emits
        with persona=None when no persona is allocated (covers the non-dict branch)."""
        mock_read.return_value = {
            "type"       : "idle_prompt",
            "session_id" : "abc12345"
        }

        main()

        call_msg = mock_send.call_args[ 0 ][ 0 ]
        assert call_msg == "Claude is waiting for input"
        mock_emit_idle.assert_called_once_with( "abc12345", persona=None )

    @patch( "lupin_cli.claude_code.hooks.notification.emit_idle_prompt" )
    @patch( "lupin_cli.claude_code.hooks.notification.resolve_stable_session_id", side_effect=lambda x: x )
    @patch( "lupin_cli.claude_code.hooks.notification.emit_json" )
    @patch( "lupin_cli.claude_code.hooks.notification.send_tts" )
    @patch( "lupin_cli.claude_code.hooks.notification.drain_and_acknowledge", return_value=[] )
    @patch( "lupin_cli.claude_code.hooks.notification.get_claude_session_id", return_value="abc12345" )
    @patch( "lupin_cli.claude_code.hooks.notification.log_payload" )
    @patch( "lupin_cli.claude_code.hooks.notification.read_hook_input" )
    def test_non_idle_branch_does_not_emit_fleet_event( self, mock_read, mock_log, mock_session,
                                                        mock_drain, mock_send, mock_emit, mock_resolve,
                                                        mock_emit_idle ):
        """permission_prompt (and any non-idle type) MUST NOT emit the idle_prompt event."""
        mock_read.return_value = {
            "type"       : "permission_prompt",
            "message"    : "needs you",
            "session_id" : "abc12345"
        }

        main()

        mock_emit_idle.assert_not_called()

    @patch( "lupin_cli.claude_code.hooks.notification.resolve_stable_session_id", side_effect=lambda x: x )
    @patch( "lupin_cli.claude_code.hooks.notification.emit_json" )
    @patch( "lupin_cli.claude_code.hooks.notification.send_tts" )
    @patch( "lupin_cli.claude_code.hooks.notification.drain_and_acknowledge", return_value=[] )
    @patch( "lupin_cli.claude_code.hooks.notification.get_claude_session_id", return_value="abc12345" )
    @patch( "lupin_cli.claude_code.hooks.notification.log_payload" )
    @patch( "lupin_cli.claude_code.hooks.notification.read_hook_input" )
    def test_default_type_with_message( self, mock_read, mock_log, mock_session,
                                         mock_drain, mock_send, mock_emit, mock_resolve ):
        """Default notification type includes message text."""
        mock_read.return_value = {
            "type"       : "info",
            "message"    : "Build completed",
            "session_id" : "abc12345"
        }

        main()

        call_msg = mock_send.call_args[ 0 ][ 0 ]
        assert call_msg == "Notification (info): Build completed"

    @patch( "lupin_cli.claude_code.hooks.notification.resolve_stable_session_id", side_effect=lambda x: x )
    @patch( "lupin_cli.claude_code.hooks.notification.emit_json" )
    @patch( "lupin_cli.claude_code.hooks.notification.send_tts" )
    @patch( "lupin_cli.claude_code.hooks.notification.drain_and_acknowledge", return_value=[] )
    @patch( "lupin_cli.claude_code.hooks.notification.get_claude_session_id", return_value="abc12345" )
    @patch( "lupin_cli.claude_code.hooks.notification.log_payload" )
    @patch( "lupin_cli.claude_code.hooks.notification.read_hook_input" )
    def test_default_type_no_message( self, mock_read, mock_log, mock_session,
                                       mock_drain, mock_send, mock_emit, mock_resolve ):
        """Default notification type without message shows type only."""
        mock_read.return_value = {
            "type"       : "warning",
            "session_id" : "abc12345"
        }

        main()

        call_msg = mock_send.call_args[ 0 ][ 0 ]
        assert call_msg == "Notification: warning"

    # ── §6: idle_prompt delivers pending peer DMs instead of drain-and-discard ──

    @patch( "lupin_cli.claude_code.hooks.stop._resolve_owed_state",
            return_value=_owed_bundle( owed=False, total_owed=0 ) )
    @patch( "lupin_cli.claude_code.hooks.notification.get_voice_persona", return_value={ "name": "Tiffany" } )
    @patch( "lupin_cli.claude_code.hooks.notification.emit_idle_prompt" )
    @patch( "lupin_cli.claude_code.hooks.notification.resolve_stable_session_id", side_effect=lambda x: x )
    @patch( "lupin_cli.claude_code.hooks.notification.emit_json" )
    @patch( "lupin_cli.claude_code.hooks.notification.send_tts" )
    @patch( "lupin_cli.claude_code.hooks.notification.deliver_pending_peer_dms", return_value=[] )
    @patch( "lupin_cli.claude_code.hooks.notification.drain_and_acknowledge", return_value=[] )
    @patch( "lupin_cli.claude_code.hooks.notification.get_claude_session_id", return_value="abc12345" )
    @patch( "lupin_cli.claude_code.hooks.notification.log_payload" )
    @patch( "lupin_cli.claude_code.hooks.notification.read_hook_input" )
    def test_idle_prompt_delivers_pending_dms_not_discard( self, mock_read, mock_log, mock_session,
                                                           mock_drain, mock_deliver, mock_send,
                                                           mock_emit, mock_resolve, mock_emit_idle,
                                                           mock_persona, mock_owed ):
        """At idle_prompt, a pending peer DM is DELIVERED via deliver_pending_peer_dms
        (tmux-wake), NOT drain-and-discarded — Notification emit_json is ignored by
        CC, so tmux is the only path to an idle pane (§6)."""
        mock_read.return_value = {
            "type"       : "idle_prompt",
            "message"    : "idle",
            "session_id" : "abc12345",
        }
        main()
        mock_deliver.assert_called_once_with( "abc12345" )
        mock_drain.assert_not_called()

    @patch( "lupin_cli.claude_code.hooks.notification.resolve_stable_session_id", side_effect=lambda x: x )
    @patch( "lupin_cli.claude_code.hooks.notification.emit_json" )
    @patch( "lupin_cli.claude_code.hooks.notification.send_tts" )
    @patch( "lupin_cli.claude_code.hooks.notification.deliver_pending_peer_dms", return_value=[] )
    @patch( "lupin_cli.claude_code.hooks.notification.drain_and_acknowledge", return_value=[] )
    @patch( "lupin_cli.claude_code.hooks.notification.get_claude_session_id", return_value="abc12345" )
    @patch( "lupin_cli.claude_code.hooks.notification.log_payload" )
    @patch( "lupin_cli.claude_code.hooks.notification.read_hook_input" )
    def test_non_idle_uses_drain_not_deliver( self, mock_read, mock_log, mock_session,
                                              mock_drain, mock_deliver, mock_send,
                                              mock_emit, mock_resolve ):
        """A non-idle notification keeps the legacy drain-and-acknowledge (no DM
        delivery) — DM delivery is gated to idle_prompt."""
        mock_read.return_value = {
            "type"       : "permission_prompt",
            "message"    : "needs you",
            "session_id" : "abc12345",
        }
        main()
        mock_drain.assert_called_once_with( "abc12345" )
        mock_deliver.assert_not_called()


# ═════════════════════════════════════════════════════════════════════════════
# TestIdleBeaconOwedAware  (Bug 1 — idle-beacon false-idle)
# ═════════════════════════════════════════════════════════════════════════════

class TestIdleBeaconOwedAware:
    """
    Bug aa403e03 (idle-status desync): the idle_prompt branch must consult the SAME
    HOLD-AWARE verdict the Stop hook uses (stop._resolve_owed_state) before
    announcing idle — never asserting "nothing owed" when work IS owed, and
    FAIL-SAFE on an uncertain store read.

    HERMETIC: these tests patch stop._resolve_owed_state with a sentinel bundle, so
    they control owed / owed_unknown / total_owed DIRECTLY and do NOT depend on
    ambient ~/.claude/settings.json heartbeat.enabled. (The beacon reaches the
    internal _owed_count_from_store ONLY when the heartbeat is enabled; a test that
    patched _owed_count_from_store would vacuously break under enabled=False —
    Sam's re-loop note. test_hermetic_no_settings_dependency pins this.)
    """

    @patch( "lupin_cli.claude_code.hooks.stop._resolve_owed_state",
            return_value=_owed_bundle( owed=True, total_owed=3 ) )
    @patch( "lupin_cli.claude_code.hooks.notification.get_voice_persona", return_value={ "name": "Tiffany" } )
    @patch( "lupin_cli.claude_code.hooks.notification.emit_idle_prompt" )
    @patch( "lupin_cli.claude_code.hooks.notification.resolve_stable_session_id", side_effect=lambda x: x )
    @patch( "lupin_cli.claude_code.hooks.notification.emit_json" )
    @patch( "lupin_cli.claude_code.hooks.notification.send_tts" )
    @patch( "lupin_cli.claude_code.hooks.notification.deliver_pending_peer_dms", return_value=[] )
    @patch( "lupin_cli.claude_code.hooks.notification.drain_and_acknowledge", return_value=[] )
    @patch( "lupin_cli.claude_code.hooks.notification.get_claude_session_id", return_value="abc12345" )
    @patch( "lupin_cli.claude_code.hooks.notification.log_payload" )
    @patch( "lupin_cli.claude_code.hooks.notification.read_hook_input" )
    def test_idle_with_owed_work_announces_owed_not_idle( self, mock_read, mock_log, mock_session,
                                                          mock_drain, mock_deliver, mock_send,
                                                          mock_emit, mock_resolve, mock_emit_idle,
                                                          mock_persona, mock_state ):
        """owed>0: the beacon surfaces the owed count and does NOT emit the bare
        idle message (the false-idle lie). Driven hermetically by the shared verdict."""
        mock_read.return_value = {
            "type"       : "idle_prompt",
            "message"    : "Claude is waiting for input",
            "session_id" : "abc12345",
        }
        main()
        call_msg = mock_send.call_args[ 0 ][ 0 ]
        assert "3" in call_msg, f"owed count missing from beacon: {call_msg!r}"
        assert "owed" in call_msg.lower(), f"owed wording missing: {call_msg!r}"
        assert call_msg != "Claude is waiting for input", "still emitting bare idle beacon"
        mock_state.assert_called_once()   # the beacon consulted the shared hold-aware verdict

    @patch( "lupin_cli.claude_code.hooks.stop._resolve_owed_state",
            return_value=_owed_bundle( owed=True, total_owed=1 ) )
    @patch( "lupin_cli.claude_code.hooks.notification.get_voice_persona", return_value={ "name": "Tiffany" } )
    @patch( "lupin_cli.claude_code.hooks.notification.emit_idle_prompt" )
    @patch( "lupin_cli.claude_code.hooks.notification.resolve_stable_session_id", side_effect=lambda x: x )
    @patch( "lupin_cli.claude_code.hooks.notification.emit_json" )
    @patch( "lupin_cli.claude_code.hooks.notification.send_tts" )
    @patch( "lupin_cli.claude_code.hooks.notification.deliver_pending_peer_dms", return_value=[] )
    @patch( "lupin_cli.claude_code.hooks.notification.drain_and_acknowledge", return_value=[] )
    @patch( "lupin_cli.claude_code.hooks.notification.get_claude_session_id", return_value="abc12345" )
    @patch( "lupin_cli.claude_code.hooks.notification.log_payload" )
    @patch( "lupin_cli.claude_code.hooks.notification.read_hook_input" )
    def test_idle_with_single_owed_item_uses_singular( self, mock_read, mock_log, mock_session,
                                                       mock_drain, mock_deliver, mock_send,
                                                       mock_emit, mock_resolve, mock_emit_idle,
                                                       mock_persona, mock_owed ):
        """owed==1: singular wording ("1 item owed", not "1 items owed")."""
        mock_read.return_value = {
            "type"       : "idle_prompt",
            "message"    : "Claude is waiting for input",
            "session_id" : "abc12345",
        }
        main()
        call_msg = mock_send.call_args[ 0 ][ 0 ]
        assert "1 item owed" in call_msg, f"expected singular wording: {call_msg!r}"

    @patch( "lupin_cli.claude_code.hooks.stop._resolve_owed_state",
            return_value=_owed_bundle( owed=False, total_owed=0 ) )
    @patch( "lupin_cli.claude_code.hooks.notification.get_voice_persona", return_value={ "name": "Tiffany" } )
    @patch( "lupin_cli.claude_code.hooks.notification.emit_idle_prompt" )
    @patch( "lupin_cli.claude_code.hooks.notification.resolve_stable_session_id", side_effect=lambda x: x )
    @patch( "lupin_cli.claude_code.hooks.notification.emit_json" )
    @patch( "lupin_cli.claude_code.hooks.notification.send_tts" )
    @patch( "lupin_cli.claude_code.hooks.notification.deliver_pending_peer_dms", return_value=[] )
    @patch( "lupin_cli.claude_code.hooks.notification.drain_and_acknowledge", return_value=[] )
    @patch( "lupin_cli.claude_code.hooks.notification.get_claude_session_id", return_value="abc12345" )
    @patch( "lupin_cli.claude_code.hooks.notification.log_payload" )
    @patch( "lupin_cli.claude_code.hooks.notification.read_hook_input" )
    def test_idle_with_zero_owed_announces_normally( self, mock_read, mock_log, mock_session,
                                                     mock_drain, mock_deliver, mock_send,
                                                     mock_emit, mock_resolve, mock_emit_idle,
                                                     mock_persona, mock_owed ):
        """owed==0 (determinate): the ONLY case that may emit the normal idle
        message verbatim."""
        mock_read.return_value = {
            "type"       : "idle_prompt",
            "message"    : "Claude is waiting for input",
            "session_id" : "abc12345",
        }
        main()
        call_msg = mock_send.call_args[ 0 ][ 0 ]
        assert call_msg == "Claude is waiting for input"

    @patch( "lupin_cli.claude_code.hooks.stop._resolve_owed_state",
            return_value=_owed_bundle( owed=False, owed_unknown=True ) )
    @patch( "lupin_cli.claude_code.hooks.notification.get_voice_persona", return_value={ "name": "Tiffany" } )
    @patch( "lupin_cli.claude_code.hooks.notification.emit_idle_prompt" )
    @patch( "lupin_cli.claude_code.hooks.notification.resolve_stable_session_id", side_effect=lambda x: x )
    @patch( "lupin_cli.claude_code.hooks.notification.emit_json" )
    @patch( "lupin_cli.claude_code.hooks.notification.send_tts" )
    @patch( "lupin_cli.claude_code.hooks.notification.deliver_pending_peer_dms", return_value=[] )
    @patch( "lupin_cli.claude_code.hooks.notification.drain_and_acknowledge", return_value=[] )
    @patch( "lupin_cli.claude_code.hooks.notification.get_claude_session_id", return_value="abc12345" )
    @patch( "lupin_cli.claude_code.hooks.notification.log_payload" )
    @patch( "lupin_cli.claude_code.hooks.notification.read_hook_input" )
    def test_idle_with_unknown_owed_fails_safe_no_nothing_owed( self, mock_read, mock_log, mock_session,
                                                                mock_drain, mock_deliver, mock_send,
                                                                mock_emit, mock_resolve, mock_emit_idle,
                                                                mock_persona, mock_owed ):
        """owed_unknown (ok=False, bad/timed-out read): FAIL-SAFE — never assert
        "nothing owed". Emit the neutral message, no owed claim either way."""
        mock_read.return_value = {
            "type"       : "idle_prompt",
            "message"    : "Claude is waiting for input",
            "session_id" : "abc12345",
        }
        main()
        call_msg = mock_send.call_args[ 0 ][ 0 ]
        assert "owed" not in call_msg.lower(), f"must not assert owed status on uncertain read: {call_msg!r}"
        assert call_msg == "Claude is waiting for input"

    @patch( "lupin_cli.claude_code.hooks.stop._resolve_owed_state",
            return_value=_owed_bundle( owed=True, total_owed=1 ) )
    @patch( "lupin_cli.claude_code.hooks.notification.get_voice_persona", return_value={ "name": "Tiffany" } )
    @patch( "lupin_cli.claude_code.hooks.notification.emit_idle_prompt" )
    @patch( "lupin_cli.claude_code.hooks.notification.resolve_stable_session_id", side_effect=lambda x: x )
    @patch( "lupin_cli.claude_code.hooks.notification.emit_json" )
    @patch( "lupin_cli.claude_code.hooks.notification.send_tts" )
    @patch( "lupin_cli.claude_code.hooks.notification.deliver_pending_peer_dms", return_value=[] )
    @patch( "lupin_cli.claude_code.hooks.notification.drain_and_acknowledge", return_value=[] )
    @patch( "lupin_cli.claude_code.hooks.notification.get_claude_session_id", return_value="abc12345" )
    @patch( "lupin_cli.claude_code.hooks.notification.log_payload" )
    @patch( "lupin_cli.claude_code.hooks.notification.read_hook_input" )
    def test_inbound_or_delegation_only_owed_counts( self, mock_read, mock_log, mock_session,
                                                     mock_drain, mock_deliver, mock_send,
                                                     mock_emit, mock_resolve, mock_emit_idle,
                                                     mock_persona, mock_state ):
        """total_owed semantics (Sam re-loop c): owed via a NON-store referent —
        e.g. store count 0 + 1 delegation → total_owed 1 — still beacons "1 item
        owed". The beacon trusts total_owed from the shared verdict (owed_items +
        delegations + open_inbound), NOT the raw store count."""
        mock_read.return_value = {
            "type": "idle_prompt", "message": "Claude is waiting for input", "session_id": "abc12345",
        }
        main()
        assert mock_send.call_args[ 0 ][ 0 ] == "Idle, but 1 item owed"

    @patch( "lupin_cli.claude_code.hooks.stop.load_heartbeat_settings" )
    @patch( "lupin_cli.claude_code.hooks.stop._resolve_owed_state",
            return_value=_owed_bundle( owed=True, total_owed=2 ) )
    @patch( "lupin_cli.claude_code.hooks.notification.get_voice_persona", return_value={ "name": "Tiffany" } )
    @patch( "lupin_cli.claude_code.hooks.notification.emit_idle_prompt" )
    @patch( "lupin_cli.claude_code.hooks.notification.resolve_stable_session_id", side_effect=lambda x: x )
    @patch( "lupin_cli.claude_code.hooks.notification.emit_json" )
    @patch( "lupin_cli.claude_code.hooks.notification.send_tts" )
    @patch( "lupin_cli.claude_code.hooks.notification.deliver_pending_peer_dms", return_value=[] )
    @patch( "lupin_cli.claude_code.hooks.notification.drain_and_acknowledge", return_value=[] )
    @patch( "lupin_cli.claude_code.hooks.notification.get_claude_session_id", return_value="abc12345" )
    @patch( "lupin_cli.claude_code.hooks.notification.log_payload" )
    @patch( "lupin_cli.claude_code.hooks.notification.read_hook_input" )
    def test_hermetic_no_settings_dependency( self, mock_read, mock_log, mock_session,
                                              mock_drain, mock_deliver, mock_send,
                                              mock_emit, mock_resolve, mock_emit_idle,
                                              mock_persona, mock_state, mock_settings ):
        """HERMETICITY PROOF (Sam re-loop a): with the shared verdict injected, the
        beacon NEVER reaches load_heartbeat_settings — so its output is independent
        of ambient ~/.claude/settings.json heartbeat.enabled (identical with enabled
        forced EITHER way). This is why patching _resolve_owed_state (not the internal
        _owed_count_from_store) is the correct, ambient-free seam."""
        mock_read.return_value = {
            "type": "idle_prompt", "message": "Claude is waiting for input", "session_id": "abc12345",
        }
        main()
        assert mock_send.call_args[ 0 ][ 0 ] == "Idle, but 2 items owed"
        mock_settings.assert_not_called()


# ═════════════════════════════════════════════════════════════════════════════
# TestMessageTruncation
# ═════════════════════════════════════════════════════════════════════════════

class TestMessageTruncation:
    """Tests for message truncation in default notification type."""

    @patch( "lupin_cli.claude_code.hooks.notification.resolve_stable_session_id", side_effect=lambda x: x )
    @patch( "lupin_cli.claude_code.hooks.notification.emit_json" )
    @patch( "lupin_cli.claude_code.hooks.notification.send_tts" )
    @patch( "lupin_cli.claude_code.hooks.notification.drain_and_acknowledge", return_value=[] )
    @patch( "lupin_cli.claude_code.hooks.notification.get_claude_session_id", return_value="abc12345" )
    @patch( "lupin_cli.claude_code.hooks.notification.log_payload" )
    @patch( "lupin_cli.claude_code.hooks.notification.read_hook_input" )
    def test_long_message_truncated_at_80( self, mock_read, mock_log, mock_session,
                                            mock_drain, mock_send, mock_emit, mock_resolve ):
        """Messages longer than 80 chars are truncated with ellipsis."""
        long_msg = "X" * 100
        mock_read.return_value = {
            "type"       : "info",
            "message"    : long_msg,
            "session_id" : "abc12345"
        }

        main()

        call_msg = mock_send.call_args[ 0 ][ 0 ]
        assert "X" * 80 + "..." in call_msg
        assert len( long_msg ) not in [ len( call_msg ) ]  # Confirm truncation happened


# ═════════════════════════════════════════════════════════════════════════════
# TestVoiceDrain
# ═════════════════════════════════════════════════════════════════════════════

class TestVoiceDrain:
    """Tests for voice buffer drain in Notification hook."""

    @patch( "lupin_cli.claude_code.hooks.notification.resolve_stable_session_id", side_effect=lambda x: x )
    @patch( "lupin_cli.claude_code.hooks.notification.emit_json" )
    @patch( "lupin_cli.claude_code.hooks.notification.send_tts" )
    @patch( "lupin_cli.claude_code.hooks.notification.drain_and_acknowledge" )
    @patch( "lupin_cli.claude_code.hooks.notification.get_claude_session_id", return_value="fallback1" )
    @patch( "lupin_cli.claude_code.hooks.notification.log_payload" )
    @patch( "lupin_cli.claude_code.hooks.notification.read_hook_input" )
    def test_drain_called( self, mock_read, mock_log, mock_session,
                            mock_drain, mock_send, mock_emit, mock_resolve ):
        """Voice drain is called with resolved session_id."""
        mock_read.return_value = {
            "type"    : "info",
            "message" : "test"
        }
        mock_drain.return_value = []

        main()

        mock_drain.assert_called_once_with( "fallback1" )


# ═════════════════════════════════════════════════════════════════════════════
# TestEmptyPayload
# ═════════════════════════════════════════════════════════════════════════════

class TestEmptyPayload:
    """Tests for empty payload handling."""

    @patch( "lupin_cli.claude_code.hooks.notification.emit_json" )
    @patch( "lupin_cli.claude_code.hooks.notification.read_hook_input", return_value={} )
    def test_empty_payload_emits_empty( self, mock_read, mock_emit ):
        """Empty payload immediately emits {} and exits."""
        with pytest.raises( SystemExit ):
            main()

        mock_emit.assert_called_once_with( {} )
