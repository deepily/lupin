#!/usr/bin/env python3
"""
Unit tests for the 6929f4ac OUTWARD-twin arbiter backstop (§9.2): a dark session
holding an open, aged direct user-gate is re-surfaced to Rick on its behalf.

Design: planning-is-prompting → src/rnd/2026.06.22-receipts-of-progress-heartbeat-
owed-calc.md §9.2. Covers the full changed arbiter surface with INJECTED fakes
(hold_reader_fn + notify_fn), no IO:
  - ctor validation of user_gate_resurface_seconds
  - _classify_owed open-gate → ACTIVE override (and the None-seam no-op)
  - _check_user_gate_resurface — dark+aged-gate → case-18 Rick escalation,
    escalate-once, re-arm, darkness gate, hold-read-hiccup swallow, inert seam
"""
import datetime
import os
import sys

import pytest

# Bootstrap
_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from cosa.agents.heartbeat_arbiter.arbiter_job import (
    ArbiterConsumerJob, CLASS_ACTIVE, CLASS_DONE, CLASS_BLOCKED_ON_USER,
)
from cosa.agents.heartbeat_arbiter.arbiter_routing import CASE_USER_GATE_RESURFACE
from lupin_cli.claude_code.hooks.lib import heartbeat_user_gates as ug


NOW = datetime.datetime( 2026, 6, 22, 12, 0, 0, tzinfo=datetime.timezone.utc )


def _ago( seconds ):
    return ( NOW - datetime.timedelta( seconds=seconds ) ).isoformat()


class _Gateway:
    def __init__( self ):
        self.sent, self.posts = [ ], [ ]
    def who( self, retention_hours=24 ): return [ ]
    def send_to( self, recipient, body, metadata=None ): self.sent.append( ( recipient, body ) )
    def post( self, topic, body ): self.posts.append( ( topic, body ) )
    def read( self, topic, since=None, limit=50 ): return [ ]


def _job( *, hold_reader_fn=None, owed_work_fn=None, notify=None,
          user_gate_resurface_seconds=1800 ):
    return ArbiterConsumerJob(
        commons                     = _Gateway(),
        poll_seconds                = 5,
        manager_recipient           = "DeclaredMgr",
        hold_reader_fn              = hold_reader_fn,
        owed_work_fn                = owed_work_fn,
        user_gate_resurface_seconds = user_gate_resurface_seconds,
        bridge_mtime_fn             = lambda sid: None,
        notify_fn                   = notify or ( lambda *a, **k: None ),
    )


def _snapshot( *rows ):
    return { "generated_at": NOW.isoformat(), "session_count": len( rows ), "sessions": list( rows ) }


def _row( sid, persona, *, verdict="offline", freshest_age_s=None ):
    return { "session_id": sid, "persona": persona, "state": "running",
             "liveness": { "verdict": verdict, "freshest_age_s": freshest_age_s } }


def _hold_with_gate( gate ):
    return { "pending_user_gates": [ gate ], "last_looked_in_on_workers_ts": None }


# ── ctor validation ───────────────────────────────────────────────────────────

class TestCtorValidation:

    def test_zero_resurface_seconds_raises( self ):
        with pytest.raises( ValueError ):
            _job( user_gate_resurface_seconds=0 )

    def test_negative_resurface_seconds_raises( self ):
        with pytest.raises( ValueError ):
            _job( user_gate_resurface_seconds=-1 )

    def test_default_seam_inert( self ):
        # No hold_reader → resurface returns 0 regardless of snapshot.
        job = _job()
        row = _row( "s1", "Sam" )
        assert job._check_user_gate_resurface( _snapshot( row ), NOW ) == 0


# ── _classify_owed open-gate → ACTIVE override ────────────────────────────────

