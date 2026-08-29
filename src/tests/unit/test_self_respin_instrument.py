#!/usr/bin/env python3
"""
Unit tests — the self-respin sample INSTRUMENT (row 39c88ee7).

The instrument RECORDS raw magnitudes per in-flight respin and DECIDES NOTHING
(Cheech + Mr Radio: instrument-over-detect). These tests prove: the sample shape
(schema-versioned), the collector's match/verdict/pct capture, that the size-
capped rotation actually BOUNDS the file and drops the OLDEST samples, and that a
throwing sampler NEVER breaks the tick. Venue: :7999-eligible (tmp_path, injected
seams).
"""
import datetime
import json
import os
import sys

import pytest

# Bootstrap
_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from cosa.agents.heartbeat_arbiter import self_respin_observer as obs
from cosa.agents.heartbeat_arbiter.self_respin_observer import (
    build_respin_sample, collect_respin_samples, append_respin_samples,
    build_marker_dict, SelfRespinAssessment, SelfRespinVerdict, MARKER_PREFIX,
    RESPIN_SAMPLE_SCHEMA_VERSION, RESPIN_SAMPLES_FILENAME, SelfRespinObserverLoop,
)

UTC = datetime.timezone.utc
NOW = datetime.datetime( 2026, 8, 17, 3, 0, tzinfo=UTC )


def _marker( sid="s1", persona="krishna", pre_pct=55.0, fired_offset_s=300 ):
    fired = NOW - datetime.timedelta( seconds=fired_offset_s )
    return build_marker_dict(
        session_id=sid, persona=persona, tmux_session="cc-x", fired_at=fired,
        delay_seconds=60, pre_clear_status="over_budget", pre_clear_pct=pre_pct,
        memento_path="/m", memento_verified=True, wake_nonce="n1",
    )


def _assessment( v=SelfRespinVerdict.PENDING, sid="s1", persona="krishna" ):
    return SelfRespinAssessment( session_id=sid, persona=persona, verdict=v, reason="", is_alarm=False )


def _write_marker( base, m ):
    ( base / f"{MARKER_PREFIX}{m[ 'session_id' ]}.json" ).write_text( json.dumps( m ) )


class FakeConfig:
    def __init__( self, enabled ): self._enabled = enabled
    def get( self, key, default=None, return_type=None ):
        if key == "arbiter self respin observer enabled": return self._enabled
        return default


# ── build_respin_sample ──────────────────────────────────────────────────────

def test_build_sample_full_fields():
    rec = { "consumption_pct_of_window": 20.7, "session_id": "s1", "tmux_session": "cc-x" }
    s   = build_respin_sample( _marker(), rec, _assessment( SelfRespinVerdict.RETURNED ), NOW )
    assert s[ "schema_version" ]   == RESPIN_SAMPLE_SCHEMA_VERSION
    assert s[ "recorded_at" ]      == NOW.isoformat()
    assert s[ "session_id" ]       == "s1"
    assert s[ "persona" ]          == "krishna"
    assert s[ "pre_clear_status" ] == "over_budget"
    assert s[ "pre_clear_pct" ]    == 55.0
    assert s[ "post_settle_pct" ]  == 20.7
    assert s[ "elapsed_s" ]        == 300.0
    assert s[ "verdict" ]          == "RETURNED"


def test_build_sample_none_record_post_pct_none():
    assert build_respin_sample( _marker(), None, _assessment(), NOW )[ "post_settle_pct" ] is None


def test_build_sample_nonnumeric_pct_none():
    rec = { "consumption_pct_of_window": "n/a" }
    assert build_respin_sample( _marker(), rec, _assessment(), NOW )[ "post_settle_pct" ] is None


def test_build_sample_unparseable_fired_at_elapsed_none():
    m = _marker(); m[ "fired_at" ] = "not-a-date"
    s = build_respin_sample( m, { "consumption_pct_of_window": 10.0 },
                             _assessment( SelfRespinVerdict.MALFORMED_MARKER ), NOW )
    assert s[ "elapsed_s" ]       is None
    assert s[ "post_settle_pct" ] == 10.0


