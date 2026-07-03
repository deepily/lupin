#!/usr/bin/env python3
"""
Unit tests for the Heartbeat-Arbiter fleet event glob/tail (events_tail.py).

Covers tail_session_file (byte-offset incremental tail, partial-line safety,
rotation/truncation reset, missing/unreadable file, malformed/non-dict/blank
line skip) and tail_fleet_events (multi-session glob, offset carry-forward,
new-records-only output, missing dir, glob error). Hermetic — tmp JSONL files.

Venue: :7999-eligible / local — pure-ish I/O, tmp-dir only, sub-second.
"""
import json
import os
import sys

import pytest

# Bootstrap
_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from cosa.agents.heartbeat_arbiter import events_tail as et


def _rec( n, sid="s1", outcome="idle" ):
    return json.dumps( { "schema_version": 1, "session_id": sid, "outcome": outcome, "n": n } )


def _write( path, *lines, trailing_newline=True ):
    text = "\n".join( lines )
    if trailing_newline and lines:
        text += "\n"
    path.write_text( text )
    return path


# ── _session_id_from_path ─────────────────────────────────────────────────────

def test_session_id_from_path():
    assert et._session_id_from_path( "/a/b/abc123.jsonl" ) == "abc123"


# ── tail_session_file ─────────────────────────────────────────────────────────

def test_tail_from_zero_returns_complete_records( tmp_path ):
    p = _write( tmp_path / "s1.jsonl", _rec( 1 ), _rec( 2 ) )
    recs, off = et.tail_session_file( str( p ) )
    assert [ r[ "n" ] for r in recs ] == [ 1, 2 ]
    assert off == os.path.getsize( p )


def test_partial_trailing_line_not_consumed( tmp_path ):
    p = tmp_path / "s1.jsonl"
    p.write_text( _rec( 1 ) + "\n" + '{"partial":' )   # no closing newline
    recs, off = et.tail_session_file( str( p ) )
    assert [ r[ "n" ] for r in recs ] == [ 1 ]
    # offset stops at the last complete newline, leaving the partial for next time
    assert off == len( _rec( 1 ) ) + 1


def test_incremental_tail_second_poll( tmp_path ):
    p = _write( tmp_path / "s1.jsonl", _rec( 1 ), _rec( 2 ) )
    recs1, off1 = et.tail_session_file( str( p ) )
    # append more
    with open( p, "a" ) as f:
        f.write( _rec( 3 ) + "\n" + _rec( 4 ) + "\n" )
    recs2, off2 = et.tail_session_file( str( p ), offset=off1 )
    assert [ r[ "n" ] for r in recs2 ] == [ 3, 4 ]
    assert off2 == os.path.getsize( p )


def test_nothing_new_when_offset_at_end( tmp_path ):
    p = _write( tmp_path / "s1.jsonl", _rec( 1 ) )
    size = os.path.getsize( p )
    recs, off = et.tail_session_file( str( p ), offset=size )
    assert recs == [ ] and off == size


def test_rotation_resets_to_zero( tmp_path ):
    p = _write( tmp_path / "s1.jsonl", _rec( 1 ), _rec( 2 ), _rec( 3 ) )
    _, off = et.tail_session_file( str( p ) )
    # file shrinks (rotated/recreated) below the tracked offset
    _write( p, _rec( 9 ) )
    recs, off2 = et.tail_session_file( str( p ), offset=off )
    assert [ r[ "n" ] for r in recs ] == [ 9 ]
    assert off2 == os.path.getsize( p )


def test_no_complete_line_yet( tmp_path ):
    p = tmp_path / "s1.jsonl"
    p.write_text( '{"partial":' )       # no newline at all
    recs, off = et.tail_session_file( str( p ) )
    assert recs == [ ] and off == 0


def test_skips_blank_malformed_and_nondict( tmp_path ):
    p = tmp_path / "s1.jsonl"
    p.write_text( "\n".join( [
        _rec( 1 ),
        "   ",            # blank
        "{not json",      # malformed
        "[1,2,3]",        # non-dict JSON
        '"a string"',     # non-dict JSON
        _rec( 2 ),
    ] ) + "\n" )
    recs, _ = et.tail_session_file( str( p ) )
    assert [ r[ "n" ] for r in recs ] == [ 1, 2 ]


def test_missing_file_returns_offset_unchanged( tmp_path ):
    recs, off = et.tail_session_file( str( tmp_path / "nope.jsonl" ), offset=42 )
    assert recs == [ ] and off == 42


def test_open_oserror_returns_offset( tmp_path, monkeypatch ):
    p = _write( tmp_path / "s1.jsonl", _rec( 1 ) )

    real_open = open
    def boom( path, *a, **k ):
        if str( path ).endswith( "s1.jsonl" ) and "b" in ( a[ 0 ] if a else k.get( "mode", "" ) ):
            raise OSError( "vanished" )
        return real_open( path, *a, **k )

    monkeypatch.setattr( "builtins.open", boom )
    recs, off = et.tail_session_file( str( p ), offset=0 )
    assert recs == [ ] and off == 0


# ── tail_fleet_events ─────────────────────────────────────────────────────────

