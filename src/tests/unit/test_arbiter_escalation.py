#!/usr/bin/env python3
"""
Unit tests for v2.2 lane B3 — the D3 escalation detectors:
decision-needed (reserved `fleet-decision-needed` topic tail → escalate to Rick)
and whole-fleet-stall (no-progress-for-X catch-all, keyed on PROGRESS not
manager liveness). Deadlock + manager-down detectors are covered elsewhere
(_escalate_deadlocks / test_arbiter_manager_tap).
"""
import datetime
import os
import sys

import pytest

# Bootstrap
_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from cosa.agents.heartbeat_arbiter.arbiter_job import ArbiterConsumerJob, DECISION_TOPIC


NOW = datetime.datetime( 2026, 6, 6, 22, 0, 0, tzinfo=datetime.timezone.utc )


class _GW:
    def __init__( self, read_entries=None, read_raises=False ):
        self.sent, self.posts, self.read_calls = [ ], [ ], [ ]
        self._read, self._raises = read_entries or [ ], read_raises
    def who( self, retention_hours=24 ): return [ ]
    def send_to( self, r, b, metadata=None ): self.sent.append( ( r, b ) )
    def post( self, t, b ): self.posts.append( ( t, b ) )
    def read( self, topic, since=None, limit=50 ):
        self.read_calls.append( ( topic, since ) )
        if self._raises:
            raise RuntimeError( "commons read failed" )
        return list( self._read )


def _job( gw, *, stall_window=1800, notify=None ):
    return ArbiterConsumerJob(
        commons                    = gw,
        poll_seconds               = 5,
        manager_recipient          = "DeclaredMgr",
        fleet_stall_window_seconds = stall_window,
        notify_fn                  = notify or ( lambda *a, **k: None ),
    )


def _stuck( sid, alive=True ):
    # alive defaults True — the 2b-1 calibration gates the stall trigger on a LIVE
    # owed-work session; pass alive=False to model the dead/offline roster the old
    # trigger mis-fired on (the Part-3/Part-7 false-fire).
    return { "session_id": sid, "persona": sid, "state": "stuck", "stuck": True,
             "holding_on": "none", "alive": alive }

def _idle( sid, alive=True ):
    return { "session_id": sid, "persona": sid, "state": "idle", "stuck": False,
             "holding_on": "none", "alive": alive }


# ── decision-needed (D3) ───────────────────────────────────────────────────────

class TestDecisionNeeded:
    def test_first_poll_baselines_no_backlog_escalation( self ):
        gw, escal = _GW( read_entries=[ { "ts": "t0", "body": "old" } ] ), [ ]
        job = _job( gw, notify=lambda m, *a, **k: escal.append( m ) )
        fired = job._check_decision_needed( NOW )
        assert fired == 0 and escal == [ ]                 # backlog ignored
        assert job._decision_since == NOW.isoformat()
        assert gw.read_calls == [ ]                          # baseline branch: no read

    def test_new_decision_escalates_to_rick( self ):
        gw = _GW( read_entries=[ { "ts": "t5", "body": "JWT vs OAuth — scope call?", "persona_name": "María" } ] )
        escal = [ ]
        job = _job( gw, notify=lambda m, *a, **k: escal.append( m ) )
        job._decision_since = "t1"                           # already baselined
        fired = job._check_decision_needed( NOW )
        assert fired == 1
        assert "DECISION-NEEDED" in escal[ 0 ] and "escalating to Rick" in escal[ 0 ]
        assert "María" in escal[ 0 ] and "JWT vs OAuth" in escal[ 0 ]
        assert gw.read_calls[ 0 ] == ( DECISION_TOPIC, "t1" )
        assert job._decision_since == "t5"                   # cursor advanced

    def test_multiple_entries_each_escalate_nondict_skipped( self ):
        gw = _GW( read_entries=[
            { "ts": "t2", "body": "A", "sender_session_id": "s1" },
            "not-a-dict",
            { "ts": "t3", "body": "B" },
            { "body": "C (no ts)" },           # escalates but does NOT advance the cursor
        ] )
        escal = [ ]
        job = _job( gw, notify=lambda m, *a, **k: escal.append( m ) )
        job._decision_since = "t1"
        assert job._check_decision_needed( NOW ) == 3 and len( escal ) == 3
        assert job._decision_since == "t3"     # advanced to the latest real ts, no-ts entry didn't move it

    def test_read_exception_swallowed( self ):
        gw = _GW( read_raises=True )
        job = _job( gw )
        job._decision_since = "t1"
        assert job._check_decision_needed( NOW ) == 0       # never raises


# ── whole-fleet-stall (D3 catch-all) ───────────────────────────────────────────

