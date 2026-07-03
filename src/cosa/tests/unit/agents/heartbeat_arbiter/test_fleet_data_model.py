#!/usr/bin/env python3
"""
Unit tests for the Heartbeat Arbiter fleet data-model transform.

Target: 100% line + branch + function coverage of
    cosa/agents/heartbeat_arbiter/fleet_data_model.py

Pure transform — all inputs injected (events + who rows + now); no I/O.
"""
import datetime
import json
import os

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
        { "outcome": "poked",        "work_owed": True },
        "not-a-dict",
        { "outcome": "cap_reached", "work_owed": True },
    ]
    assert f._count_stuck_episodes( events ) == 2               # no honored recovery → both live


# ── 5a1f17f8 (a): freshness-gate consumed cap_reached against a later `honored` ──
# The offset-reset replay (a :8001 restart re-reads the events file from byte 0)
# re-surfaces HISTORICAL cap_reached as if fresh. In real streams those are followed
# by `honored` recovery outcomes — so a cap_reached BEFORE the last honored is
# CONSUMED, not live stuck evidence. Only cap_reached+owed AFTER the last honored count.

def test_cap_reached_consumed_by_later_honored_not_counted():
    """The 2026-07-02 replay pattern (Mr Radio's fixture): one historical cap_reached
    followed by ≥1 honored recovery → CONSUMED → 0 live stuck episodes → not wedged."""
    events = [
        { "outcome": "cap_reached", "work_owed": True },        # historical, replayed
        { "outcome": "honored",      "work_owed": True },        # recovery #1
        { "outcome": "honored",      "work_owed": True },        # recovery #2 (…5 in the real file)
    ]
    assert f._count_stuck_episodes( events ) == 0


def test_cap_reached_after_last_honored_still_counts():
    """Recovered-then-re-stuck: cap_reached AFTER the last honored is LIVE. Two such
    → genuinely repeated-stuck (the true-positive is preserved)."""
    events = [
        { "outcome": "cap_reached", "work_owed": True },        # consumed (before honored)
        { "outcome": "honored",      "work_owed": True },        # last recovery
        { "outcome": "cap_reached", "work_owed": True },        # live
        { "outcome": "cap_reached", "work_owed": True },        # live
    ]
    assert f._count_stuck_episodes( events ) == 2


def test_honored_before_cap_reached_does_not_consume():
    """Order matters: a honored BEFORE the cap_reached (recovered, then wedged) does
    NOT consume the later cap_reached — genuine stuck stands."""
    events = [
        { "outcome": "honored",      "work_owed": True },
        { "outcome": "cap_reached", "work_owed": True },
        { "outcome": "cap_reached", "work_owed": True },
    ]
    assert f._count_stuck_episodes( events ) == 2


def test_consumed_cap_reached_not_owed_ignored_either_way():
    """A not-owed cap_reached is never counted, consumed or not (unchanged predicate)."""
    events = [
        { "outcome": "cap_reached", "work_owed": False },
        { "outcome": "honored",      "work_owed": True },
        { "outcome": "cap_reached", "work_owed": False },
    ]
    assert f._count_stuck_episodes( events ) == 0


def test_real_replay_fixture_defeated_by_freshness_gate():
    """RED-BENCH (Mr Radio's preserved 8a92b253 events file, frozen snapshot): the
    2026-07-02 offset-reset replay. Chronological stream has 5 cap_reached+owed but
    each is followed by `honored` recoveries — so the freshness-gate yields 0 live
    stuck episodes (stuck=False), where the OLD all-cap_reached count was 5 (false
    stuck=True → the ~60s STUCK loop-fire). Proves the fix on REAL data shapes, not a
    synthetic mock (feedback_e2e_route_intercept_false_passes_on_real_data)."""
    fixture = os.path.join(
        os.environ[ "LUPIN_ROOT" ], "src", "tests", "unit", "fixtures",
        "arbiter_offset_reset_events.jsonl",
    )
    activity = [ ]
    with open( fixture ) as fh:
        for line in fh:
            line = line.strip()
            if not line or "FIXTURE-META" in line:
                continue
            rec = json.loads( line )
            if rec.get( "outcome" ) != "idle_prompt":            # the ACTIVITY axis
                activity.append( rec )
    old_count = sum( 1 for e in activity
                     if e.get( "outcome" ) == "cap_reached" and e.get( "work_owed" ) is True )
    assert old_count == 5                                        # the replayed historical cap_reached
    assert f._count_stuck_episodes( activity ) == 0             # freshness-gate consumes them all
    assert f._count_stuck_episodes( activity ) < f.STUCK_REPEAT_THRESHOLD   # → stuck=False, no false poke


# ── build_fleet_view ──────────────────────────────────────────────────────────

def test_build_view_skips_empty_and_invalid():
    v = f.build_fleet_view( { "s1": [ ], "s2": None, "s3": "x", "s4": [ "not-dict" ] }, [ ], NOW, 3600 )
    assert v == { }


def test_build_view_full():
    events = {
        "s1": [ { "persona": "Ann", "ts": _ts( 30 ), "outcome": "poked",
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


def test_build_view_non_dict_records_filtered():
    # Non-dict tail records are FILTERED, not session-fatal: the session still
    # builds from its remaining dict records (unrecognized fields ⇒ state
    # "unknown"). A tail with NO dict records at all skips the session.
    # (Re-pinned 2026-06-09: this test previously asserted the pre-filter
    # contract — a trailing non-dict skipped the whole session — which drifted
    # from the implementation and its lupin-side sibling test.)
    view = f.build_fleet_view( { "s1": [ { "ok": 1 }, "trailing-non-dict" ] }, [ ], NOW, 3600 )
    assert set( view ) == { "s1" }
    assert view[ "s1" ][ "state" ] == "unknown" and view[ "s1" ][ "last_outcome" ] is None
    assert f.build_fleet_view( { "s2": [ "all", "non-dict" ] }, [ ], NOW, 3600 ) == { }


def test_build_view_reaped_tombstone_member_off_axis_with_flag():
    """A kind=reaped tombstone (NO outcome) → member with reaped=True, kept OFF
    the activity axis; a non-reaped row carries reaped=False."""
    events = {
        "rp": [ { "session_id": "rp", "persona": "Hal", "kind": "reaped", "ts": _ts( 20 ) } ],
        "s1": [ { "persona": "Ann", "ts": _ts( 30 ), "outcome": "poked", "poke_count": 1, "cap": 3 } ],
    }
    v = f.build_fleet_view( events, [ ], NOW, 3600 )
    assert v[ "rp" ][ "reaped" ] is True
    assert v[ "rp" ][ "state" ] == "unknown" and v[ "rp" ][ "last_event_ts" ] is None
    assert v[ "rp" ][ "persona" ] == "Hal"
    assert v[ "s1" ][ "reaped" ] is False


def test_quick_smoke_test():
    assert f.quick_smoke_test() is True
