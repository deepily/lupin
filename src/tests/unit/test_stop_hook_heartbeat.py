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
)
from lupin_cli.claude_code.hooks.lib.heartbeat_decision import (
    DECLARED_OWED_REASON, OUTCOME_POKE, OUTCOME_NOT_OWED,
)

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
        ~/.claude writes), stub persona resolution, and default the Task*
        source to 'no owed work / empty set'. Tests override as needed.
        """
        with patch( "lupin_cli.claude_code.hooks.stop.heartbeat_events" ) as ev, \
             patch( "lupin_cli.claude_code.hooks.stop.get_voice_persona", return_value=None ) as vp, \
             patch( "lupin_cli.claude_code.hooks.stop.replay_task_state", return_value={ } ) as rt:
            # owed_items_from_state + is_empty_state run REAL on the replayed
            # state (single-replay v2.1 path) — tests drive scenarios by setting
            # self.mock_replay.return_value to a { taskId: status } dict.
            ev.EVENT_IDLE = "idle"
            ev.is_idle_transition.return_value = True
            self.mock_events  = ev
            self.mock_persona = vp
            self.mock_replay  = rt
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
