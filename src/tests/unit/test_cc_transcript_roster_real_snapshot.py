"""
Tests for the transcript roster fed by the real fleet snapshot, not hand-written rows.

The older roster test feeds rows the producer never emits. Here the rows come from
build_fleet_view and build_snapshot, then through the roster projection.
"""

import datetime

import pytest

from cosa.agents.heartbeat_arbiter.fleet_data_model import build_fleet_view
from cosa.agents.heartbeat_arbiter.fleet_render import build_snapshot
from cosa.rest.routers import cc_transcript as module

SEAT = "449359bc-c735-4970-8fc0-e83b635c8548"
NOW  = datetime.datetime( 2026, 10, 18, 12, 0, 0, tzinfo=datetime.timezone.utc )


def _real_rows():
    """One live seat through the real producer chain."""
    stamp  = ( NOW - datetime.timedelta( seconds=30 ) ).isoformat()
    events = { SEAT: [ {
        "session_id": SEAT, "persona": "Krishna", "outcome": "poke", "ts": stamp,
        "poke_count": 0, "cap": 3, "work_owed": False, "awaiting": None,
    } ] }
    view     = build_fleet_view( events, [ ], NOW, alive_threshold_seconds=3600, bridge_sessions={ SEAT: "Krishna" } )
    snapshot = build_snapshot( view, { SEAT: NOW.timestamp() - 5 }, NOW )
    return stamp, snapshot[ "sessions" ]


def test_the_producer_carries_the_last_activity_time():
    stamp, rows = _real_rows()
    assert len( rows ) == 1, "precondition failed: the seat should be live"
    assert rows[ 0 ][ "last_activity_ts" ] == stamp


def test_the_roster_shows_the_last_activity_time_of_a_real_row( monkeypatch ):
    stamp, rows = _real_rows()
    monkeypatch.setattr( module, "resolve_transcript_path", lambda *a, **k: "" )
    seats = module._project_seats( rows )
    assert seats[ 0 ][ "last_ts" ] == stamp


def test_a_seat_with_no_activity_time_reads_null( monkeypatch ):
    monkeypatch.setattr( module, "resolve_transcript_path", lambda *a, **k: "" )
    seats = module._project_seats( [ { "session_id": SEAT, "last_activity_ts": None } ] )
    assert seats[ 0 ][ "last_ts" ] is None


def test_an_unparseable_activity_time_costs_the_row_nothing():
    snapshot = build_snapshot( { SEAT: { "persona": "Krishna", "last_activity_ts": "not-a-time", "reaped": False } },
                               { SEAT: NOW.timestamp() - 5 }, NOW )
    assert snapshot[ "sessions" ][ 0 ][ "last_activity_ts" ] is None
