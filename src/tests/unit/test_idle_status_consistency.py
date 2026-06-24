#!/usr/bin/env python3
"""
Unit tests — idle-status desync fix (bug aa403e03).

The Stop hook and the Notification idle-beacon used to disagree on whether a
session is idle: the Stop hook ran the full HOLD-AWARE oracle (decide_heartbeat
honors the .heartbeat-hold), while the beacon read _owed_count_from_store ALONE
(raw store count, hold-blind). A held / blocked / hold-suppressed store row read
0-owed on the Stop path but N-owed on the beacon ("Momentarily idle." vs "Idle,
but N owed" within ~60s).

The fix routes BOTH consumers through the single shared _resolve_owed_state
verdict. These tests pin:
  - _resolve_owed_state's owed := { POKE, CAP_REACHED } mapping (hold-aware);
  - the desync-killer: a held in_progress/owed store row → owed=False on the
    shared verdict (so both consumers read idle);
  - the CAP_REACHED case (capped + owed → owed=True, both consumers owed);
  - the owed_unknown case (store unreachable → both consumers neutral);
  - the disabled short-circuit does NO hold read / transcript replay (the Stop
    "no reads when disabled" contract);
  - _idle_sentence's owed-aware phrasing matches the beacon's, so the two agree.

Venue: :7999-eligible / local — fully mocked I/O, sub-second.
"""
import datetime
import os
import sys

import pytest
from unittest.mock import patch

_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from lupin_cli.claude_code.hooks.stop import (
    _resolve_owed_state, _idle_sentence,
)
from lupin_cli.claude_code.hooks.notification import beacon_idle_message
from lupin_cli.claude_code.hooks.lib.heartbeat_decision import (
    OUTCOME_POKE, OUTCOME_CAP_REACHED, OUTCOME_HONORED, OUTCOME_NOT_OWED,
)

UTC = datetime.timezone.utc


def _now():
    return datetime.datetime.now( UTC )


def _fresh_reasoned_hold():
    """A fresh, honored hold (defends quiescence — decide_heartbeat → HONORED)."""
    return {
        "session_id"  : "s", "persona": "María 🌸", "held_at": _now().isoformat(),
        "ttl_seconds" : 900, "work_owed": True, "reason": "holding on the gate",
        "awaiting"    : "peer:Rachel",
    }


_SETTINGS = {
    "enabled"                         : True,
    "poke_cap"                        : 3,
    "owed_source_from_store"          : True,     # owed via the store-count seam
    "verification_threshold_seconds"  : 600,
    "count_inbound_questions_as_owed" : False,
}


class _Base:
    """Isolate _resolve_owed_state's heavy IO; per-test drives hold / store-count / poke_count."""

    @pytest.fixture( autouse=True )
    def _isolate( self ):
        with patch( "lupin_cli.claude_code.hooks.stop.replay_task_state", return_value={ } ), \
             patch( "lupin_cli.claude_code.hooks.stop._gather_outstanding_delegations", return_value=[ ] ), \
             patch( "lupin_cli.claude_code.hooks.stop._gather_unanswered_inbound_questions",
                    return_value={ "owed": [ ], "stale": [ ] } ), \
             patch( "lupin_cli.claude_code.hooks.stop._backlog_count_from_store", return_value=( 0, False ) ), \
             patch( "lupin_cli.claude_code.hooks.stop.get_session_metadata", return_value={ "role": None } ), \
             patch( "lupin_cli.claude_code.hooks.stop._heartbeat_goal_line", return_value="" ):
            yield


class TestOwedMapping( _Base ):
    """owed := outcome in { POKE, CAP_REACHED }; HONORED / NOT_OWED ⇒ not owed."""

    @pytest.mark.parametrize( "outcome,expected_owed", [
        ( OUTCOME_POKE,        True ),
        ( OUTCOME_CAP_REACHED, True ),
        ( OUTCOME_HONORED,     False ),
        ( OUTCOME_NOT_OWED,    False ),
    ] )
    def test_owed_flag_tracks_outcome( self, outcome, expected_owed ):
        with patch( "lupin_cli.claude_code.hooks.stop.load_heartbeat_settings", return_value=dict( _SETTINGS ) ), \
             patch( "lupin_cli.claude_code.hooks.stop.read_hold_resilient", return_value=None ), \
             patch( "lupin_cli.claude_code.hooks.stop.get_poke_count", return_value=0 ), \
             patch( "lupin_cli.claude_code.hooks.stop._owed_count_from_store", return_value=( 1, True ) ), \
             patch( "lupin_cli.claude_code.hooks.stop.decide_heartbeat",
                    return_value={ "outcome": outcome, "hook_output": { }, "should_increment": False, "should_notify_cap": False } ):
            state = _resolve_owed_state( "sid", "/t.jsonl", None )
        assert state[ "owed" ] is expected_owed
        assert state[ "outcome" ] == outcome


