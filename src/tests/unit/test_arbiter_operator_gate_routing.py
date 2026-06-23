#!/usr/bin/env python3
"""
Unit tests for the A2/A3 arbiter operator-gate URGENCY routing (fcb5dbc0): the
arbiter as the SINGLE pusher of STORE operator gates, routed by D4 urgency
(urgent → interrupt, normal → cadence-due digest, low → pull-only).

Covers the full changed arbiter surface with INJECTED fakes (operator_gates_fn +
notify_fn), no IO:
  - ctor validation of operator_digest_cadence_seconds
  - _route_operator_gates — inert seam, swallow-safe read, urgent interrupt +
    escalate-once + re-arm, normal digest + cadence debounce + clock stamp +
    list cap, low pull-only, non-dict filtering
The PURE routing decision is proven in test_operator_gate_routing.py; this proves
the thin arbiter consumer that emits from it.
"""
import datetime
import os
import sys

import pytest

_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from cosa.agents.heartbeat_arbiter.arbiter_job import ArbiterConsumerJob, CASE_KINDS
from cosa.agents.heartbeat_arbiter.arbiter_routing import CASE_OPERATOR_GATE


NOW = datetime.datetime( 2026, 6, 23, 12, 0, 0, tzinfo=datetime.timezone.utc )


def _ago( seconds ):
    return ( NOW - datetime.timedelta( seconds=seconds ) ).isoformat()


class _Gateway:
    def __init__( self ):
        self.sent, self.posts = [ ], [ ]
    def who( self, retention_hours=24 ): return [ ]
    def send_to( self, recipient, body, metadata=None ): self.sent.append( ( recipient, body ) )
    def post( self, topic, body ): self.posts.append( ( topic, body ) )
    def read( self, topic, since=None, limit=50 ): return [ ]


def _job( *, operator_gates_fn=None, operator_digest_cadence_seconds=1800, notify=None ):
    return ArbiterConsumerJob(
        commons                         = _Gateway(),
        poll_seconds                    = 5,
        manager_recipient               = "DeclaredMgr",
        operator_gates_fn               = operator_gates_fn,
        operator_digest_cadence_seconds = operator_digest_cadence_seconds,
        bridge_mtime_fn                 = lambda sid: None,
        notify_fn                       = notify or ( lambda *a, **k: None ),
    )


def _gate( gid, urgency, *, title=None, owner="Sam" ):
    g = { "id": gid, "urgency": urgency, "owner_persona": owner }
    if title is not None:
        g[ "title" ] = title
    return g


def _capture():
    calls = [ ]
    return calls, ( lambda *a, **k: calls.append( a[ 0 ] if a else "" ) )


# ── ctor validation ───────────────────────────────────────────────────────────

class TestCtorValidation:

    def test_zero_cadence_raises( self ):
        with pytest.raises( ValueError ):
            _job( operator_digest_cadence_seconds=0 )

    def test_negative_cadence_raises( self ):
        with pytest.raises( ValueError ):
            _job( operator_digest_cadence_seconds=-1 )


# ── inert seam ────────────────────────────────────────────────────────────────

def test_unwired_seam_is_inert():
    job = _job()   # operator_gates_fn None
    assert job._route_operator_gates( NOW ) == 0


def test_empty_gates_no_emit():
    job = _job( operator_gates_fn=lambda: [ ] )
    assert job._route_operator_gates( NOW ) == 0


def test_read_hiccup_swallowed():
    def boom(): raise RuntimeError( "store down" )
    job = _job( operator_gates_fn=boom )
    assert job._route_operator_gates( NOW ) == 0   # degrades to no gates, no raise


def test_non_dict_entries_filtered():
    job = _job( operator_gates_fn=lambda: [ "junk", None, _gate( "u1", "urgent" ) ] )
    assert job._route_operator_gates( NOW ) == 1   # only the valid urgent gate fires


# ── URGENT interrupt ──────────────────────────────────────────────────────────

