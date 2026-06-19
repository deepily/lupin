#!/usr/bin/env python3
"""
Unit tests for the Heartbeat-Arbiter consumer wiring state (arbiter_state.py).

Covers FleetEventAccumulator (append, per-session bound/cap, first-seen,
snapshot order) and PingLedger (get/record, clear-on-resume drop semantics).
Pure state — no I/O, no clock.

Venue: :7999-eligible / local — pure module, sub-second.
"""
import os
import sys

import pytest

# Bootstrap
_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from cosa.agents.heartbeat_arbiter.arbiter_state import (
    FleetEventAccumulator, PingLedger, DEFAULT_TAIL_MAXLEN,
)


# ── FleetEventAccumulator ─────────────────────────────────────────────────────

def test_accumulate_appends_across_polls():
    acc = FleetEventAccumulator()
    acc.update( { "s1": [ { "n": 1 } ] } )
    acc.update( { "s1": [ { "n": 2 }, { "n": 3 } ] } )
    assert [ r[ "n" ] for r in acc.snapshot()[ "s1" ] ] == [ 1, 2, 3 ]


def test_accumulate_caps_at_maxlen_dropping_oldest():
    acc = FleetEventAccumulator( maxlen=2 )
    acc.update( { "s1": [ { "n": 1 }, { "n": 2 }, { "n": 3 } ] } )
    assert [ r[ "n" ] for r in acc.snapshot()[ "s1" ] ] == [ 2, 3 ]


def test_accumulate_first_seen_session_gets_fresh_deque():
    acc = FleetEventAccumulator()
    acc.update( { "s1": [ { "n": 1 } ], "s2": [ { "n": 9 } ] } )
    snap = acc.snapshot()
    assert snap[ "s1" ][ 0 ][ "n" ] == 1 and snap[ "s2" ][ 0 ][ "n" ] == 9


def test_accumulate_empty_update_noop():
    acc = FleetEventAccumulator()
    acc.update( { } )
    assert acc.snapshot() == { } and acc.sessions() == set()


def test_sessions_reports_all_seen():
    acc = FleetEventAccumulator()
    acc.update( { "a": [ { "n": 1 } ] } )
    acc.update( { "b": [ { "n": 1 } ] } )
    assert acc.sessions() == { "a", "b" }


def test_default_maxlen_constant():
    assert DEFAULT_TAIL_MAXLEN == 50
    acc = FleetEventAccumulator()
    assert acc._maxlen == 50


# ── PingLedger ────────────────────────────────────────────────────────────────

def test_ledger_get_missing_is_none():
    assert PingLedger().get_last( "e" ) is None


def test_ledger_record_and_get():
    led = PingLedger()
    led.record_ping( "e1", "t1" )
    assert led.get_last( "e1" ) == "t1"


def test_ledger_record_overwrites():
    led = PingLedger()
    led.record_ping( "e1", "t1" )
    led.record_ping( "e1", "t2" )
    assert led.get_last( "e1" ) == "t2"


def test_ledger_clear_resolved_drops_inactive():
    led = PingLedger()
    led.record_ping( "eA", "t1" )
    led.record_ping( "eB", "t2" )
    led.record_ping( "eC", "t3" )
    dropped = led.clear_resolved( { "eA", "eC" } )
    assert dropped == { "eB" }
    assert led.tracked_edges() == { "eA", "eC" }


def test_ledger_clear_resolved_none_active_drops_all():
    led = PingLedger()
    led.record_ping( "eA", "t1" )
    assert led.clear_resolved( set() ) == { "eA" }
    assert led.tracked_edges() == set()


def test_ledger_clear_resolved_all_active_drops_none():
    led = PingLedger()
    led.record_ping( "eA", "t1" )
    assert led.clear_resolved( { "eA", "eX" } ) == set()
    assert led.tracked_edges() == { "eA" }


# ── smoke ─────────────────────────────────────────────────────────────────────

def test_quick_smoke_test_passes():
    from cosa.agents.heartbeat_arbiter import arbiter_state
    assert arbiter_state.quick_smoke_test() is True
