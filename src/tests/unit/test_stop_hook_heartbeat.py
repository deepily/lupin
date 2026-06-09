#!/usr/bin/env python3
"""
Unit + integration tests for the Stop-hook Heartbeat Branch-C adapter (v2).

Layers:
  1. _run_heartbeat — the side-effecting adapter shell, driven against the REAL
     pure leaves (heartbeat_hold + heartbeat_work_owed + heartbeat_decision) so
     the v2 seam composition is validated, not mocked away. The Task*-replay
     SOURCE is injected via patched fetch_task_work_owed / is_task_set_empty
     (the reader itself is unit-tested in test_heartbeat_task_state.py).
  2. _emit_genuine_idle — the §6.2 genuine-idle declaration beacon (edge-trigger
     gate delegated to heartbeat_events.is_idle_transition).
  3. _notify_cap_reached — log-only cap FYI.
  4. main() — the Branch-C wiring (poke owns stop vs fall-through-to-idle), now
     threading transcript_path.

v2 scope (§0.3): work-owed source = the session's own Task* state replayed from
its transcript. v1 behavior preserved (fresh hold honored; hold-declared owed
still wins). FM-19 catch added: no hold + owed Task* → poke.

Venue: :7999-eligible / local — fully mocked I/O, no server, sub-second.
"""
import datetime
import os
import sys

import pytest
from unittest.mock import patch, MagicMock

# Bootstrap
_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from lupin_cli.claude_code.hooks.stop import (
    main, _run_heartbeat, _emit_genuine_idle, _notify_cap_reached,
    _poke_sentence, _announce_poke, _has_pending_voice,
)
from lupin_cli.claude_code.hooks.lib.heartbeat_decision import (
    DECLARED_OWED_REASON, OUTCOME_POKE, OUTCOME_NOT_OWED,
)
from lupin_cli.notifications.notification_models import NotificationPriority

UTC = datetime.timezone.utc


def _now():
    return datetime.datetime.now( UTC )


def _fresh_reasoned_hold():
    return {
        "session_id"  : "s", "persona": "María 🌸", "held_at": _now().isoformat(),
        "ttl_seconds" : 900, "work_owed": True, "reason": "holding on the gate",
        "awaiting"    : "peer:Rachel",
    }


def _stale_owed_hold():
    stale = ( _now() - datetime.timedelta( seconds=10_000 ) ).isoformat()
    return {
        "session_id"  : "s", "persona": "Tiffany 💍", "held_at": stale,
        "ttl_seconds" : 900, "work_owed": True, "reason": "was holding", "awaiting": "none",
    }


# v2.1: stop.py replays the transcript ONCE → these are replay_task_state outputs
# (the derive helpers owed_items_from_state / is_empty_state run real on them).
_OWED_STATE  = { "1": "in_progress" }    # FM-19 owed Task* state
_EMPTY_STATE = { }                        # no tasks → genuinely idle (empty set)
_DONE_STATE  = { "1": "completed" }       # not owed, but task set NON-empty


# ═════════════════════════════════════════════════════════════════════════════
# _run_heartbeat — v2 adapter shell over the REAL leaves
# ═════════════════════════════════════════════════════════════════════════════

