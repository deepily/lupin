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
        "last_outcome"     : "poked",
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
        "s2": _v( session_id="s2", last_outcome="poked", alive=True, last_activity_ts=NOW - datetime.timedelta( seconds=900 ) ),
        "s3": _v( session_id="s3", last_outcome="poked", alive=True, last_activity_ts=NOW - datetime.timedelta( seconds=10 ) ),  # working
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


# ── build_roster staleness filter (free-count fix, 2026-06-24) ─────────────────
# A roster entry counts as "free" only if idle/quiet AND its session is NOT stale
# (dependency_graph.session_is_stale — the SAME predicate the storm/edge fixes use).
# alive_threshold_seconds defaults None → no gate → byte-identical to today.

ALIVE = 600    # alive_threshold_seconds for these cases


def test_build_roster_excludes_stale_declared_session():
    # A DEAD session with a sticky idle beacon (EVENT_IDLE) but last_activity_ts
    # beyond alive_threshold → EXCLUDED once the threshold is threaded. THE bug.
    fv = {
        "s1": _v( session_id="s1", last_outcome="idle",
                  last_activity_ts=NOW - datetime.timedelta( seconds=900 ) ),   # stale (900 > 600)
    }
    roster = r.build_roster( fv, NOW, 300, alive_threshold_seconds=ALIVE )
    assert roster == [ ]                                                        # phantom dropped


def test_build_roster_includes_fresh_idle_session():
    # A genuinely-live idle session (ts within alive_threshold) stays counted.
    fv = {
        "s1": _v( session_id="s1", last_outcome="idle",
                  last_activity_ts=NOW - datetime.timedelta( seconds=120 ) ),   # fresh (120 < 600)
    }
    roster = r.build_roster( fv, NOW, 300, alive_threshold_seconds=ALIVE )
    assert [ e[ "session_id" ] for e in roster ] == [ "s1" ]


def test_build_roster_keeps_missing_ts_session_failsafe():
    # Missing last_activity_ts → session_is_stale fail-SAFE False → KEPT (never
    # under-report live capacity), mirroring the storm fixes' bias-to-keep.
    fv = {
        "s1": _v( session_id="s1", last_outcome="idle", last_activity_ts=None ),
    }
    roster = r.build_roster( fv, NOW, 300, alive_threshold_seconds=ALIVE )
    assert [ e[ "session_id" ] for e in roster ] == [ "s1" ]


def test_build_roster_count_collapses_to_live_idle_subset():
    # Mixed fleet: one fresh declared, one fresh inferred (alive+quiet), one stale
    # declared (sticky beacon, dead), one stale inferred → count collapses to the
    # two live-idle entries. Staleness applied UNIFORMLY (declared + inferred).
    fv = {
        "fresh_decl"  : _v( session_id="fresh_decl", last_outcome="idle",
                            last_activity_ts=NOW - datetime.timedelta( seconds=120 ) ),
        "fresh_infer" : _v( session_id="fresh_infer", last_outcome="poked", alive=True,
                            last_activity_ts=NOW - datetime.timedelta( seconds=400 ) ),   # quiet(>300), fresh(<600)
        "stale_decl"  : _v( session_id="stale_decl", last_outcome="idle",
                            last_activity_ts=NOW - datetime.timedelta( seconds=5000 ) ),  # dead beacon
        "stale_infer" : _v( session_id="stale_infer", last_outcome="poked", alive=True,
                            last_activity_ts=NOW - datetime.timedelta( seconds=5000 ) ),  # stale
    }
    roster = r.build_roster( fv, NOW, 300, alive_threshold_seconds=ALIVE )
    assert set( e[ "session_id" ] for e in roster ) == { "fresh_decl", "fresh_infer" }
    assert len( roster ) == 2


def test_build_roster_threshold_none_is_byte_identical():
    # alive_threshold_seconds omitted (None) → no staleness gate → today's behavior:
    # a stale declared beacon is STILL counted (the un-threaded additive default).
    fv = {
        "s1": _v( session_id="s1", last_outcome="idle",
                  last_activity_ts=NOW - datetime.timedelta( seconds=9000 ) ),
    }
    assert [ e[ "session_id" ] for e in r.build_roster( fv, NOW, 300 ) ] == [ "s1" ]


def test_quick_smoke_test():
    assert r.quick_smoke_test() is True