class TestUrgentInterrupt:

    def test_urgent_interrupts_to_rick( self ):
        calls, notify = _capture()
        job = _job( operator_gates_fn=lambda: [ _gate( "u1", "urgent", title="Deploy to prod?", owner="Sam" ) ],
                    notify=notify )
        assert job._route_operator_gates( NOW ) == 1
        assert calls and "URGENT" in calls[ 0 ] and "Deploy to prod?" in calls[ 0 ] and "Sam" in calls[ 0 ]

    def test_escalate_once_then_quiet( self ):
        gates = [ _gate( "u1", "urgent", title="t" ) ]
        job   = _job( operator_gates_fn=lambda: gates )
        assert job._route_operator_gates( NOW ) == 1
        assert job._route_operator_gates( NOW ) == 0   # already interrupted → quiet

    def test_rearm_after_gate_clears( self ):
        state = { "gates": [ _gate( "u1", "urgent", title="t" ) ] }
        job   = _job( operator_gates_fn=lambda: state[ "gates" ] )
        assert job._route_operator_gates( NOW ) == 1
        state[ "gates" ] = [ ]                              # gate cleared
        assert job._route_operator_gates( NOW ) == 0
        assert job._routed_operator_gates == set()         # re-armed
        state[ "gates" ] = [ _gate( "u1", "urgent", title="t" ) ]   # re-opens
        assert job._route_operator_gates( NOW ) == 1

    def test_untitled_and_missing_owner_fallbacks( self ):
        calls, notify = _capture()
        job = _job( operator_gates_fn=lambda: [ { "id": "u1", "urgency": "urgent" } ], notify=notify )
        assert job._route_operator_gates( NOW ) == 1
        assert "(untitled)" in calls[ 0 ] and "a session" in calls[ 0 ]


# ── NORMAL digest ─────────────────────────────────────────────────────────────

class TestNormalDigest:

    def test_digest_emitted_when_due( self ):
        calls, notify = _capture()
        job = _job( operator_gates_fn=lambda: [ _gate( "n1", "normal", title="Pick a window" ),
                                                _gate( "n2", "normal", title="Approve copy" ) ],
                    notify=notify )
        # last_digest_ts None ⇒ due ⇒ one digest emission listing both
        assert job._route_operator_gates( NOW ) == 1
        assert "digest" in calls[ 0 ] and "2 normal" in calls[ 0 ]
        assert "Pick a window" in calls[ 0 ] and "Approve copy" in calls[ 0 ]
        # the clock was stamped → an immediate re-poll is NOT due
        assert job._last_operator_digest_ts == NOW.isoformat()
        assert job._route_operator_gates( NOW ) == 0

    def test_digest_withheld_until_cadence( self ):
        job = _job( operator_gates_fn=lambda: [ _gate( "n1", "normal", title="t" ) ],
                    operator_digest_cadence_seconds=1800 )
        job._last_operator_digest_ts = _ago( 60 )          # emitted 1 min ago ⇒ not due
        assert job._route_operator_gates( NOW ) == 0
        assert job._last_operator_digest_ts == _ago( 60 )  # clock untouched

    def test_digest_list_cap_folds_overflow( self ):
        calls, notify = _capture()
        gates = [ _gate( f"n{i}", "normal", title=f"q{i}" ) for i in range( 12 ) ]
        job   = _job( operator_gates_fn=lambda: gates, notify=notify )
        assert job._route_operator_gates( NOW ) == 1
        assert "12 normal" in calls[ 0 ] and "+4 more" in calls[ 0 ]   # 12 - cap(8) = 4


# ── LOW is pull-only ──────────────────────────────────────────────────────────

def test_low_gate_never_pushed():
    calls, notify = _capture()
    job = _job( operator_gates_fn=lambda: [ _gate( "l1", "low", title="someday" ) ], notify=notify )
    assert job._route_operator_gates( NOW ) == 0
    assert calls == [ ]


# ── mixed tiers in one poll ───────────────────────────────────────────────────

def test_mixed_urgent_normal_low():
    calls, notify = _capture()
    job = _job( operator_gates_fn=lambda: [
        _gate( "u1", "urgent", title="urgent-q" ),
        _gate( "n1", "normal", title="normal-q" ),
        _gate( "l1", "low",    title="low-q" ),
    ], notify=notify )
    # 1 urgent interrupt + 1 digest (due) = 2 emissions; low never pushed
    assert job._route_operator_gates( NOW ) == 2
    joined = " || ".join( calls )
    assert "URGENT" in joined and "urgent-q" in joined
    assert "digest" in joined and "normal-q" in joined
    assert "low-q" not in joined


def test_case_kind_registered():
    assert CASE_KINDS[ CASE_OPERATOR_GATE ] == "operator_gate"