class TestRunHeartbeat:
    """Real decide_heartbeat + evaluate_work_owed; Task* source + emit injected."""

    @pytest.fixture( autouse=True )
    def _isolate( self ):
        """
        Isolate side effects for ALL tests: patch the emit module (no real
        ~/.claude writes), stub persona resolution, default the Task* source
        to 'no owed work / empty set', and intercept the §4 breadcrumb's
        async notify (no network). Tests override as needed.
        """
        with patch( "lupin_cli.claude_code.hooks.stop.heartbeat_events" ) as ev, \
             patch( "lupin_cli.claude_code.hooks.stop.get_voice_persona", return_value=None ) as vp, \
             patch( "lupin_cli.claude_code.hooks.stop.replay_task_state", return_value={ } ) as rt, \
             patch( "lupin_cli.claude_code.hooks.stop.notify_user_async" ) as na, \
             patch( "lupin_cli.claude_code.hooks.stop.build_sender_id_for_cc",
                    return_value="claude.code@lupin.deepily.ai#sid" ):
            # owed_items_from_state + is_empty_state run REAL on the replayed
            # state (single-replay v2.1 path) — tests drive scenarios by setting
            # self.mock_replay.return_value to a { taskId: status } dict.
            # _announce_poke runs REAL (its AsyncNotificationRequest is
            # asserted via self.mock_notify) — only the network call is cut.
            ev.EVENT_IDLE = "idle"
            ev.is_idle_transition.return_value = True
            self.mock_events  = ev
            self.mock_persona = vp
            self.mock_replay  = rt
            self.mock_notify  = na
            yield

    # ── gate / fail-safe ──

    @patch( "lupin_cli.claude_code.hooks.stop.read_hold" )
    @patch( "lupin_cli.claude_code.hooks.stop.load_heartbeat_settings",
            return_value={ "enabled": False, "poke_cap": 3 } )
    def test_disabled_returns_none_no_reads( self, mock_load, mock_read ):
        assert _run_heartbeat( "sid", "/t.jsonl" ) is None
        mock_read.assert_not_called()
        self.mock_replay.assert_not_called()
        self.mock_events.emit_outcome.assert_not_called()

    @patch( "lupin_cli.claude_code.hooks.stop.log_to_stream" )
    @patch( "lupin_cli.claude_code.hooks.stop.read_hold" )
    @patch( "lupin_cli.claude_code.hooks.stop.load_heartbeat_settings",
            side_effect=ValueError( "bad poke_cap" ) )
    def test_malformed_config_fails_safe( self, mock_load, mock_read, mock_log ):
        assert _run_heartbeat( "sid", "/t.jsonl" ) is None
        mock_read.assert_not_called()
        self.mock_events.emit_outcome.assert_not_called()
        assert "heartbeat_settings_invalid" in [ c.kwargs[ "extra" ][ "phase" ] for c in mock_log.call_args_list ]

    # ── poke paths ──

    @patch( "lupin_cli.claude_code.hooks.stop.increment_poke_count" )
    @patch( "lupin_cli.claude_code.hooks.stop.get_poke_count", return_value=0 )
    @patch( "lupin_cli.claude_code.hooks.stop.read_hold", return_value=None )
    @patch( "lupin_cli.claude_code.hooks.stop.load_heartbeat_settings",
            return_value={ "enabled": True, "poke_cap": 3 } )
    def test_v2_fm19_catch_no_hold_owed_task_pokes( self, mock_load, mock_read, mock_count, mock_incr ):
        """FM-19: no hold + owed Task* (in_progress) → poke (the v2 headline catch)."""
        self.mock_replay.return_value = _OWED_STATE
        out = _run_heartbeat( "sid", "/t.jsonl" )
        assert out[ "decision" ] == "block"
        assert out[ "reason" ]                                    # oracle-owed reason (quotes specifics)
        mock_incr.assert_called_once_with( "sid" )
        # emit carries the REAL work_owed=True
        _, kwargs = self.mock_events.emit_outcome.call_args
        assert kwargs[ "work_owed" ] is True
        # §4 breadcrumb rides the poke: ONE low-pri card notify with specifics
        self.mock_notify.assert_called_once()
        crumb = self.mock_notify.call_args[ 0 ][ 0 ]
        assert crumb.message  == "A worker stopped — 1 owed Task item, poked."
        assert crumb.priority == NotificationPriority.LOW

    @patch( "lupin_cli.claude_code.hooks.stop.increment_poke_count" )
    @patch( "lupin_cli.claude_code.hooks.stop.get_poke_count", return_value=0 )
    @patch( "lupin_cli.claude_code.hooks.stop.read_hold" )
    @patch( "lupin_cli.claude_code.hooks.stop.load_heartbeat_settings",
            return_value={ "enabled": True, "poke_cap": 3 } )
    def test_v1_preserved_stale_declared_hold_pokes( self, mock_load, mock_read, mock_count, mock_incr ):
        """v1 preserved: stale self-declared-owed hold pokes even with no owed Task*."""
        mock_read.return_value       = _stale_owed_hold()
        self.mock_replay.return_value = _EMPTY_STATE
        out = _run_heartbeat( "sid", "/t.jsonl" )
        assert out == { "decision": "block", "reason": DECLARED_OWED_REASON }
        mock_incr.assert_called_once_with( "sid" )
        # §4 breadcrumb: declared-owed poke has no Task* count → self-declared text
        self.mock_notify.assert_called_once()
        crumb = self.mock_notify.call_args[ 0 ][ 0 ]
        assert crumb.message == "A worker stopped — work owed (self-declared), poked."

    # ── non-poke paths ──

    @patch( "lupin_cli.claude_code.hooks.stop.increment_poke_count" )
    @patch( "lupin_cli.claude_code.hooks.stop.get_poke_count", return_value=0 )
    @patch( "lupin_cli.claude_code.hooks.stop.read_hold" )
    @patch( "lupin_cli.claude_code.hooks.stop.load_heartbeat_settings",
            return_value={ "enabled": True, "poke_cap": 3 } )
    def test_fresh_hold_honored( self, mock_load, mock_read, mock_count, mock_incr ):
        mock_read.return_value = _fresh_reasoned_hold()
        assert _run_heartbeat( "sid", "/t.jsonl" ) is None
        mock_incr.assert_not_called()
        self.mock_notify.assert_not_called()    # §4 breadcrumb rides ONLY the poke

    @patch( "lupin_cli.claude_code.hooks.stop.get_poke_count", return_value=0 )
    @patch( "lupin_cli.claude_code.hooks.stop.read_hold", return_value=None )
    @patch( "lupin_cli.claude_code.hooks.stop.load_heartbeat_settings",
            return_value={ "enabled": True, "poke_cap": 3 } )
    def test_not_owed_empty_taskset_emits_idle( self, mock_load, mock_read, mock_count ):
        """not_owed + empty Task* set → genuine-idle beacon (transition)."""
        self.mock_replay.return_value = _EMPTY_STATE
        assert _run_heartbeat( "sid", "/t.jsonl" ) is None
        # idle beacon emitted (is_idle_transition True by fixture)
        self.mock_events.is_idle_transition.assert_called_once_with( "sid" )
        idle_calls = [ c for c in self.mock_events.emit_outcome.call_args_list
                       if c.args[ 2 ] == "idle" ]
        assert len( idle_calls ) == 1
        assert idle_calls[ 0 ].kwargs[ "work_owed" ] is False

    @patch( "lupin_cli.claude_code.hooks.stop.get_poke_count", return_value=0 )
    @patch( "lupin_cli.claude_code.hooks.stop.read_hold", return_value=None )
    @patch( "lupin_cli.claude_code.hooks.stop.load_heartbeat_settings",
            return_value={ "enabled": True, "poke_cap": 3 } )
    def test_not_owed_nonempty_taskset_no_idle( self, mock_load, mock_read, mock_count ):
        """not_owed but tasks exist (all completed) → NOT genuine-idle → no beacon."""
        self.mock_replay.return_value = _DONE_STATE        # nothing owed, but task set NON-empty
        assert _run_heartbeat( "sid", "/t.jsonl" ) is None
        self.mock_events.is_idle_transition.assert_not_called()

    @patch( "lupin_cli.claude_code.hooks.stop._notify_cap_reached" )
    @patch( "lupin_cli.claude_code.hooks.stop.increment_poke_count" )
    @patch( "lupin_cli.claude_code.hooks.stop.get_poke_count", return_value=3 )
    @patch( "lupin_cli.claude_code.hooks.stop.read_hold", return_value=None )
    @patch( "lupin_cli.claude_code.hooks.stop.load_heartbeat_settings",
            return_value={ "enabled": True, "poke_cap": 3 } )
    def test_cap_reached_notifies_no_increment( self, mock_load, mock_read, mock_count,
                                                 mock_incr, mock_notify ):
        """Owed Task* but at cap → no poke, cap FYI, no increment."""
        self.mock_replay.return_value = _OWED_STATE
        assert _run_heartbeat( "sid", "/t.jsonl" ) is None
        mock_notify.assert_called_once_with( "sid" )
        mock_incr.assert_not_called()

    # ── emit details ──

    @patch( "lupin_cli.claude_code.hooks.stop.increment_poke_count" )
    @patch( "lupin_cli.claude_code.hooks.stop.get_poke_count", return_value=1 )
    @patch( "lupin_cli.claude_code.hooks.stop.read_hold" )
    @patch( "lupin_cli.claude_code.hooks.stop.load_heartbeat_settings",
            return_value={ "enabled": True, "poke_cap": 3 } )
    def test_emit_persona_and_awaiting_from_hold( self, mock_load, mock_read, mock_count, mock_incr ):
        self.mock_persona.return_value = { "name": "Rachel" }
        mock_read.return_value         = _stale_owed_hold()      # awaiting="none"
        _run_heartbeat( "sid", "/t.jsonl" )
        poke_emits = [ c for c in self.mock_events.emit_outcome.call_args_list
                       if c.args[ 2 ] == OUTCOME_POKE ]
        assert len( poke_emits ) == 1
        assert poke_emits[ 0 ].args[ 1 ] == "Rachel"            # persona resolved
        assert poke_emits[ 0 ].kwargs[ "awaiting" ] == "none"

    @patch( "lupin_cli.claude_code.hooks.stop.log_to_stream" )
    @patch( "lupin_cli.claude_code.hooks.stop.increment_poke_count" )
    @patch( "lupin_cli.claude_code.hooks.stop.get_poke_count", return_value=0 )
    @patch( "lupin_cli.claude_code.hooks.stop.read_hold", return_value=None )
    @patch( "lupin_cli.claude_code.hooks.stop.load_heartbeat_settings",
            return_value={ "enabled": True, "poke_cap": 3 } )
    def test_emit_failure_never_breaks_poke( self, mock_load, mock_read, mock_count, mock_incr, mock_log ):
        """§0 #2: emission failure must NOT break the poke."""
        self.mock_replay.return_value = _OWED_STATE
        self.mock_events.emit_outcome.side_effect = RuntimeError( "disk full" )
        out = _run_heartbeat( "sid", "/t.jsonl" )
        assert out[ "decision" ] == "block"
        assert "heartbeat_emit_error" in [ c.kwargs[ "extra" ][ "phase" ] for c in mock_log.call_args_list ]