# ── _pressure_by_id ──────────────────────────────────────────────────────────

def test_pressure_by_id_none_section():
    assert obs._pressure_by_id( None ) == {}

def test_pressure_by_id_non_dict_personas():
    assert obs._pressure_by_id( { "personas": "nope" } ) == {}

def test_pressure_by_id_skips_records_without_sid_or_nondict():
    section = { "personas": { "a": { "session_id": "x" }, "b": { "no": "sid" }, "c": "notadict" } }
    assert obs._pressure_by_id( section ) == { "x": { "session_id": "x" } }


# ── collect_respin_samples ───────────────────────────────────────────────────

def test_collect_no_markers_empty( tmp_path ):
    assert collect_respin_samples( base_dir=str( tmp_path ), now=NOW,
                                   fetch_pressure=lambda: { "personas": {} } ) == []


def test_collect_defaults_no_markers( tmp_path ):
    # No now/fetch passed → exercises both None-defaulting branches; empty dir
    # returns [] before the live reader is ever called.
    assert collect_respin_samples( base_dir=str( tmp_path ) ) == []


def test_collect_matches_pressure_and_verdict( tmp_path ):
    _write_marker( tmp_path, _marker( sid="s1", pre_pct=55.0 ) )
    fetch = lambda: { "personas": { "krishna": {
        "session_id": "s1", "tmux_session": "cc-x",
        "consumption_pct_of_window": 19.6, "status": "within_budget", "last_turn_age_s": 5 } } }
    samples = collect_respin_samples( base_dir=str( tmp_path ), now=NOW, fetch_pressure=fetch )
    assert len( samples ) == 1
    assert samples[ 0 ][ "post_settle_pct" ] == 19.6
    assert samples[ 0 ][ "pre_clear_pct" ]   == 55.0
    # fired 300s ago, deadline = fired + 60 + 120 = NOW-120 → past → DEAD (no wake proof).
    assert samples[ 0 ][ "verdict" ] == "DEAD_NO_RETURN"


def test_collect_unreachable_pressure_post_pct_none( tmp_path ):
    _write_marker( tmp_path, _marker( sid="s1" ) )
    samples = collect_respin_samples( base_dir=str( tmp_path ), now=NOW,
                                      fetch_pressure=lambda: { "personas": None } )
    assert len( samples ) == 1
    assert samples[ 0 ][ "post_settle_pct" ] is None


# ── append_respin_samples ────────────────────────────────────────────────────

def _sample( seq=0 ):
    s = build_respin_sample( _marker( sid=f"s{seq}" ),
                             { "consumption_pct_of_window": float( seq ) }, _assessment(), NOW )
    s[ "seq" ] = seq
    return s


def test_append_empty_returns_zero_no_file( tmp_path ):
    assert append_respin_samples( [], base_dir=str( tmp_path ) ) == 0
    assert not ( tmp_path / RESPIN_SAMPLES_FILENAME ).exists()


def test_append_writes_schema_versioned_lines( tmp_path ):
    n = append_respin_samples( [ _sample( 0 ), _sample( 1 ) ], base_dir=str( tmp_path ) )
    assert n == 2
    lines = ( tmp_path / RESPIN_SAMPLES_FILENAME ).read_text().splitlines()
    assert len( lines ) == 2
    assert json.loads( lines[ 0 ] )[ "schema_version" ] == RESPIN_SAMPLE_SCHEMA_VERSION


def test_append_accumulates( tmp_path ):
    append_respin_samples( [ _sample( 0 ) ], base_dir=str( tmp_path ) )
    append_respin_samples( [ _sample( 1 ) ], base_dir=str( tmp_path ) )
    assert len( ( tmp_path / RESPIN_SAMPLES_FILENAME ).read_text().splitlines() ) == 2


def test_append_serialization_error_writes_nothing( tmp_path ):
    class Bad: pass
    assert append_respin_samples( [ { "x": Bad() } ], base_dir=str( tmp_path ) ) == 0
    assert not ( tmp_path / RESPIN_SAMPLES_FILENAME ).exists()


