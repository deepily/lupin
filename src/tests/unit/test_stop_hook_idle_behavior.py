#!/usr/bin/env python3
"""
Unit tests for the Thread A 3-way idle-behavior enum on the Stop hook
(stop hook idle behavior = none | ask | idle_announce, default idle_announce):
the _stop_hook_idle_behavior config reader, the _idle_sentence / _announce_idle
idle-announce helpers, and the main() Branch-C gate's `none` + `idle_announce`
branches. See src/rnd/v0.1.8/2026.06.06-heartbeat-poke-scaffold-vs-v2.1-supersession.md.
"""
import os
import sys
from unittest.mock import patch, MagicMock

import pytest

# Bootstrap
_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

import lupin_cli.claude_code.hooks.stop as stop
from lupin_cli.claude_code.hooks.stop import (
    main, _stop_hook_idle_behavior, _idle_sentence, _announce_idle, DEFAULT_IDLE_BEHAVIOR,
)
from lupin_cli.notifications.notification_models import NotificationPriority


def _bundle( owed=False, owed_unknown=False, total_owed=0 ):
    """
    A minimal _resolve_owed_state return (bug aa403e03) for driving the owed-aware
    idle-announce. main() now resolves this shared verdict and threads owed /
    owed_unknown / total_owed into _announce_idle, so tests patch _resolve_owed_state
    with a controlled bundle and assert those VALUES reach the announce.
    """
    return {
        "config_error" : False, "enabled": True, "outcome": None,
        "owed"         : owed, "owed_unknown": owed_unknown, "total_owed": total_owed,
        "result"       : None, "verdict": None, "settings": None, "hold": None,
        "poke_count"   : 0, "task_state": { }, "owed_items": [ ], "delegations": [ ],
        "open_inbound" : [ ], "stale_inbound": [ ], "needs_verification": False,
        "open_gates"   : [ ], "due_gates": [ ],
    }


# ── _stop_hook_idle_behavior (config reader) ──────────────────────────────────

class TestIdleBehaviorReader:

    @pytest.mark.parametrize( "configured", [ "none", "ask", "idle_announce" ] )
    def test_valid_values_passthrough( self, configured ):
        with patch.object( stop, "ConfigurationManager" ) as MockCfg:
            MockCfg.return_value.get.return_value = configured
            assert _stop_hook_idle_behavior() == configured

    def test_case_and_whitespace_normalized( self ):
        with patch.object( stop, "ConfigurationManager" ) as MockCfg:
            MockCfg.return_value.get.return_value = "  ASK  "
            assert _stop_hook_idle_behavior() == "ask"

    def test_unrecognized_value_falls_back_to_default( self ):
        with patch.object( stop, "ConfigurationManager" ) as MockCfg:
            MockCfg.return_value.get.return_value = "bogus"
            assert _stop_hook_idle_behavior() == DEFAULT_IDLE_BEHAVIOR == "idle_announce"

    def test_none_value_falls_back_to_default( self ):
        with patch.object( stop, "ConfigurationManager" ) as MockCfg:
            MockCfg.return_value.get.return_value = None
            assert _stop_hook_idle_behavior() == "idle_announce"

    def test_configmanager_error_falls_back_to_default( self ):
        with patch.object( stop, "ConfigurationManager", side_effect=RuntimeError( "no config" ) ):
            assert _stop_hook_idle_behavior() == "idle_announce"


# ── _idle_sentence ────────────────────────────────────────────────────────────

class TestIdleSentence:
    def test_with_persona( self ):
        assert _idle_sentence( "Rio" ) == "Momentarily idle."

    def test_without_persona( self ):
        assert _idle_sentence( None ) == "Momentarily idle."

    def test_owed_unknown_says_unknown_not_idle( self ):
        """FACET-2: store unreachable → the sentence must NOT assert idle."""
        assert _idle_sentence( "Rio", owed_unknown=True ) == "Owed status unknown."

    def test_owed_unknown_false_default_is_idle( self ):
        assert _idle_sentence( "Rio", owed_unknown=False ) == "Momentarily idle."