# ═════════════════════════════════════════════════════════════════════════════
# _emit_genuine_idle — the §6.2 beacon (edge-trigger gate delegated)
# ═════════════════════════════════════════════════════════════════════════════

class TestEmitGenuineIdle:

    @patch( "lupin_cli.claude_code.hooks.stop.get_poke_count", return_value=0 )
    @patch( "lupin_cli.claude_code.hooks.stop.heartbeat_events" )
    def test_emits_on_transition( self, mock_ev, mock_count ):
        mock_ev.EVENT_IDLE = "idle"
        mock_ev.is_idle_transition.return_value = True
        _emit_genuine_idle( "sid", "Rachel", 3 )
        mock_ev.emit_outcome.assert_called_once()
        args, kwargs = mock_ev.emit_outcome.call_args
        assert args[ 0 ] == "sid" and args[ 1 ] == "Rachel" and args[ 2 ] == "idle"
        assert kwargs[ "work_owed" ] is False and kwargs[ "awaiting" ] is None

    @patch( "lupin_cli.claude_code.hooks.stop.get_poke_count", return_value=0 )
    @patch( "lupin_cli.claude_code.hooks.stop.heartbeat_events" )
    def test_skips_when_already_idle( self, mock_ev, mock_count ):
        mock_ev.is_idle_transition.return_value = False
        _emit_genuine_idle( "sid", "Rachel", 3 )
        mock_ev.emit_outcome.assert_not_called()

    @patch( "lupin_cli.claude_code.hooks.stop.log_to_stream" )
    @patch( "lupin_cli.claude_code.hooks.stop.get_poke_count", return_value=0 )
    @patch( "lupin_cli.claude_code.hooks.stop.heartbeat_events" )
    def test_failure_never_raises( self, mock_ev, mock_count, mock_log ):
        mock_ev.is_idle_transition.side_effect = RuntimeError( "events unreadable" )
        _emit_genuine_idle( "sid", "Rachel", 3 )   # must not raise
        assert "heartbeat_idle_emit_error" in [ c.kwargs[ "extra" ][ "phase" ] for c in mock_log.call_args_list ]


