#!/usr/bin/env python3
"""
Unit + integration tests for the Stop-hook Heartbeat Branch-C adapter.

Two layers:
  1. _run_heartbeat / _notify_cap_reached — the side-effecting adapter shell,
     driven against the REAL pure leaf modules (heartbeat_hold +
     heartbeat_decision) so the seam composition is validated, not mocked away.
     Mirrors Tiffany's leaf-only contract test (test_heartbeat_v1_composition.py)
     but adds the stop.py side effects (settings gate, increment, cap FYI).
  2. main() — the Branch-C wiring: a poke owns the stop (emit block, skip idle);
     a non-poke falls through to the existing idle path UNCHANGED.

v1 scope: hold-declared work-owed only (oracle_verdict=None). Conservative —
no hold → no poke. The live oracle (v2) is gated on María §C.3 Q4.

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
    main, _run_heartbeat, _notify_cap_reached,
)
from lupin_cli.claude_code.hooks.lib.heartbeat_decision import (
    DECLARED_OWED_REASON, OUTCOME_POKE, OUTCOME_NOT_OWED,
)

UTC = datetime.timezone.utc


def _now():
    return datetime.datetime.now( UTC )


def _fresh_reasoned_hold():
    """A fresh, reasoned, work-owed hold → honored (no poke)."""
    return {
        "session_id"  : "s",
        "persona"     : "María 🌸",
        "held_at"     : _now().isoformat(),
        "ttl_seconds" : 900,
        "work_owed"   : True,
        "reason"      : "holding on the Tiberius gate",
        "awaiting"    : "peer:Rachel",
    }


def _stale_owed_hold():
    """A STALE self-declared work-owed hold → pokeable (v1's catch)."""
    stale = ( _now() - datetime.timedelta( seconds=10_000 ) ).isoformat()
    return {
        "session_id"  : "s",
        "persona"     : "Tiffany 💍",
        "held_at"     : stale,
        "ttl_seconds" : 900,
        "work_owed"   : True,
        "reason"      : "was holding on Rachel",
        "awaiting"    : "none",
    }


# ═════════════════════════════════════════════════════════════════════════════
# _run_heartbeat — adapter shell over the REAL leaf modules
# ═════════════════════════════════════════════════════════════════════════════

class TestRunHeartbeat:
    """Adapter side-effect shell; real decide_heartbeat composition."""

    @pytest.fixture( autouse=True )
    def _isolate_emit( self ):
        """
        Isolate the fire-and-forget EMIT-NOW side effect for ALL tests in this
        class: patch the heartbeat_events module (so emit_outcome never writes a
        real ~/.claude/heartbeat-events/ file) and stub persona resolution to
        None. Individual tests set self.mock_get_persona.return_value or inspect
        self.mock_events.emit_outcome.call_args as needed.
        """
        with patch( "lupin_cli.claude_code.hooks.stop.heartbeat_events" ) as ev, \
             patch( "lupin_cli.claude_code.hooks.stop.get_voice_persona", return_value=None ) as vp:
            self.mock_events      = ev
            self.mock_get_persona = vp
            yield

    @patch( "lupin_cli.claude_code.hooks.stop.read_hold" )
    @patch( "lupin_cli.claude_code.hooks.stop.load_heartbeat_settings",
            return_value={ "enabled": False, "poke_cap": 3 } )
    def test_disabled_returns_none_no_leaf_reads( self, mock_load, mock_read ):
        """Gate off → None, never read the hold, never emit."""
        assert _run_heartbeat( "sid" ) is None
        mock_read.assert_not_called()
        self.mock_events.emit_outcome.assert_not_called()

    @patch( "lupin_cli.claude_code.hooks.stop.log_to_stream" )
    @patch( "lupin_cli.claude_code.hooks.stop.read_hold" )
    @patch( "lupin_cli.claude_code.hooks.stop.load_heartbeat_settings",
            side_effect=ValueError( "heartbeat.poke_cap must be > 0, got 0" ) )
    def test_malformed_config_fails_safe( self, mock_load, mock_read, mock_log ):
        """Malformed config → fail SAFE (None) + logged; never poke, never emit."""
        assert _run_heartbeat( "sid" ) is None
        mock_read.assert_not_called()
        self.mock_events.emit_outcome.assert_not_called()
        phases = [ c.kwargs[ "extra" ][ "phase" ] for c in mock_log.call_args_list ]
        assert "heartbeat_settings_invalid" in phases

    @patch( "lupin_cli.claude_code.hooks.stop._notify_cap_reached" )
    @patch( "lupin_cli.claude_code.hooks.stop.increment_poke_count" )
    @patch( "lupin_cli.claude_code.hooks.stop.get_poke_count", return_value=0 )
    @patch( "lupin_cli.claude_code.hooks.stop.read_hold" )
    @patch( "lupin_cli.claude_code.hooks.stop.load_heartbeat_settings",
            return_value={ "enabled": True, "poke_cap": 3 } )
    def test_poke_returns_block_and_increments( self, mock_load, mock_read, mock_count,
                                                  mock_incr, mock_notify ):
        """Stale owed hold, under cap → block dict + increment, no cap FYI."""
        mock_read.return_value = _stale_owed_hold()
        out = _run_heartbeat( "sid" )
        assert out == { "decision": "block", "reason": DECLARED_OWED_REASON }
        mock_incr.assert_called_once_with( "sid" )
        mock_notify.assert_not_called()

    @patch( "lupin_cli.claude_code.hooks.stop._notify_cap_reached" )
    @patch( "lupin_cli.claude_code.hooks.stop.increment_poke_count" )
    @patch( "lupin_cli.claude_code.hooks.stop.get_poke_count", return_value=0 )
    @patch( "lupin_cli.claude_code.hooks.stop.read_hold" )
    @patch( "lupin_cli.claude_code.hooks.stop.load_heartbeat_settings",
            return_value={ "enabled": True, "poke_cap": 3 } )
    def test_fresh_hold_honored_no_poke( self, mock_load, mock_read, mock_count,
                                          mock_incr, mock_notify ):
        """Fresh reasoned hold → honored → None, no side effects."""
        mock_read.return_value = _fresh_reasoned_hold()
        assert _run_heartbeat( "sid" ) is None
        mock_incr.assert_not_called()
        mock_notify.assert_not_called()

    @patch( "lupin_cli.claude_code.hooks.stop._notify_cap_reached" )
    @patch( "lupin_cli.claude_code.hooks.stop.increment_poke_count" )
    @patch( "lupin_cli.claude_code.hooks.stop.get_poke_count", return_value=0 )
    @patch( "lupin_cli.claude_code.hooks.stop.read_hold", return_value=None )
    @patch( "lupin_cli.claude_code.hooks.stop.load_heartbeat_settings",
            return_value={ "enabled": True, "poke_cap": 3 } )
    def test_no_hold_not_owed_no_poke( self, mock_load, mock_read, mock_count,
                                        mock_incr, mock_notify ):
        """No hold + oracle None → not_owed → None (conservative v1)."""
        assert _run_heartbeat( "sid" ) is None
        mock_incr.assert_not_called()
        mock_notify.assert_not_called()

    @patch( "lupin_cli.claude_code.hooks.stop._notify_cap_reached" )
    @patch( "lupin_cli.claude_code.hooks.stop.increment_poke_count" )
    @patch( "lupin_cli.claude_code.hooks.stop.get_poke_count", return_value=3 )
    @patch( "lupin_cli.claude_code.hooks.stop.read_hold" )
    @patch( "lupin_cli.claude_code.hooks.stop.load_heartbeat_settings",
            return_value={ "enabled": True, "poke_cap": 3 } )
    def test_cap_reached_fires_notify_no_increment( self, mock_load, mock_read, mock_count,
                                                      mock_incr, mock_notify ):
        """Owed but at cap → None (allow stop) + cap FYI, no increment."""
        mock_read.return_value = _stale_owed_hold()
        assert _run_heartbeat( "sid" ) is None
        mock_notify.assert_called_once_with( "sid" )
        mock_incr.assert_not_called()

    # ── EMIT NOW, CONSUME LATER — the single fire-and-forget call-site ────────

    @patch( "lupin_cli.claude_code.hooks.stop.increment_poke_count" )
    @patch( "lupin_cli.claude_code.hooks.stop.get_poke_count", return_value=1 )
    @patch( "lupin_cli.claude_code.hooks.stop.read_hold" )
    @patch( "lupin_cli.claude_code.hooks.stop.load_heartbeat_settings",
            return_value={ "enabled": True, "poke_cap": 3 } )
    def test_emit_called_on_poke_with_contract_args( self, mock_load, mock_read, mock_count, mock_incr ):
        """On poke: emit_outcome gets resolved persona, POST-increment count, cap, reason."""
        self.mock_get_persona.return_value = { "name": "Rachel" }
        mock_read.return_value             = _stale_owed_hold()   # awaiting="none"
        out = _run_heartbeat( "sid" )
        assert out == { "decision": "block", "reason": DECLARED_OWED_REASON }
        self.mock_events.emit_outcome.assert_called_once()
        args, kwargs = self.mock_events.emit_outcome.call_args
        assert args[ 0 ] == "sid"                 # session_id
        assert args[ 1 ] == "Rachel"              # persona resolved from the bridge
        assert args[ 2 ] == OUTCOME_POKE          # outcome
        assert args[ 3 ] == 1                     # get_poke_count read at emit (post-increment)
        assert args[ 4 ] == 3                     # cap
        assert kwargs[ "work_owed" ] is None      # v1
        assert kwargs[ "awaiting" ] == "none"     # from the hold
        assert kwargs[ "reason" ]   == DECLARED_OWED_REASON

    @patch( "lupin_cli.claude_code.hooks.stop.get_poke_count", return_value=0 )
    @patch( "lupin_cli.claude_code.hooks.stop.read_hold", return_value=None )
    @patch( "lupin_cli.claude_code.hooks.stop.load_heartbeat_settings",
            return_value={ "enabled": True, "poke_cap": 3 } )
    def test_emit_called_unconditionally_on_not_owed( self, mock_load, mock_read, mock_count ):
        """Unconditional call: emit fires even on not_owed (the module self-filters the write).
        With no hold + unresolved persona → persona None, awaiting None, reason None."""
        assert _run_heartbeat( "sid" ) is None
        self.mock_events.emit_outcome.assert_called_once()
        args, kwargs = self.mock_events.emit_outcome.call_args
        assert args[ 1 ] is None                  # persona unresolved → None
        assert args[ 2 ] == OUTCOME_NOT_OWED
        assert kwargs[ "awaiting" ] is None       # no hold
        assert kwargs[ "reason" ]   is None       # {"continue":True} → no reason

    @patch( "lupin_cli.claude_code.hooks.stop.log_to_stream" )
    @patch( "lupin_cli.claude_code.hooks.stop.increment_poke_count" )
    @patch( "lupin_cli.claude_code.hooks.stop.get_poke_count", return_value=1 )
    @patch( "lupin_cli.claude_code.hooks.stop.read_hold" )
    @patch( "lupin_cli.claude_code.hooks.stop.load_heartbeat_settings",
            return_value={ "enabled": True, "poke_cap": 3 } )
    def test_emit_failure_never_breaks_poke( self, mock_load, mock_read, mock_count, mock_incr, mock_log ):
        """§0 #2 invariant: an emission failure must NOT break the poke."""
        mock_read.return_value                      = _stale_owed_hold()
        self.mock_events.emit_outcome.side_effect   = RuntimeError( "disk full" )
        out = _run_heartbeat( "sid" )
        assert out == { "decision": "block", "reason": DECLARED_OWED_REASON }   # poke STILL proceeds
        phases = [ c.kwargs[ "extra" ][ "phase" ] for c in mock_log.call_args_list ]
        assert "heartbeat_emit_error" in phases


# ═════════════════════════════════════════════════════════════════════════════
# _notify_cap_reached — log-only FYI (v1)
# ═════════════════════════════════════════════════════════════════════════════

class TestNotifyCapReached:

    @patch( "lupin_cli.claude_code.hooks.stop.get_poke_count", return_value=3 )
    @patch( "lupin_cli.claude_code.hooks.stop.log_to_stream" )
    def test_logs_session_and_count( self, mock_log, mock_count ):
        _notify_cap_reached( "sid42" )
        assert mock_log.call_count == 1
        extra = mock_log.call_args.kwargs[ "extra" ]
        assert extra[ "phase" ]      == "heartbeat_cap_reached"
        assert extra[ "session_id" ] == "sid42"
        assert extra[ "poke_count" ] == 3


# ═════════════════════════════════════════════════════════════════════════════
# main() — Branch-C wiring
# ═════════════════════════════════════════════════════════════════════════════

class TestMainBranchCWiring:
    """A poke owns the stop (emit block, skip idle); non-poke → idle path."""

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
    def test_poke_emits_block_and_skips_idle( self, mock_read, mock_log, mock_resolve,
                                               mock_sp, mock_drain, mock_emit,
                                               mock_reset, mock_hb, mock_idle ):
        mock_read.return_value = { "stop_hook_active": False, "session_id": "abc12345" }
        main()
        mock_emit.assert_called_once_with( { "decision": "block", "reason": "poke!" } )
        mock_hb.assert_called_once_with( "abc12345" )
        mock_idle.assert_not_called()   # idle path skipped — poke owns the stop

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
                                            mock_hb, mock_idle, mock_arm ):
        mock_read.return_value = { "stop_hook_active": False, "session_id": "abc12345" }
        main()
        mock_hb.assert_called_once_with( "abc12345" )
        mock_arm.assert_called_once()           # idle waiter armed → fell through
        mock_emit.assert_called_once_with( {} ) # allow stop after arming