class TestClassifyOwedGateOverride:

    def _open_gate_hold( self, sid ):
        # hold reader returns an OPEN gate for s1 only
        gate = ug.make_gate( "g1", "Proceed?", "ask_yes_no", last_asked_ts=_ago( 60 ) )
        return lambda s: _hold_with_gate( gate ) if s == sid else None

    def test_open_gate_overrides_done_to_active( self ):
        # store says DONE (zero owed items) but an open gate ⇒ ACTIVE (owes re-ask).
        job = _job( owed_work_fn=lambda names: { n: [ ] for n in names },
                    hold_reader_fn=self._open_gate_hold( "s1" ) )
        fleet_view = { "s1": { "persona": "Sam" } }
        assert job._classify_owed( [ "Sam" ], fleet_view ) == { "Sam": CLASS_ACTIVE }

    def test_open_gate_overrides_blocked_on_user_to_active( self ):
        owed = { "Sam": [ { "status": "in_progress", "gate_class": "operator", "blocked_by": None } ] }
        job  = _job( owed_work_fn=lambda names: owed,
                     hold_reader_fn=self._open_gate_hold( "s1" ) )
        fleet_view = { "s1": { "persona": "Sam" } }
        # would be BLOCKED_ON_USER from the store; the open gate flips it ACTIVE
        assert job._classify_owed( [ "Sam" ], fleet_view ) == { "Sam": CLASS_ACTIVE }

    def test_no_open_gate_leaves_store_class( self ):
        # answered gate ⇒ no open gate ⇒ store DONE stands
        gate = ug.make_gate( "g1", "Proceed?", "ask_yes_no", last_asked_ts=_ago( 60 ), answered=True )
        job  = _job( owed_work_fn=lambda names: { n: [ ] for n in names },
                     hold_reader_fn=lambda s: _hold_with_gate( gate ) )
        assert job._classify_owed( [ "Sam" ], { "s1": { "persona": "Sam" } } ) == { "Sam": CLASS_DONE }

    def test_persona_not_in_fleet_view_no_override( self ):
        job = _job( owed_work_fn=lambda names: { n: [ ] for n in names },
                    hold_reader_fn=self._open_gate_hold( "s1" ) )
        # fleet_view has no row for Sam → no sid → no hold read → store class stands
        assert job._classify_owed( [ "Sam" ], { } ) == { "Sam": CLASS_DONE }

    def test_hold_read_hiccup_swallowed_no_override( self ):
        def boom( s ): raise RuntimeError( "store down" )
        job = _job( owed_work_fn=lambda names: { n: [ ] for n in names }, hold_reader_fn=boom )
        assert job._classify_owed( [ "Sam" ], { "s1": { "persona": "Sam" } } ) == { "Sam": CLASS_DONE }

    def test_none_seam_no_override_path( self ):
        # hold_reader None → override block skipped entirely (store class stands)
        job = _job( owed_work_fn=lambda names: { n: [ ] for n in names } )
        assert job._classify_owed( [ "Sam" ], { "s1": { "persona": "Sam" } } ) == { "Sam": CLASS_DONE }


# ── _check_user_gate_resurface ────────────────────────────────────────────────

