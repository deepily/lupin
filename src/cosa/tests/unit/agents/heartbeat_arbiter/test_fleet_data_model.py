#!/usr/bin/env python3
"""
Unit tests for the Heartbeat Arbiter fleet data-model transform.

Target: 100% line + branch + function coverage of
    cosa/agents/heartbeat_arbiter/fleet_data_model.py

Pure transform — all inputs injected (events + who rows + now); no I/O.
"""
import datetime

from cosa.agents.heartbeat_arbiter import fleet_data_model as f


UTC = datetime.timezone.utc
NOW = datetime.datetime( 2026, 6, 5, 12, 0, 0, tzinfo=UTC )


def _ts( secs_ago ):
    return ( NOW - datetime.timedelta( seconds=secs_ago ) ).isoformat()


# ── _parse_iso ────────────────────────────────────────────────────────────────

def test_parse_iso_variants():
    assert f._parse_iso( None ) is None
    assert f._parse_iso( "" ) is None
    assert f._parse_iso( 123 ) is None
    assert f._parse_iso( "not-a-ts" ) is None
    assert f._parse_iso( "2026-06-05T12:00:00Z" ) == datetime.datetime( 2026, 6, 5, 12, 0, 0, tzinfo=UTC )
    naive = f._parse_iso( "2026-06-05T12:00:00" )
    assert naive == datetime.datetime( 2026, 6, 5, 12, 0, 0, tzinfo=UTC )
    assert f._parse_iso( "2026-06-05T12:00:00+05:00" ).utcoffset() == datetime.timedelta( hours=5 )


# ── _age_seconds / _is_recent ─────────────────────────────────────────────────

def test_age_seconds():
    assert f._age_seconds( None, NOW ) is None
    assert f._age_seconds( "bad", NOW ) is None                     # TypeError path
    assert f._age_seconds( NOW - datetime.timedelta( seconds=10 ), NOW ) == 10


def test_is_recent():
    assert f._is_recent( None, NOW, 60 ) is False
    assert f._is_recent( NOW - datetime.timedelta( seconds=30 ), NOW, 60 ) is True
    assert f._is_recent( NOW - datetime.timedelta( seconds=90 ), NOW, 60 ) is False
    assert f._is_recent( NOW + datetime.timedelta( seconds=5 ), NOW, 60 ) is True   # future ⇒ recent


# ── _newer ────────────────────────────────────────────────────────────────────

def test_newer():
    a = NOW
    b = NOW - datetime.timedelta( seconds=10 )
    assert f._newer( None, b ) is b
    assert f._newer( a, None ) is a
    assert f._newer( a, b ) is a
    assert f._newer( b, a ) is a


# ── _who_matches ──────────────────────────────────────────────────────────────

def test_who_matches():
    assert f._who_matches( "s1", "s1" ) is True
    assert f._who_matches( "s1-full-uuid", "s1" ) is True     # row full, sid short
    assert f._who_matches( "s1", "s1-full" ) is True          # sid full, row short
    assert f._who_matches( "x", "y" ) is False
    assert f._who_matches( None, "s1" ) is False
    assert f._who_matches( "s1", None ) is False


# ── _commons_ts_for_session ───────────────────────────────────────────────────

def test_commons_ts_for_session():
    rows = [
        "not-a-dict",
        { "session_id": "other", "last_post_ts": _ts( 5 ) },     # no match
        { "session_id": "s1",    "last_post_ts": None },          # match, ts None
        { "session_id": "s1",    "last_post_ts": _ts( 100 ) },
        { "session_id": "s1-uuid", "last_post_ts": _ts( 20 ) },   # newer, prefix match
    ]
    assert f._commons_ts_for_session( rows, "s1" ) == f._parse_iso( _ts( 20 ) )
    assert f._commons_ts_for_session( [ ], "s1" ) is None


# ── _count_stuck_episodes ─────────────────────────────────────────────────────

def test_count_stuck_episodes():
    events = [
        { "outcome": "cap_reached", "work_owed": True },
        { "outcome": "cap_reached", "work_owed": False },     # not owed
        { "outcome": "poke",        "work_owed": True },
        "not-a-dict",
        { "outcome": "cap_reached", "work_owed": True },
    ]
    assert f._count_stuck_episodes( events ) == 2


# ── build_fleet_view ──────────────────────────────────────────────────────────

def test_build_view_skips_empty_and_invalid():
    v = f.build_fleet_view( { "s1": [ ], "s2": None, "s3": "x", "s4": [ "not-dict" ] }, [ ], NOW, 3600 )
    assert v == { }


def test_build_view_full():
    events = {
        "s1": [ { "persona": "Ann", "ts": _ts( 30 ), "outcome": "poke",
                  "awaiting": "peer:Bob", "poke_count": 1, "cap": 3, "work_owed": True } ],
        "s2": [ { "persona": "Bob", "ts": _ts( 9000 ), "outcome": "cap_reached",
                  "work_owed": True, "poke_count": 3, "cap": 3 },
                { "persona": "Bob", "ts": _ts( 60 ), "outcome": "cap_reached",
                  "work_owed": True, "poke_count": 3, "cap": 3 } ],
    }
    who = [ { "session_id": "s2", "last_post_ts": _ts( 40 ) } ]
    v = f.build_fleet_view( events, who, NOW, 3600 )
    assert v[ "s1" ][ "state" ] == "working"
    assert v[ "s1" ][ "holding_on" ] == "peer:Bob"
    assert v[ "s1" ][ "alive" ] is True
    assert v[ "s1" ][ "stuck" ] is False               # 0 cap_reached
    assert v[ "s1" ][ "poke_count" ] == 1 and v[ "s1" ][ "cap" ] == 3
    assert v[ "s2" ][ "stuck" ] is True                # 2 cap_reached+owed ⇒ repeated
    assert v[ "s2" ][ "alive" ] is True                # commons ts recent though event old


def test_build_view_holding_on_default_and_idle_state():
    events = { "s1": [ { "persona": "Ann", "ts": _ts( 30 ), "outcome": "idle",
                         "awaiting": None, "poke_count": 0, "cap": 3 } ] }
    v = f.build_fleet_view( events, None, NOW, 3600 )
    assert v[ "s1" ][ "holding_on" ] == "none"
    assert v[ "s1" ][ "state" ] == "idle"


def test_build_view_unknown_state():
    events = { "s1": [ { "persona": "Ann", "ts": _ts( 30 ), "outcome": "weird", "poke_count": 0, "cap": 3 } ] }
    assert f.build_fleet_view( events, [ ], NOW, 3600 )[ "s1" ][ "state" ] == "unknown"


def test_build_view_last_not_dict_skipped():
    # the LAST tail record is non-dict → that session is skipped
    assert f.build_fleet_view( { "s1": [ { "ok": 1 }, "trailing-non-dict" ] }, [ ], NOW, 3600 ) == { }


def test_quick_smoke_test():
    assert f.quick_smoke_test() is True