class TestHoldAwareDesyncKiller( _Base ):
    """REAL decide_heartbeat: the hold must suppress owed even with an owed store row."""

    def test_held_owed_store_row_reads_not_owed( self ):
        # The exact desync repro: a FRESH honored hold + an owed (in_progress) store
        # row. Pre-fix the beacon read 1-owed; the Stop hook (hold-aware) read idle.
        # Now the shared verdict resolves HONORED ⇒ owed=False ⇒ BOTH read idle.
        with patch( "lupin_cli.claude_code.hooks.stop.load_heartbeat_settings", return_value=dict( _SETTINGS ) ), \
             patch( "lupin_cli.claude_code.hooks.stop.read_hold_resilient", return_value=_fresh_reasoned_hold() ), \
             patch( "lupin_cli.claude_code.hooks.stop.get_poke_count", return_value=0 ), \
             patch( "lupin_cli.claude_code.hooks.stop._owed_count_from_store", return_value=( 1, True ) ):
            state = _resolve_owed_state( "sid", "/t.jsonl", None )
        assert state[ "outcome" ] == OUTCOME_HONORED
        assert state[ "owed" ] is False
        assert state[ "owed_unknown" ] is False

    def test_no_hold_owed_store_row_reads_owed( self ):
        # No hold + owed store row + under cap → POKE → owed True (both consumers owed).
        with patch( "lupin_cli.claude_code.hooks.stop.load_heartbeat_settings", return_value=dict( _SETTINGS ) ), \
             patch( "lupin_cli.claude_code.hooks.stop.read_hold_resilient", return_value=None ), \
             patch( "lupin_cli.claude_code.hooks.stop.get_poke_count", return_value=0 ), \
             patch( "lupin_cli.claude_code.hooks.stop._owed_count_from_store", return_value=( 2, True ) ):
            state = _resolve_owed_state( "sid", "/t.jsonl", None )
        assert state[ "outcome" ] == OUTCOME_POKE
        assert state[ "owed" ] is True
        assert state[ "total_owed" ] == 2

    def test_cap_reached_owed_reads_owed( self ):
        # Owed store row but poke_count >= cap → CAP_REACHED → still owed (the cap
        # halts the POKING, not the owed-ness). Both consumers must read "N owed".
        with patch( "lupin_cli.claude_code.hooks.stop.load_heartbeat_settings", return_value=dict( _SETTINGS ) ), \
             patch( "lupin_cli.claude_code.hooks.stop.read_hold_resilient", return_value=None ), \
             patch( "lupin_cli.claude_code.hooks.stop.get_poke_count", return_value=3 ), \
             patch( "lupin_cli.claude_code.hooks.stop._owed_count_from_store", return_value=( 1, True ) ):
            state = _resolve_owed_state( "sid", "/t.jsonl", None )
        assert state[ "outcome" ] == OUTCOME_CAP_REACHED
        assert state[ "owed" ] is True
        assert state[ "total_owed" ] == 1


class TestOwedUnknown( _Base ):
    """Store-owed source ON but unreachable → owed_unknown (UNKNOWN ≠ idle)."""

    def test_store_unreachable_sets_owed_unknown( self ):
        with patch( "lupin_cli.claude_code.hooks.stop.load_heartbeat_settings", return_value=dict( _SETTINGS ) ), \
             patch( "lupin_cli.claude_code.hooks.stop.read_hold_resilient", return_value=None ), \
             patch( "lupin_cli.claude_code.hooks.stop.get_poke_count", return_value=0 ), \
             patch( "lupin_cli.claude_code.hooks.stop._owed_count_from_store", return_value=( 0, False ) ):
            state = _resolve_owed_state( "sid", "/t.jsonl", None )
        assert state[ "owed_unknown" ] is True
        # owed itself is False (no determinate owed signal) — the consumers gate on
        # owed_unknown FIRST and emit the neutral message, never a false "N owed".
        assert state[ "owed" ] is False