# ── _announce_idle ────────────────────────────────────────────────────────────

class TestAnnounceIdle:

    @patch( "lupin_cli.claude_code.hooks.stop.build_sender_id_for_cc",
            return_value="claude.code@lupin.deepily.ai#abc12345" )
    @patch( "lupin_cli.claude_code.hooks.stop.notify_user_async" )
    def test_posts_low_priority_persona_notify( self, mock_notify, mock_sender ):
        _announce_idle( "abc12345", "Rio" )

        mock_notify.assert_called_once()
        request = mock_notify.call_args[ 0 ][ 0 ]
        assert request.message  == "Momentarily idle."
        assert request.priority == NotificationPriority.LOW
        assert request.sender_id == "claude.code@lupin.deepily.ai#abc12345"

    @patch( "lupin_cli.claude_code.hooks.stop.log_to_stream" )
    @patch( "lupin_cli.claude_code.hooks.stop.build_sender_id_for_cc", return_value="x" )
    @patch( "lupin_cli.claude_code.hooks.stop.notify_user_async",
            side_effect=RuntimeError( "server down" ) )
    def test_failsafe_swallows_errors( self, mock_notify, mock_sender, mock_log ):
        # Must NOT raise — the idle announce can never block the Stop.
        _announce_idle( "abc12345", "Rio" )
        mock_log.assert_called_once()
        assert mock_log.call_args[ 1 ][ "extra" ][ "phase" ] == "idle_announce_error"

    @patch( "lupin_cli.claude_code.hooks.stop.build_sender_id_for_cc",
            return_value="claude.code@lupin.deepily.ai#abc12345" )
    @patch( "lupin_cli.claude_code.hooks.stop.notify_user_async" )
    def test_owed_unknown_beacon_does_not_claim_nothing_owed( self, mock_notify, mock_sender ):
        """FACET-2 FLIP: store unreachable → the beacon must render the UNKNOWN
        message + abstract, NEVER "nothing owed" (which conflates UNKNOWN with
        genuine IDLE — the whole-fleet :7999-outage false-idle)."""
        _announce_idle( "abc12345", "Rio", owed_unknown=True )
        request = mock_notify.call_args[ 0 ][ 0 ]
        assert request.message == "Owed status unknown."
        assert "nothing owed" not in request.abstract
        assert "unknown" in request.abstract.lower()
        assert "verify manually" in request.abstract.lower()

    @patch( "lupin_cli.claude_code.hooks.stop.build_sender_id_for_cc",
            return_value="claude.code@lupin.deepily.ai#abc12345" )
    @patch( "lupin_cli.claude_code.hooks.stop.notify_user_async" )
    def test_owed_known_beacon_keeps_nothing_owed( self, mock_notify, mock_sender ):
        """Determinate not-owed (default) keeps the genuine-idle beacon verbatim."""
        _announce_idle( "abc12345", "Rio" )
        request = mock_notify.call_args[ 0 ][ 0 ]
        assert request.abstract == "Heartbeat: idle — nothing owed."


# ── main() Branch-C gate: the new enum branches ───────────────────────────────