class TestResurfaceDetector:

    def _aged_gate( self ):
        return ug.make_gate( "g1", "Deploy to prod?", "ask_yes_no", last_asked_ts=_ago( 9999 ) )

    def test_dark_session_aged_gate_resurfaces_to_rick( self ):
        calls = [ ]
        job   = _job( hold_reader_fn=lambda s: _hold_with_gate( self._aged_gate() ),
                      notify=lambda *a, **k: calls.append( ( a, k ) ) )
        n = job._check_user_gate_resurface( _snapshot( _row( "s1", "Sam", verdict="offline" ) ), NOW )
        assert n == 1
        # routed Rick-only (notify_fn fired) carrying the question text
        assert calls, "expected a Rick notify for the resurfaced gate"
        body = " ".join( str( x ) for x in calls[ 0 ][ 0 ] ) + " " + " ".join( str( v ) for v in calls[ 0 ][ 1 ].values() )
        assert "Deploy to prod?" in body and "RESURFACED" in body

    def test_escalate_once_then_quiet( self ):
        job = _job( hold_reader_fn=lambda s: _hold_with_gate( self._aged_gate() ) )
        snap = _snapshot( _row( "s1", "Sam", verdict="offline" ) )
        assert job._check_user_gate_resurface( snap, NOW ) == 1
        assert job._check_user_gate_resurface( snap, NOW ) == 0   # already resurfaced → quiet

    def test_rearm_after_gate_clears( self ):
        state = { "gate": self._aged_gate() }
        job   = _job( hold_reader_fn=lambda s: _hold_with_gate( state[ "gate" ] ) )
        snap_dark = _snapshot( _row( "s1", "Sam", verdict="offline" ) )
        assert job._check_user_gate_resurface( snap_dark, NOW ) == 1
        # gate answered ⇒ no longer eligible ⇒ key re-arms
        state[ "gate" ] = ug.make_gate( "g1", "Deploy to prod?", "ask_yes_no",
                                        last_asked_ts=_ago( 9999 ), answered=True )
        assert job._check_user_gate_resurface( snap_dark, NOW ) == 0
        assert job._resurfaced_gates == set()                     # re-armed
        # gate re-opens later ⇒ resurfaces again
        state[ "gate" ] = self._aged_gate()
        assert job._check_user_gate_resurface( snap_dark, NOW ) == 1

    def test_alive_session_not_resurfaced( self ):
        # fresh liveness (verdict online, recent age) ⇒ not dark ⇒ skip
        job  = _job( hold_reader_fn=lambda s: _hold_with_gate( self._aged_gate() ) )
        snap = _snapshot( _row( "s1", "Sam", verdict="online", freshest_age_s=10 ) )
        assert job._check_user_gate_resurface( snap, NOW ) == 0

    def test_dark_by_stale_age_resurfaces( self ):
        # not offline verdict, but freshest age past the ceiling ⇒ dark
        job  = _job( hold_reader_fn=lambda s: _hold_with_gate( self._aged_gate() ),
                     user_gate_resurface_seconds=1800 )
        snap = _snapshot( _row( "s1", "Sam", verdict="quiet", freshest_age_s=2000 ) )
        assert job._check_user_gate_resurface( snap, NOW ) == 1

    def test_fresh_gate_on_dark_session_not_resurfaced( self ):
        # session dark but the gate was re-asked recently ⇒ not aged ⇒ skip
        fresh = ug.make_gate( "g1", "q", "ask_yes_no", last_asked_ts=_ago( 60 ) )
        job   = _job( hold_reader_fn=lambda s: _hold_with_gate( fresh ) )
        snap  = _snapshot( _row( "s1", "Sam", verdict="offline" ) )
        assert job._check_user_gate_resurface( snap, NOW ) == 0

    def test_hold_read_hiccup_swallowed( self ):
        def boom( s ): raise RuntimeError( "hold read failed" )
        job  = _job( hold_reader_fn=boom )
        snap = _snapshot( _row( "s1", "Sam", verdict="offline" ) )
        assert job._check_user_gate_resurface( snap, NOW ) == 0   # degrades to no-gate, no raise

    def test_malformed_rows_and_missing_sid_skipped( self ):
        job  = _job( hold_reader_fn=lambda s: _hold_with_gate( self._aged_gate() ) )
        snap = { "sessions": [ "not-a-dict", { "persona": "NoSid" },          # no session_id
                               _row( "s1", "Sam", verdict="offline" ) ] }
        assert job._check_user_gate_resurface( snap, NOW ) == 1   # only the valid dark row fires

    def test_missing_liveness_block_treated_dark( self ):
        # a row with no liveness dict → age None → dark
        job = _job( hold_reader_fn=lambda s: _hold_with_gate( self._aged_gate() ) )
        snap = { "sessions": [ { "session_id": "s1", "persona": "Sam" } ] }
        assert job._check_user_gate_resurface( snap, NOW ) == 1

    def test_empty_snapshot_returns_zero( self ):
        job = _job( hold_reader_fn=lambda s: _hold_with_gate( self._aged_gate() ) )
        assert job._check_user_gate_resurface( None, NOW ) == 0
        assert job._check_user_gate_resurface( { }, NOW ) == 0


def test_case_kind_registered():
    from cosa.agents.heartbeat_arbiter.arbiter_job import CASE_KINDS
    assert CASE_KINDS[ CASE_USER_GATE_RESURFACE ] == "user_gate_resurface"