class TestFleetStall:
    def test_progress_change_resets_timer( self ):
        job = _job( _GW() )
        assert job._check_fleet_stall( { "s1": _stuck( "s1" ) }, NOW ) == 0          # baseline sig
        # state advances (s1 no longer stuck) → progress → reset, no escalation
        later = NOW + datetime.timedelta( seconds=9999 )
        assert job._check_fleet_stall( { "s1": _idle( "s1" ) }, later ) == 0

    def test_stall_fires_with_fresh_manager_and_stuck_no_progress( self ):
        """KRISHNA ANCHOR: stall fires on {fresh manager}+{stuck}+{no progress for X}.
        The detector takes NO who_rows / manager liveness → it CANNOT be gated by a
        fresh manager; an alive-but-ignoring manager is caught here (not by D4)."""
        escal = [ ]
        job = _job( _GW(), stall_window=600, notify=lambda m, *a, **k: escal.append( m ) )
        fleet = { "s1": _stuck( "s1" ) }
        assert job._check_fleet_stall( fleet, NOW ) == 0                             # baseline
        # identical (no progress) past the window → escalate, regardless of any
        # (fresh) manager liveness, which this path never consults.
        fired = job._check_fleet_stall( fleet, NOW + datetime.timedelta( seconds=700 ) )
        assert fired == 1
        assert "WHOLE-FLEET-STALL" in escal[ 0 ] and "escalating to Rick" in escal[ 0 ]

    def test_idle_fleet_no_owed_no_stall( self ):
        job = _job( _GW(), stall_window=600 )
        fleet = { "s1": _idle( "s1" ) }                                              # no owed work
        job._check_fleet_stall( fleet, NOW )
        assert job._check_fleet_stall( fleet, NOW + datetime.timedelta( seconds=700 ) ) == 0

    def test_escalate_once_then_rearm_after_progress( self ):
        escal = [ ]
        job = _job( _GW(), stall_window=600, notify=lambda m, *a, **k: escal.append( m ) )
        stuck = { "s1": _stuck( "s1" ) }
        job._check_fleet_stall( stuck, NOW )                                          # baseline
        assert job._check_fleet_stall( stuck, NOW + datetime.timedelta( seconds=700 ) ) == 1
        # still stalled → no re-escalation (once per episode)
        assert job._check_fleet_stall( stuck, NOW + datetime.timedelta( seconds=900 ) ) == 0
        assert len( escal ) == 1
        # progress (different crew) → re-arm
        prog = { "s1": _stuck( "s1" ), "s2": _stuck( "s2" ) }
        assert job._check_fleet_stall( prog, NOW + datetime.timedelta( seconds=1000 ) ) == 0
        # stall again → escalates a 2nd episode
        assert job._check_fleet_stall( prog, NOW + datetime.timedelta( seconds=1700 ) ) == 1
        assert len( escal ) == 2

    def test_non_dict_views_ignored_in_signature( self ):
        job = _job( _GW(), stall_window=600 )
        # a non-dict view must not crash the signature
        assert job._check_fleet_stall( { "bad": "x", "s1": _stuck( "s1" ) }, NOW ) == 0


# ── 2b-1 calibration: liveness GATES the stall trigger ─────────────────────────

