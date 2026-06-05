#!/usr/bin/env python3
"""
Unit tests for the Heartbeat Arbiter idle-roster leaf.

Target: 100% line + branch + function coverage of
    cosa/agents/heartbeat_arbiter/idle_roster.py
"""
import datetime

from cosa.agents.heartbeat_arbiter import idle_roster as r


UTC = datetime.timezone.utc
NOW = datetime.datetime( 2026, 6, 5, 12, 0, 0, tzinfo=UTC )


def _v( **kw ):
    base = {
        "session_id"       : "s",
        "persona"          : "P",
        "last_outcome"     : "poke",
        "alive"            : True,
        "last_activity_ts" : NOW - datetime.timedelta( seconds=600 ),
    }
    base.update( kw )
    return base


# ── _quiet_for_seconds ────────────────────────────────────────────────────────

def test_quiet_for_seconds():
    assert r._quiet_for_seconds( None, NOW ) is None
    assert r._quiet_for_seconds( "bad", NOW ) is None                       # TypeError path
    assert r._quiet_for_seconds( NOW - datetime.timedelta( seconds=10 ), NOW ) == 10


# ── classify_idle ─────────────────────────────────────────────────────────────

def test_classify_declared_wins():
    assert r.classify_idle( _v( last_outcome="idle" ), NOW, 300 ) == ( r.IDLE_SOURCE_DECLARED, r.TRUST_DECLARED )


def test_classify_not_alive_is_none():
    assert r.classify_idle( _v( alive=False ), NOW, 300 ) is None


def test_classify_inferred_when_alive_and_quiet():
    v = _v( alive=True, last_activity_ts=NOW - datetime.timedelta( seconds=600 ) )
    assert r.classify_idle( v, NOW, 300 ) == ( r.IDLE_SOURCE_INFERENCE, r.TRUST_INFERRED )


def test_classify_not_quiet_is_none():
    v = _v( alive=True, last_activity_ts=NOW - datetime.timedelta( seconds=10 ) )
    assert r.classify_idle( v, NOW, 300 ) is None


def test_classify_bad_ts_is_none():
    assert r.classify_idle( _v( alive=True, last_activity_ts="bad" ), NOW, 300 ) is None


# ── build_roster ──────────────────────────────────────────────────────────────

def test_build_roster_filters_labels_and_sorts():
    fv = {
        "s1": _v( session_id="s1", last_outcome="idle", last_activity_ts=NOW - datetime.timedelta( seconds=600 ) ),
        "s2": _v( session_id="s2", last_outcome="poke", alive=True, last_activity_ts=NOW - datetime.timedelta( seconds=900 ) ),
        "s3": _v( session_id="s3", last_outcome="poke", alive=True, last_activity_ts=NOW - datetime.timedelta( seconds=10 ) ),  # working
        "s4": "not-a-dict",
    }
    roster = r.build_roster( fv, NOW, 300 )
    assert [ e[ "session_id" ] for e in roster ] == [ "s1", "s2" ]    # s1 ts newer → first
    assert roster[ 0 ][ "trust_label" ] == r.TRUST_DECLARED
    assert roster[ 1 ][ "idle_source" ] == "inference"


def test_build_roster_none_ts_sorts_last():
    fv = {
        "s1": _v( session_id="s1", last_outcome="idle", last_activity_ts=None ),
        "s2": _v( session_id="s2", last_outcome="idle", last_activity_ts=NOW - datetime.timedelta( seconds=100 ) ),
    }
    roster = r.build_roster( fv, NOW, 300 )
    assert [ e[ "session_id" ] for e in roster ] == [ "s2", "s1" ]    # missing ts sorts last


def test_quick_smoke_test():
    assert r.quick_smoke_test() is True