# ═════════════════════════════════════════════════════════════════════════════
# _notify_cap_reached — log-only FYI
# ═════════════════════════════════════════════════════════════════════════════

class TestNotifyCapReached:

    @patch( "lupin_cli.claude_code.hooks.stop.get_poke_count", return_value=3 )
    @patch( "lupin_cli.claude_code.hooks.stop.log_to_stream" )
    def test_logs_session_and_count( self, mock_log, mock_count ):
        _notify_cap_reached( "sid42" )
        assert mock_log.call_count == 1
        extra = mock_log.call_args.kwargs[ "extra" ]
        assert extra[ "phase" ] == "heartbeat_cap_reached"
        assert extra[ "session_id" ] == "sid42"
        assert extra[ "poke_count" ] == 3


# ═════════════════════════════════════════════════════════════════════════════
# main() — Branch-C wiring (threads transcript_path)
# ═════════════════════════════════════════════════════════════════════════════

class TestMainBranchCWiring:

    @patch( "lupin_cli.claude_code.hooks.stop.load_idle_settings" )
    @patch( "lupin_cli.claude_code.hooks.stop._run_heartbeat",
            return_value={ "decision": "block", "reason": "poke!" } )
    @patch( "lupin_cli.claude_code.hooks.stop.reset_stop_block_count" )
    @patch( "lupin_cli.claude_code.hooks.stop.emit_json" )
    @patch( "lupin_cli.claude_code.hooks.stop.drain_and_acknowledge", return_value=[] )
    @patch( "lupin_cli.claude_code.hooks.stop.get_speakerphone", return_value=False )
    @patch( "lupin_cli.claude_code.hooks.stop.resolve_stable_session_id", side_effect=lambda x: x )
    @patch( "lupin_cli.claude_code.hooks.stop.log_payload" )
    @patch( "lupin_cli.claude_code.hooks.stop.read_hook_input" )
    def test_poke_emits_block_skips_idle_passes_transcript( self, mock_read, mock_log, mock_resolve,
                                                            mock_sp, mock_drain, mock_emit,
                                                            mock_reset, mock_hb, mock_idle ):
        mock_read.return_value = {
            "stop_hook_active": False, "session_id": "abc12345",
            "transcript_path": "/home/u/.claude/projects/p/abc.jsonl",
        }
        main()
        mock_emit.assert_called_once_with( { "decision": "block", "reason": "poke!" } )
        mock_hb.assert_called_once_with( "abc12345", "/home/u/.claude/projects/p/abc.jsonl" )
        mock_idle.assert_not_called()

    @patch( "lupin_cli.claude_code.hooks.stop._stop_hook_idle_behavior", return_value="ask" )
    @patch( "lupin_cli.claude_code.hooks.stop._arm_idle_waiter" )
    @patch( "lupin_cli.claude_code.hooks.stop.load_idle_settings",
            return_value={ "enabled": True, "backoff_minutes": [ 5 ] } )
    @patch( "lupin_cli.claude_code.hooks.stop._run_heartbeat", return_value=None )
    @patch( "lupin_cli.claude_code.hooks.stop.reset_stop_block_count" )
    @patch( "lupin_cli.claude_code.hooks.stop.emit_json" )
    @patch( "lupin_cli.claude_code.hooks.stop.drain_and_acknowledge", return_value=[] )
    @patch( "lupin_cli.claude_code.hooks.stop.get_speakerphone", return_value=False )
    @patch( "lupin_cli.claude_code.hooks.stop.resolve_stable_session_id", side_effect=lambda x: x )
    @patch( "lupin_cli.claude_code.hooks.stop.log_payload" )
    @patch( "lupin_cli.claude_code.hooks.stop.read_hook_input" )
    def test_no_poke_falls_through_to_idle( self, mock_read, mock_log, mock_resolve,
                                            mock_sp, mock_drain, mock_emit, mock_reset,
                                            mock_hb, mock_idle, mock_arm, mock_behavior ):
        """Idle behavior 'ask' + no poke + idle enabled → arm the deferred waiter, allow stop."""
        mock_read.return_value = { "stop_hook_active": False, "session_id": "abc12345" }   # no transcript_path key
        main()
        mock_hb.assert_called_once_with( "abc12345", None )   # missing key → None threaded
        mock_arm.assert_called_once()
        mock_emit.assert_called_once_with( {} )