def test_fleet_globs_multiple_sessions( tmp_path ):
    _write( tmp_path / "s1.jsonl", _rec( 1, "s1" ) )
    _write( tmp_path / "s2.jsonl", _rec( 1, "s2" ), _rec( 2, "s2" ) )
    ev, offs = et.tail_fleet_events( events_dir=str( tmp_path ) )
    assert set( ev.keys() ) == { "s1", "s2" }
    assert [ r[ "n" ] for r in ev[ "s2" ] ] == [ 1, 2 ]
    assert set( offs.keys() ) == { "s1", "s2" }


def test_fleet_only_returns_sessions_with_new_records( tmp_path ):
    _write( tmp_path / "s1.jsonl", _rec( 1, "s1" ) )
    ev, offs = et.tail_fleet_events( events_dir=str( tmp_path ) )
    # second poll, no changes → s1 absent from events, but offset carried
    ev2, offs2 = et.tail_fleet_events( events_dir=str( tmp_path ), offsets=offs )
    assert ev2 == { }
    assert offs2[ "s1" ] == offs[ "s1" ]


def test_fleet_offsets_carry_forward( tmp_path ):
    p = _write( tmp_path / "s1.jsonl", _rec( 1, "s1" ) )
    ev, offs = et.tail_fleet_events( events_dir=str( tmp_path ) )
    with open( p, "a" ) as f:
        f.write( _rec( 2, "s1" ) + "\n" )
    ev2, offs2 = et.tail_fleet_events( events_dir=str( tmp_path ), offsets=offs )
    assert [ r[ "n" ] for r in ev2[ "s1" ] ] == [ 2 ]


def test_fleet_missing_dir( tmp_path ):
    ev, offs = et.tail_fleet_events( events_dir=str( tmp_path / "gone" ) )
    assert ev == { } and offs == { }


def test_fleet_glob_error_returns_prior_offsets( tmp_path, monkeypatch ):
    monkeypatch.setattr( et.glob, "glob", lambda *a, **k: ( _ for _ in () ).throw( OSError( "glob boom" ) ) )
    prior = { "s1": 10 }
    ev, offs = et.tail_fleet_events( events_dir=str( tmp_path ), offsets=prior )
    assert ev == { } and offs == prior


def test_fleet_default_dir_is_fleet_events_dir( tmp_path, monkeypatch ):
    # events_dir=None → uses heartbeat_events.FLEET_EVENTS_DIR. The unit conftest
    # already redirects that to a tmp dir, so this is hermetic + asserts the
    # None-branch path executes without touching the real ~/.claude.
    ev, offs = et.tail_fleet_events( events_dir=None )
    assert isinstance( ev, dict ) and isinstance( offs, dict )


# ── 5a1f17f8 (b): durable offsets across restarts ─────────────────────────────
# Root cause of the STUCK-poke replay: the arbiter holds byte offsets in memory
# (self._offsets), so a :8001 restart re-reads every events file from byte 0 and
# re-consumes historical cap_reached as fresh. save_offsets/load_offsets persist the
# per-session offset map so a bounce resumes where it left off (no replay). Both are
# swallow-safe I/O (never raise) — an offset-store hiccup degrades to today's
# in-memory behavior, never crashes the poll loop.

def test_offsets_save_then_load_roundtrip( tmp_path ):
    path = tmp_path / "offsets.json"
    offs = { "s1": 42, "s2-full-uuid": 1024 }
    assert et.save_offsets( path, offs ) is True
    assert et.load_offsets( path ) == offs


def test_offsets_load_missing_returns_empty( tmp_path ):
    assert et.load_offsets( tmp_path / "nope.json" ) == { }


def test_offsets_load_corrupt_returns_empty( tmp_path ):
    path = tmp_path / "offsets.json"
    path.write_text( "{not valid json" )
    assert et.load_offsets( path ) == { }


def test_offsets_load_non_dict_returns_empty( tmp_path ):
    path = tmp_path / "offsets.json"
    path.write_text( "[1, 2, 3]" )                               # valid JSON, wrong shape
    assert et.load_offsets( path ) == { }


def test_offsets_save_overwrites_atomically( tmp_path ):
    path = tmp_path / "offsets.json"
    et.save_offsets( path, { "s1": 1 } )
    et.save_offsets( path, { "s1": 2, "s2": 9 } )               # latest wins, no temp residue
    assert et.load_offsets( path ) == { "s1": 2, "s2": 9 }
    assert not ( tmp_path / "offsets.json.tmp" ).exists()


def test_offsets_save_swallows_unwritable( tmp_path ):
    # target path is a DIRECTORY → write raises → save swallows → False, never raises
    d = tmp_path / "adir"
    d.mkdir()
    assert et.save_offsets( d, { "s1": 1 } ) is False


def test_offsets_load_swallows_unreadable( tmp_path ):
    # path is a DIRECTORY → read raises → load swallows → {} (fail-safe = in-memory start)
    d = tmp_path / "adir"
    d.mkdir()
    assert et.load_offsets( d ) == { }


# ── smoke ─────────────────────────────────────────────────────────────────────

def test_quick_smoke_test_passes():
    assert et.quick_smoke_test() is True