class TestIdleBehaviorGate:

    def test_none_takes_no_action( self ):
        with patch( "lupin_cli.claude_code.hooks.stop.emit_json" ) as mock_emit, \
             patch( "lupin_cli.claude_code.hooks.stop._arm_idle_waiter" ) as mock_arm, \
             patch( "lupin_cli.claude_code.hooks.stop._ask_anything_else" ) as mock_ask, \
             patch( "lupin_cli.claude_code.hooks.stop._announce_idle" ) as mock_announce, \
             patch( "lupin_cli.claude_code.hooks.stop._run_heartbeat", return_value=( None, False ) ), \
             patch( "lupin_cli.claude_code.hooks.stop._stop_hook_idle_behavior", return_value="none" ), \
             patch( "lupin_cli.claude_code.hooks.stop.get_speakerphone", return_value=False ), \
             patch( "lupin_cli.claude_code.hooks.stop.drain_and_acknowledge", return_value=[] ), \
             patch( "lupin_cli.claude_code.hooks.stop.reset_stop_block_count" ), \
             patch( "lupin_cli.claude_code.hooks.stop.resolve_stable_session_id", side_effect=lambda x: x ), \
             patch( "lupin_cli.claude_code.hooks.stop.log_payload" ), \
             patch( "lupin_cli.claude_code.hooks.stop.read_hook_input",
                    return_value={ "stop_hook_active": False, "session_id": "abc12345" } ):
            main()
            mock_emit.assert_called_once_with( {} )
            mock_arm.assert_not_called()
            mock_ask.assert_not_called()
            mock_announce.assert_not_called()

    def test_idle_announce_announces_then_allows_stop( self ):
        # bug aa403e03: main() resolves the shared verdict and threads it into the
        # announce. Drive a genuinely-idle bundle and assert the announce receives
        # the explicit owed-aware VALUES (owed=False, total_owed=0) — not just the
        # new shape. _run_heartbeat is patched to no-poke so the idle path runs.
        with patch( "lupin_cli.claude_code.hooks.stop.emit_json" ) as mock_emit, \
             patch( "lupin_cli.claude_code.hooks.stop._arm_idle_waiter" ) as mock_arm, \
             patch( "lupin_cli.claude_code.hooks.stop._ask_anything_else" ) as mock_ask, \
             patch( "lupin_cli.claude_code.hooks.stop._announce_idle" ) as mock_announce, \
             patch( "lupin_cli.claude_code.hooks.stop._resolve_owed_state", return_value=_bundle( owed=False ) ), \
             patch( "lupin_cli.claude_code.hooks.stop.get_voice_persona", return_value={ "name": "Rio" } ), \
             patch( "lupin_cli.claude_code.hooks.stop._run_heartbeat", return_value=( None, False ) ), \
             patch( "lupin_cli.claude_code.hooks.stop._stop_hook_idle_behavior", return_value="idle_announce" ), \
             patch( "lupin_cli.claude_code.hooks.stop.get_speakerphone", return_value=False ), \
             patch( "lupin_cli.claude_code.hooks.stop.drain_and_acknowledge", return_value=[] ), \
             patch( "lupin_cli.claude_code.hooks.stop.reset_stop_block_count" ), \
             patch( "lupin_cli.claude_code.hooks.stop.resolve_stable_session_id", side_effect=lambda x: x ), \
             patch( "lupin_cli.claude_code.hooks.stop.log_payload" ), \
             patch( "lupin_cli.claude_code.hooks.stop.read_hook_input",
                    return_value={ "stop_hook_active": False, "session_id": "abc12345" } ):
            main()
            mock_announce.assert_called_once_with( "abc12345", "Rio",
                                                   owed_unknown=False, owed=False, total_owed=0, muted=False )
            mock_emit.assert_called_once_with( {} )
            mock_arm.assert_not_called()
            mock_ask.assert_not_called()

    def test_owed_verdict_threads_owed_args_to_announce( self ):
        """bug aa403e03 (STRENGTHEN): a hold-aware OWED verdict at idle (e.g. the
        poke-cap halted poking) must thread owed=True + total_owed into the
        announce, so the Stop beacon surfaces 'Idle, but N owed' — consistent with
        the Notification idle-beacon."""
        with patch( "lupin_cli.claude_code.hooks.stop.emit_json" ) as mock_emit, \
             patch( "lupin_cli.claude_code.hooks.stop._announce_idle" ) as mock_announce, \
             patch( "lupin_cli.claude_code.hooks.stop._resolve_owed_state",
                    return_value=_bundle( owed=True, total_owed=2 ) ), \
             patch( "lupin_cli.claude_code.hooks.stop.get_voice_persona", return_value={ "name": "Rio" } ), \
             patch( "lupin_cli.claude_code.hooks.stop._run_heartbeat", return_value=( None, False ) ), \
             patch( "lupin_cli.claude_code.hooks.stop._stop_hook_idle_behavior", return_value="idle_announce" ), \
             patch( "lupin_cli.claude_code.hooks.stop.get_speakerphone", return_value=False ), \
             patch( "lupin_cli.claude_code.hooks.stop.drain_and_acknowledge", return_value=[] ), \
             patch( "lupin_cli.claude_code.hooks.stop.reset_stop_block_count" ), \
             patch( "lupin_cli.claude_code.hooks.stop.resolve_stable_session_id", side_effect=lambda x: x ), \
             patch( "lupin_cli.claude_code.hooks.stop.log_payload" ), \
             patch( "lupin_cli.claude_code.hooks.stop.read_hook_input",
                    return_value={ "stop_hook_active": False, "session_id": "abc12345" } ):
            main()
            mock_announce.assert_called_once_with( "abc12345", "Rio",
                                                   owed_unknown=False, owed=True, total_owed=2, muted=False )
            mock_emit.assert_called_once_with( {} )

    def test_store_unreachable_threads_owed_unknown_to_announce( self ):
        """FACET-2 END-TO-END (bug aa403e03): when the shared verdict reports
        owed_unknown=True (store down, no poke), main() must thread it into
        _announce_idle so the beacon renders UNKNOWN, not "nothing owed". Now driven
        by _resolve_owed_state (the hold-aware verdict), not _run_heartbeat's tuple."""
        with patch( "lupin_cli.claude_code.hooks.stop.emit_json" ) as mock_emit, \
             patch( "lupin_cli.claude_code.hooks.stop._announce_idle" ) as mock_announce, \
             patch( "lupin_cli.claude_code.hooks.stop._resolve_owed_state",
                    return_value=_bundle( owed=False, owed_unknown=True ) ), \
             patch( "lupin_cli.claude_code.hooks.stop.get_voice_persona", return_value={ "name": "Rio" } ), \
             patch( "lupin_cli.claude_code.hooks.stop._run_heartbeat", return_value=( None, True ) ), \
             patch( "lupin_cli.claude_code.hooks.stop._stop_hook_idle_behavior", return_value="idle_announce" ), \
             patch( "lupin_cli.claude_code.hooks.stop.get_speakerphone", return_value=False ), \
             patch( "lupin_cli.claude_code.hooks.stop.drain_and_acknowledge", return_value=[] ), \
             patch( "lupin_cli.claude_code.hooks.stop.reset_stop_block_count" ), \
             patch( "lupin_cli.claude_code.hooks.stop.resolve_stable_session_id", side_effect=lambda x: x ), \
             patch( "lupin_cli.claude_code.hooks.stop.log_payload" ), \
             patch( "lupin_cli.claude_code.hooks.stop.read_hook_input",
                    return_value={ "stop_hook_active": False, "session_id": "abc12345" } ):
            main()
            mock_announce.assert_called_once_with( "abc12345", "Rio",
                                                   owed_unknown=True, owed=False, total_owed=0, muted=False )
            mock_emit.assert_called_once_with( {} )

    def test_ask_handles_invalid_idle_settings( self ):
        """'ask' + load_idle_settings raises ValueError → logged, fail-safe to immediate ask."""
        with patch( "lupin_cli.claude_code.hooks.stop.emit_json" ) as mock_emit, \
             patch( "lupin_cli.claude_code.hooks.stop._arm_idle_waiter" ) as mock_arm, \
             patch( "lupin_cli.claude_code.hooks.stop._ask_anything_else", return_value={} ) as mock_ask, \
             patch( "lupin_cli.claude_code.hooks.stop.log_to_stream" ) as mock_log, \
             patch( "lupin_cli.claude_code.hooks.stop.load_idle_settings",
                    side_effect=ValueError( "bad backoff" ) ), \
             patch( "lupin_cli.claude_code.hooks.stop._run_heartbeat", return_value=( None, False ) ), \
             patch( "lupin_cli.claude_code.hooks.stop._stop_hook_idle_behavior", return_value="ask" ), \
             patch( "lupin_cli.claude_code.hooks.stop.get_speakerphone", return_value=False ), \
             patch( "lupin_cli.claude_code.hooks.stop.drain_and_acknowledge", return_value=[] ), \
             patch( "lupin_cli.claude_code.hooks.stop.reset_stop_block_count" ), \
             patch( "lupin_cli.claude_code.hooks.stop.resolve_stable_session_id", side_effect=lambda x: x ), \
             patch( "lupin_cli.claude_code.hooks.stop.log_payload" ), \
             patch( "lupin_cli.claude_code.hooks.stop.read_hook_input",
                    return_value={ "stop_hook_active": False, "session_id": "abc12345" } ):
            main()
            # invalid settings logged, then fail-safe (enabled=False) → immediate ask, no waiter
            phases = [ c[ 1 ][ "extra" ][ "phase" ] for c in mock_log.call_args_list
                       if "extra" in c[ 1 ] and "phase" in c[ 1 ][ "extra" ] ]
            assert "idle_settings_invalid" in phases
            mock_arm.assert_not_called()
            mock_ask.assert_called_once()

    def test_idle_announce_handles_missing_persona( self ):
        # bug aa403e03: None persona threaded AND the owed-aware args present.
        with patch( "lupin_cli.claude_code.hooks.stop.emit_json" ) as mock_emit, \
             patch( "lupin_cli.claude_code.hooks.stop._announce_idle" ) as mock_announce, \
             patch( "lupin_cli.claude_code.hooks.stop._resolve_owed_state", return_value=_bundle( owed=False ) ), \
             patch( "lupin_cli.claude_code.hooks.stop.get_voice_persona", return_value=None ), \
             patch( "lupin_cli.claude_code.hooks.stop._run_heartbeat", return_value=( None, False ) ), \
             patch( "lupin_cli.claude_code.hooks.stop._stop_hook_idle_behavior", return_value="idle_announce" ), \
             patch( "lupin_cli.claude_code.hooks.stop.get_speakerphone", return_value=False ), \
             patch( "lupin_cli.claude_code.hooks.stop.drain_and_acknowledge", return_value=[] ), \
             patch( "lupin_cli.claude_code.hooks.stop.reset_stop_block_count" ), \
             patch( "lupin_cli.claude_code.hooks.stop.resolve_stable_session_id", side_effect=lambda x: x ), \
             patch( "lupin_cli.claude_code.hooks.stop.log_payload" ), \
             patch( "lupin_cli.claude_code.hooks.stop.read_hook_input",
                    return_value={ "stop_hook_active": False, "session_id": "abc12345" } ):
            main()
            mock_announce.assert_called_once_with( "abc12345", None,
                                                   owed_unknown=False, owed=False, total_owed=0, muted=False )   # None persona threaded
            mock_emit.assert_called_once_with( {} )