# ═════════════════════════════════════════════════════════════════════════════
# main() — §3 speakerphone poke matrix (the :990 split, 2026-06-09)
#
# Regression-guards the order-of-operations bug where the all-or-nothing
# speakerphone early-exit bailed 75 lines upstream of _run_heartbeat, so NO
# speakerphone session (i.e. every manager) was ever poked. Post-split:
# speakerphone suppresses ONLY the blocking "Anything else?" ask — the poke
# and the breadcrumb run; the loop guard + voice-wins invariants hold.
# ═════════════════════════════════════════════════════════════════════════════

class TestMainSpeakerphonePokeMatrix:

    def _patches( self, *, payload, pending_voice=False, heartbeat_output=None,
                  idle_behavior="idle_announce", persona=None ):
        """One ExitStack-style patch bundle for the speakerphone matrix."""
        from contextlib import ExitStack
        stack = ExitStack()
        p     = lambda target, **kw: stack.enter_context(
                    patch( f"lupin_cli.claude_code.hooks.stop.{target}", **kw ) )
        mocks = {
            "read"          : p( "read_hook_input", return_value=payload ),
            "log_payload"   : p( "log_payload" ),
            "log_stream"    : p( "log_to_stream" ),
            "resolve"       : p( "resolve_stable_session_id", side_effect=lambda x: x ),
            "speakerphone"  : p( "get_speakerphone", return_value=True ),
            "auto_narrate"  : p( "_try_auto_narrate" ),
            "voice_peek"    : p( "_has_pending_voice", return_value=pending_voice ),
            "heartbeat"     : p( "_run_heartbeat", return_value=heartbeat_output ),
            "idle_behavior" : p( "_stop_hook_idle_behavior", return_value=idle_behavior ),
            "persona"       : p( "get_voice_persona", return_value=persona ),
            "announce_idle" : p( "_announce_idle" ),
            "emit"          : p( "emit_json" ),
            "drain"         : p( "drain_and_acknowledge" ),
            "ask"           : p( "_ask_anything_else" ),
            "arm_waiter"    : p( "_arm_idle_waiter" ),
            "notify_sync"   : p( "notify_user_sync" ),
        }
        return stack, mocks

    _POKE = { "decision": "block", "reason": "Do not stop yet — owed Task work." }

    def test_speakerphone_owed_pokes( self ):
        """REGRESSION GUARD (brief §2): speakerphone ON + stopped-with-owed →
        the POKE FIRES — emit the block dict, return (heartbeat owns the stop),
        skip the idle announce. Pre-split this was unreachable."""
        payload = { "stop_hook_active": False, "session_id": "abc12345",
                    "transcript_path": "/t.jsonl" }
        stack, m = self._patches( payload=payload, heartbeat_output=dict( self._POKE ) )
        with stack:
            main()   # returns (no sys.exit) — the poke path mirrors Branch C
            m[ "heartbeat" ].assert_called_once_with( "abc12345", "/t.jsonl" )
            m[ "emit" ].assert_called_once_with( self._POKE )
            m[ "announce_idle" ].assert_not_called()
            # the split is observable in the log stream
            phases = [ c.kwargs[ "extra" ][ "phase" ] for c in m[ "log_stream" ].call_args_list ]
            assert "speakerphone_poke" in phases
            assert "speakerphone_skip" not in phases
            # interactive surfaces stay suppressed
            m[ "drain" ].assert_not_called()
            m[ "notify_sync" ].assert_not_called()
            m[ "ask" ].assert_not_called()

    def test_speakerphone_not_owed_no_poke_idle_announces( self ):
        """speakerphone ON + nothing owed → NO poke; the silent idle announce
        (2026-06-08 behavior) still fires; stop allowed."""
        payload  = { "stop_hook_active": False, "session_id": "abc12345" }
        stack, m = self._patches( payload=payload, heartbeat_output=None,
                                  persona={ "name": "Rachel" } )
        with stack:
            with pytest.raises( SystemExit ):
                main()
            m[ "heartbeat" ].assert_called_once_with( "abc12345", None )
            m[ "announce_idle" ].assert_called_once_with( "abc12345", "Rachel" )
            m[ "emit" ].assert_called_once_with( {} )

    def test_speakerphone_blocking_ask_still_suppressed( self ):
        """speakerphone ON + idle behavior 'ask' → the blocking 'Anything
        else?' path stays FULLY suppressed (the preserved half of the :990
        intent): no waiter, no ask, no sync notify."""
        payload  = { "stop_hook_active": False, "session_id": "abc12345" }
        stack, m = self._patches( payload=payload, heartbeat_output=None,
                                  idle_behavior="ask" )
        with stack:
            with pytest.raises( SystemExit ):
                main()
            m[ "arm_waiter" ].assert_not_called()
            m[ "ask" ].assert_not_called()
            m[ "notify_sync" ].assert_not_called()
            m[ "announce_idle" ].assert_not_called()   # gated to idle_announce only
            m[ "emit" ].assert_called_once_with( {} )

    def test_speakerphone_refire_never_pokes( self ):
        """Loop-guard invariant: stop_hook_active=True (re-fire after a block)
        → NEVER poke, exit silently BEFORE the heartbeat; auto-narrate (own
        per-turn dedup) still ran upstream."""
        payload  = { "stop_hook_active": True, "session_id": "abc12345" }
        stack, m = self._patches( payload=payload, heartbeat_output=dict( self._POKE ) )
        with stack:
            with pytest.raises( SystemExit ):
                main()
            m[ "heartbeat" ].assert_not_called()
            m[ "auto_narrate" ].assert_called_once_with( "abc12345", payload )
            m[ "announce_idle" ].assert_not_called()
            m[ "emit" ].assert_called_once_with( {} )

    def test_speakerphone_pending_voice_suppresses_poke( self ):
        """Branch-C invariant (voice always wins): pending buffered voice →
        NO poke; the buffer is NOT drained (peek only); falls through to the
        idle announce + allow-stop."""
        payload  = { "stop_hook_active": False, "session_id": "abc12345" }
        stack, m = self._patches( payload=payload, pending_voice=True,
                                  heartbeat_output=dict( self._POKE ) )
        with stack:
            with pytest.raises( SystemExit ):
                main()
            m[ "heartbeat" ].assert_not_called()
            m[ "drain" ].assert_not_called()           # peek, never consume
            m[ "emit" ].assert_called_once_with( {} )

    def test_speakerphone_auto_narrate_error_never_blocks_poke( self ):
        """A raising auto-narrate is swallowed (logged) and the poke still
        fires — the safety net is never a dependency of the heartbeat."""
        payload  = { "stop_hook_active": False, "session_id": "abc12345",
                     "transcript_path": "/t.jsonl" }
        stack, m = self._patches( payload=payload, heartbeat_output=dict( self._POKE ) )
        with stack:
            m[ "auto_narrate" ].side_effect = RuntimeError( "transcript unreadable" )
            main()
            phases = [ c.kwargs[ "extra" ][ "phase" ] for c in m[ "log_stream" ].call_args_list ]
            assert "auto_narrate_error" in phases
            m[ "emit" ].assert_called_once_with( self._POKE )

    def test_speakerphone_poke_composition_breadcrumb_fires( self ):
        """§3+§4 composition over the REAL adapter: speakerphone main() with
        the real _run_heartbeat (leaves stubbed to owed-under-cap) emits the
        block AND fires the §4 breadcrumb — poke + breadcrumb in speakerphone,
        end to end."""
        payload = { "stop_hook_active": False, "session_id": "abc12345",
                    "transcript_path": "/t.jsonl" }
        with patch( "lupin_cli.claude_code.hooks.stop.read_hook_input", return_value=payload ), \
             patch( "lupin_cli.claude_code.hooks.stop.log_payload" ), \
             patch( "lupin_cli.claude_code.hooks.stop.log_to_stream" ), \
             patch( "lupin_cli.claude_code.hooks.stop.resolve_stable_session_id", side_effect=lambda x: x ), \
             patch( "lupin_cli.claude_code.hooks.stop.get_speakerphone", return_value=True ), \
             patch( "lupin_cli.claude_code.hooks.stop._try_auto_narrate" ), \
             patch( "lupin_cli.claude_code.hooks.stop._has_pending_voice", return_value=False ), \
             patch( "lupin_cli.claude_code.hooks.stop.load_heartbeat_settings",
                    return_value={ "enabled": True, "poke_cap": 3 } ), \
             patch( "lupin_cli.claude_code.hooks.stop.read_hold", return_value=None ), \
             patch( "lupin_cli.claude_code.hooks.stop.get_poke_count", return_value=0 ), \
             patch( "lupin_cli.claude_code.hooks.stop.increment_poke_count" ), \
             patch( "lupin_cli.claude_code.hooks.stop.replay_task_state",
                    return_value={ "1": "in_progress", "2": "pending" } ), \
             patch( "lupin_cli.claude_code.hooks.stop.heartbeat_events" ), \
             patch( "lupin_cli.claude_code.hooks.stop.get_voice_persona",
                    return_value={ "name": "Tiberius" } ), \
             patch( "lupin_cli.claude_code.hooks.stop.build_sender_id_for_cc",
                    return_value="claude.code@lupin.deepily.ai#abc12345" ), \
             patch( "lupin_cli.claude_code.hooks.stop.notify_user_async" ) as mock_async, \
             patch( "lupin_cli.claude_code.hooks.stop.emit_json" ) as mock_emit:
            main()
            emitted = mock_emit.call_args[ 0 ][ 0 ]
            assert emitted[ "decision" ] == "block"             # the poke owns the stop
            mock_async.assert_called_once()                     # the breadcrumb fired
            crumb = mock_async.call_args[ 0 ][ 0 ]
            assert crumb.message  == "Tiberius stopped — 2 owed Task items, poked."
            assert crumb.priority == NotificationPriority.LOW   # silent card bubble — no double-speak