def test_append_oserror_returns_partial( tmp_path ):
    # Make the target path a directory so open(path, "a") raises IsADirectoryError.
    ( tmp_path / RESPIN_SAMPLES_FILENAME ).mkdir()
    assert append_respin_samples( [ _sample( 0 ) ], base_dir=str( tmp_path ) ) == 0


def test_rotation_bounds_file_and_drops_oldest( tmp_path, monkeypatch ):
    # Cheech's required test: write past the cap and prove the bound holds AND the
    # oldest samples are the ones dropped.
    monkeypatch.setattr( obs, "RESPIN_SAMPLES_MAX_BYTES", 600 )
    last = 60
    for seq in range( last + 1 ):
        append_respin_samples( [ _sample( seq ) ], base_dir=str( tmp_path ) )

    cur  = tmp_path / RESPIN_SAMPLES_FILENAME
    dot1 = tmp_path / ( RESPIN_SAMPLES_FILENAME + ".1" )
    total = ( cur.stat().st_size if cur.exists() else 0 ) + ( dot1.stat().st_size if dot1.exists() else 0 )
    assert total < 2 * 600                    # bounded UNDER 2× the cap

    present = []
    for f in ( cur, dot1 ):
        if f.exists():
            present += [ json.loads( line )[ "seq" ] for line in f.read_text().splitlines() ]
    assert present
    assert max( present ) == last             # newest kept
    assert min( present ) > 0                 # oldest dropped


# ── SelfRespinObserverLoop.record_once — must break NOTHING ───────────────────

def test_record_once_disabled_no_io( tmp_path ):
    loop = SelfRespinObserverLoop( FakeConfig( False ), base_dir=str( tmp_path ),
                                   fetch_pressure_fn=lambda: { "personas": {} }, now_fn=lambda: NOW )
    assert loop.record_once() == { "enabled": False, "recorded": 0 }
    assert not ( tmp_path / RESPIN_SAMPLES_FILENAME ).exists()


def test_record_once_enabled_records( tmp_path ):
    _write_marker( tmp_path, _marker( sid="s1" ) )
    fetch = lambda: { "personas": { "krishna": {
        "session_id": "s1", "tmux_session": "cc-x",
        "consumption_pct_of_window": 19.6, "status": "within_budget", "last_turn_age_s": 5 } } }
    loop = SelfRespinObserverLoop( FakeConfig( True ), base_dir=str( tmp_path ),
                                   fetch_pressure_fn=fetch, now_fn=lambda: NOW )
    assert loop.record_once() == { "enabled": True, "recorded": 1 }
    assert ( tmp_path / RESPIN_SAMPLES_FILENAME ).exists()


def test_record_once_collect_raise_does_not_propagate( tmp_path, monkeypatch ):
    loop = SelfRespinObserverLoop( FakeConfig( True ), base_dir=str( tmp_path ),
                                   fetch_pressure_fn=lambda: { "personas": {} }, now_fn=lambda: NOW )
    def boom( *a, **k ): raise RuntimeError( "boom" )
    monkeypatch.setattr( obs, "collect_respin_samples", boom )
    assert loop.record_once() == { "enabled": True, "recorded": 0 }


def test_record_once_append_raise_does_not_break_the_tick( tmp_path, monkeypatch ):
    # Cheech's requirement: a throwing sampler must NOT propagate. Make append
    # raise and assert record_once still returns cleanly — a lost data point is
    # free, a lost tick is not.
    _write_marker( tmp_path, _marker( sid="s1" ) )
    loop = SelfRespinObserverLoop( FakeConfig( True ), base_dir=str( tmp_path ),
                                   fetch_pressure_fn=lambda: { "personas": {} }, now_fn=lambda: NOW )
    def boom( *a, **k ): raise RuntimeError( "disk exploded" )
    monkeypatch.setattr( obs, "append_respin_samples", boom )
    assert loop.record_once() == { "enabled": True, "recorded": 0 }