# ── main() speakerphone branch: silent idle-announce (Rick, 2026-06-08) ───────
# The silent idle-announce fires INSIDE the speakerphone branch, downstream of
# the §3 heartbeat (patched to no-poke here — the poke matrix lives in
# test_stop_hook_heartbeat.py::TestMainSpeakerphonePokeMatrix). Gated to
# idle_announce ONLY (ask/none stay fully silent — the blocking ask is correctly
# skipped). _announce_idle posts at LOW priority → the client renders the DOM
# card WITHOUT TTS (no chorus-TTS spam). The branch ends in sys.exit(0), so each
# run raises SystemExit.

class TestSpeakerphoneIdleAnnounce:

    def _run_speakerphone_main( self, idle_behavior, persona, bundle=None ):
        # bug aa403e03: the speakerphone branch resolves the shared verdict ONCE and
        # threads it into both the poke and the idle-announce. Patch _resolve_owed_state
        # with a controlled bundle so the announce-arg assertion checks the owed values.
        if bundle is None:
            bundle = _bundle( owed=False )
        with patch( "lupin_cli.claude_code.hooks.stop._announce_idle" ) as mock_announce, \
             patch( "lupin_cli.claude_code.hooks.stop._resolve_owed_state", return_value=bundle ), \
             patch( "lupin_cli.claude_code.hooks.stop.emit_json" ) as mock_emit, \
             patch( "lupin_cli.claude_code.hooks.stop._try_auto_narrate" ), \
             patch( "lupin_cli.claude_code.hooks.stop._run_heartbeat", return_value=( None, False ) ), \
             patch( "lupin_cli.claude_code.hooks.stop._has_pending_voice", return_value=False ), \
             patch( "lupin_cli.claude_code.hooks.stop.get_voice_persona", return_value=persona ), \
             patch( "lupin_cli.claude_code.hooks.stop._stop_hook_idle_behavior", return_value=idle_behavior ), \
             patch( "lupin_cli.claude_code.hooks.stop.get_speakerphone", return_value=True ), \
             patch( "lupin_cli.claude_code.hooks.stop.log_to_stream" ), \
             patch( "lupin_cli.claude_code.hooks.stop.resolve_stable_session_id", side_effect=lambda x: x ), \
             patch( "lupin_cli.claude_code.hooks.stop.log_payload" ), \
             patch( "lupin_cli.claude_code.hooks.stop.read_hook_input",
                    return_value={ "stop_hook_active": False, "session_id": "abc12345" } ):
            with pytest.raises( SystemExit ):
                main()
            mock_emit.assert_called_once_with( {} )   # speakerphone still allows the stop
            return mock_announce

    def test_speakerphone_idle_announce_fires_silent_bubble( self ):
        """speakerphone + idle_announce → _announce_idle fires (LOW pri → silent DOM
        bubble) with the owed-aware args from the shared verdict (bug aa403e03)."""
        mock_announce = self._run_speakerphone_main( "idle_announce", { "name": "Rachel" } )
        mock_announce.assert_called_once_with( "abc12345", "Rachel",
                                               owed_unknown=False, owed=False, total_owed=0, muted=False )

    def test_speakerphone_idle_announce_owed_threads_args( self ):
        """bug aa403e03 (STRENGTHEN): speakerphone + idle_announce + an OWED shared
        verdict → the owed args reach the announce on the speakerphone path too."""
        mock_announce = self._run_speakerphone_main( "idle_announce", { "name": "Rachel" },
                                                     bundle=_bundle( owed=True, total_owed=4 ) )
        mock_announce.assert_called_once_with( "abc12345", "Rachel",
                                               owed_unknown=False, owed=True, total_owed=4, muted=False )

    def test_speakerphone_idle_announce_missing_persona( self ):
        """speakerphone + idle_announce + no persona → _announce_idle fires with None threaded."""
        mock_announce = self._run_speakerphone_main( "idle_announce", None )
        mock_announce.assert_called_once_with( "abc12345", None,
                                               owed_unknown=False, owed=False, total_owed=0, muted=False )

    def test_speakerphone_ask_stays_fully_silent( self ):
        """speakerphone + ask → NO announce (blocking ask skipped, no silent-degrade per Rick)."""
        mock_announce = self._run_speakerphone_main( "ask", { "name": "Rachel" } )
        mock_announce.assert_not_called()

    def test_speakerphone_none_stays_silent( self ):
        """speakerphone + none → NO announce."""
        mock_announce = self._run_speakerphone_main( "none", { "name": "Rachel" } )
        mock_announce.assert_not_called()


if __name__ == "__main__":
    sys.exit( pytest.main( [ __file__, "-v" ] ) )