# ═════════════════════════════════════════════════════════════════════════════
# _poke_sentence / _announce_poke — the §4 breadcrumb leaf + shell
# ═════════════════════════════════════════════════════════════════════════════

class TestPokeSentence:

    def test_singular_count( self ):
        assert _poke_sentence( "Krishna", 1 ) == "Krishna stopped — 1 owed Task item, poked."

    def test_plural_count( self ):
        assert _poke_sentence( "Krishna", 2 ) == "Krishna stopped — 2 owed Task items, poked."

    def test_zero_count_self_declared( self ):
        """A hold-declared poke has no oracle specifics to count."""
        assert _poke_sentence( "Krishna", 0 ) == "Krishna stopped — work owed (self-declared), poked."

    def test_missing_persona( self ):
        assert _poke_sentence( None, 3 ) == "A worker stopped — 3 owed Task items, poked."


class TestAnnouncePoke:

    @patch( "lupin_cli.claude_code.hooks.stop.build_sender_id_for_cc",
            return_value="claude.code@lupin.deepily.ai#abc12345" )
    @patch( "lupin_cli.claude_code.hooks.stop.notify_user_async" )
    def test_posts_low_priority_persona_notify( self, mock_notify, mock_sender ):
        _announce_poke( "abc12345", "Rio", 2 )
        mock_notify.assert_called_once()
        request = mock_notify.call_args[ 0 ][ 0 ]
        assert request.message   == "Rio stopped — 2 owed Task items, poked."
        assert request.priority  == NotificationPriority.LOW
        assert request.sender_id == "claude.code@lupin.deepily.ai#abc12345"

    @patch( "lupin_cli.claude_code.hooks.stop.log_to_stream" )
    @patch( "lupin_cli.claude_code.hooks.stop.build_sender_id_for_cc", return_value="x" )
    @patch( "lupin_cli.claude_code.hooks.stop.notify_user_async",
            side_effect=RuntimeError( "server down" ) )
    def test_failsafe_swallows_errors( self, mock_notify, mock_sender, mock_log ):
        # Must NOT raise — the breadcrumb can never block (or break) the poke.
        _announce_poke( "abc12345", "Rio", 2 )
        mock_log.assert_called_once()
        assert mock_log.call_args[ 1 ][ "extra" ][ "phase" ] == "poke_announce_error"


# ═════════════════════════════════════════════════════════════════════════════
# _has_pending_voice — the Branch-C voice-wins peek (non-destructive)
# ═════════════════════════════════════════════════════════════════════════════

class TestHasPendingVoice:

    def test_true_when_buffer_exists( self, tmp_path ):
        buf = tmp_path / "cc-buffer-abc12345.jsonl"
        buf.write_text( '{"message": "hold on"}\n' )
        with patch( "lupin_cli.claude_code.hooks.stop.get_buffer_path", return_value=buf ):
            assert _has_pending_voice( "abc12345" ) is True
        assert buf.exists(), "peek must NOT consume the buffer"

    def test_false_when_no_buffer( self, tmp_path ):
        with patch( "lupin_cli.claude_code.hooks.stop.get_buffer_path",
                    return_value=tmp_path / "absent.jsonl" ):
            assert _has_pending_voice( "abc12345" ) is False

    def test_false_on_error_never_raises( self ):
        with patch( "lupin_cli.claude_code.hooks.stop.get_buffer_path",
                    side_effect=RuntimeError( "bad session dir" ) ):
            assert _has_pending_voice( "abc12345" ) is False