class TestFleetStallCalibration:
    """
    2b-1 receipt (a): the whole-fleet-stall false-positive (#11) calibration.

    Tiberius's framing: liveness GATES whether to evaluate a stall (a dead/offline
    roster never escalates), while PROGRESS stays keyed on work-advancement (the
    semantic signature) — so commons chatter, which is liveness not progress, can
    NOT mask a real stall. The receipts:
      • (regression) the documented Part-3/Part-7 false-fire — a DEAD/offline
        roster with frozen owed-work state — is now SUPPRESSED.
      • (true-positive) a LIVE owed-work fleet, frozen past the window, STILL fires.
      • (chatty-but-stuck) a LIVE fleet whose commons recency advances while WORK
        does not — a REAL stall — STILL fires (commons never enters the signature).
    """

    def test_regression_dead_offline_roster_with_owed_is_suppressed( self ):
        """REGRESSION (receipt a): reproduce the OLD false-positive at the view
        level. Offline sessions (alive=False) with frozen owed-work `state`, held
        past the window. The OLD predicate (owed-work ALONE) is TRUE → it fired;
        the NEW gate (LIVE owed-work) is FALSE → suppressed."""
        escal = [ ]
        job   = _job( _GW(), stall_window=600, notify=lambda m, *a, **k: escal.append( m ) )
        dead  = { "s1": _stuck( "s1", alive=False ), "s2": _stuck( "s2", alive=False ) }
        # the roster DOES owe work (the OLD predicate) but no LIVE session owes it
        # (the NEW gate) — exactly the dead-roster shape the old trigger mis-fired on
        assert any( v[ "state" ] in ( "working", "stuck", "holding" ) for v in dead.values() )  # OLD → fire
        assert job._has_live_owed_work( dead ) is False                                          # NEW → blocked
        assert job._check_fleet_stall( dead, NOW ) == 0                                           # baseline
        # frozen (no progress) past the window — the OLD bug fired HERE; now silent
        assert job._check_fleet_stall( dead, NOW + datetime.timedelta( seconds=700 ) ) == 0
        assert escal == [ ]

    def test_regression_via_real_fleet_view_offline_sessions( self ):
        """REGRESSION (faithful, through the REAL leaf): build the roster from
        build_fleet_view with only STALE stop-events (2-day-old ts, no bridge/
        commons) → every session alive=False → no LIVE owed work → suppressed even
        past the window. This is the literal Part-7 scenario (dead historical
        roster reading as 100%-offline 'no progress')."""
        from cosa.agents.heartbeat_arbiter.fleet_data_model import build_fleet_view
        old_ts = ( NOW - datetime.timedelta( days=2 ) ).isoformat()
        events = {
            "h1": [ { "session_id": "h1", "persona": "Ann", "outcome": "poked",
                      "ts": old_ts, "awaiting": "peer:Bob", "work_owed": True } ],
            "h2": [ { "session_id": "h2", "persona": "Bob", "outcome": "cap_reached",
                      "ts": old_ts, "work_owed": True },
                    { "session_id": "h2", "persona": "Bob", "outcome": "cap_reached",
                      "ts": old_ts, "work_owed": True } ],
        }
        view = build_fleet_view( events, who_rows=[ ], now=NOW,
                                 alive_threshold_seconds=600, bridge_sessions={ } )
        assert view and all( v[ "alive" ] is False for v in view.values() )                     # all OFFLINE
        assert any( v[ "state" ] in ( "working", "stuck", "holding" ) for v in view.values() )   # OLD → fire
        job = _job( _GW(), stall_window=600 )
        assert job._check_fleet_stall( view, NOW ) == 0                                           # baseline
        assert job._check_fleet_stall( view, NOW + datetime.timedelta( seconds=700 ) ) == 0       # SUPPRESSED

    def test_true_positive_live_owed_frozen_still_fires( self ):
        """TRUE-POSITIVE (receipt a): a LIVE owed-work session (alive=True), frozen
        past the window → STILL fires. Calibration must not suppress real stalls."""
        escal = [ ]
        job   = _job( _GW(), stall_window=600, notify=lambda m, *a, **k: escal.append( m ) )
        live  = { "s1": _stuck( "s1", alive=True ) }
        assert job._check_fleet_stall( live, NOW ) == 0                                           # baseline
        assert job._check_fleet_stall( live, NOW + datetime.timedelta( seconds=700 ) ) == 1       # FIRES
        assert "WHOLE-FLEET-STALL" in escal[ 0 ] and "escalating to Rick" in escal[ 0 ]

    def test_chatty_but_stuck_live_fleet_still_fires( self ):
        """CHATTY-BUT-STUCK (Tiberius's caveat): a LIVE fleet posting 'still
        blocked' (commons recency ADVANCING) while WORK does not advance is a REAL
        stall. Commons recency is liveness, not progress — it must NEVER reach the
        signature. Here commons_ts advances between polls but `state` stays frozen
        → progress signature UNCHANGED → STILL fires."""
        escal   = [ ]
        job     = _job( _GW(), stall_window=600, notify=lambda m, *a, **k: escal.append( m ) )
        chatty1 = { "s1": { **_stuck( "s1" ), "commons_ts": "2026-06-06T22:00:00+00:00" } }
        # same WORK state, but commons recency advanced 11 min (the fleet is chatting)
        chatty2 = { "s1": { **_stuck( "s1" ), "commons_ts": "2026-06-06T22:11:00+00:00" } }
        assert job._check_fleet_stall( chatty1, NOW ) == 0                                        # baseline
        assert job._check_fleet_stall( chatty2, NOW + datetime.timedelta( seconds=700 ) ) == 1    # FIRES
        assert "WHOLE-FLEET-STALL" in escal[ 0 ]

    def test_live_and_dead_mixed_owed_fires_on_the_live_one( self ):
        """A roster mixing a DEAD owed session + a LIVE owed session still has LIVE
        owed work → fires (the gate is ANY live owed, not ALL)."""
        escal = [ ]
        job   = _job( _GW(), stall_window=600, notify=lambda m, *a, **k: escal.append( m ) )
        mixed = { "dead": _stuck( "dead", alive=False ), "live": _stuck( "live", alive=True ) }
        assert job._check_fleet_stall( mixed, NOW ) == 0
        assert job._check_fleet_stall( mixed, NOW + datetime.timedelta( seconds=700 ) ) == 1


if __name__ == "__main__":
    sys.exit( pytest.main( [ __file__, "-v" ] ) )