class TestDisabledNoReads:
    """Disabled heartbeat short-circuits BEFORE any hold read / transcript replay."""

    def test_disabled_does_no_reads( self ):
        with patch( "lupin_cli.claude_code.hooks.stop.load_heartbeat_settings",
                    return_value={ "enabled": False, "poke_cap": 3 } ), \
             patch( "lupin_cli.claude_code.hooks.stop.read_hold_resilient" ) as mock_hold, \
             patch( "lupin_cli.claude_code.hooks.stop.replay_task_state" ) as mock_replay:
            state = _resolve_owed_state( "sid", "/t.jsonl", None )
        assert state[ "enabled" ] is False
        assert state[ "owed" ] is False and state[ "owed_unknown" ] is False
        mock_hold.assert_not_called()
        mock_replay.assert_not_called()

    def test_malformed_config_fails_safe_no_reads( self ):
        with patch( "lupin_cli.claude_code.hooks.stop.load_heartbeat_settings",
                    side_effect=ValueError( "bad poke_cap" ) ), \
             patch( "lupin_cli.claude_code.hooks.stop.read_hold_resilient" ) as mock_hold:
            state = _resolve_owed_state( "sid", "/t.jsonl", None )
        assert state[ "config_error" ] is True and state[ "enabled" ] is False
        assert state[ "owed" ] is False
        mock_hold.assert_not_called()


class TestIdleSentenceOwedAware:
    """The Stop _idle_sentence phrasing — owed-aware, matches the beacon wording."""

    def test_owed_unknown_first( self ):
        assert _idle_sentence( "Rio", owed_unknown=True, owed=True, total_owed=5 ) == "Owed status unknown."

    def test_owed_with_count( self ):
        assert _idle_sentence( "Rio", owed=True, total_owed=1 ) == "Idle, but 1 item owed."
        assert _idle_sentence( "Rio", owed=True, total_owed=3 ) == "Idle, but 3 items owed."

    def test_owed_referent_less( self ):
        assert _idle_sentence( "Rio", owed=True, total_owed=0 ) == "Idle, but work owed."

    def test_not_owed_is_momentarily_idle( self ):
        assert _idle_sentence( "Rio", owed=False ) == "Momentarily idle."


class TestCrossHookConsistency:
    """
    Given the SAME shared verdict, the Stop idle-announce sentence and the
    Notification beacon message must AGREE on owed-vs-idle (the whole point of the
    fix). We call the REAL beacon function (notification.beacon_idle_message) — NOT
    a hand-mirrored copy — so this tests the actual production code and can't drift
    from it (Sam re-loop c; the same anti-duplication lesson as this very bug).
    """

    @pytest.mark.parametrize( "owed_unknown,owed,total_owed", [
        ( False, False, 0 ),    # genuinely idle
        ( False, True,  3 ),    # owed with referents
        ( False, True,  1 ),    # owed, single referent (singular wording)
        ( False, True,  0 ),    # owed, referent-less
        ( True,  False, 0 ),    # unknown
    ] )
    def test_consumers_never_contradict( self, owed_unknown, owed, total_owed ):
        stop_msg   = _idle_sentence( "Rio", owed_unknown=owed_unknown, owed=owed, total_owed=total_owed )
        beacon_msg = beacon_idle_message( owed=owed, owed_unknown=owed_unknown,
                                          total_owed=total_owed, idle_msg="Claude is waiting for input" )
        # "owed" claim must be consistent across both surfaces
        stop_claims_owed   = stop_msg.startswith( "Idle, but" )
        beacon_claims_owed = beacon_msg.startswith( "Idle, but" )
        assert stop_claims_owed == beacon_claims_owed, ( stop_msg, beacon_msg )
        # and when both claim owed with a count, the COUNT matches
        if owed and total_owed > 0:
            assert f"{total_owed} item" in stop_msg and f"{total_owed} item" in beacon_msg
