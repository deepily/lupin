#!/usr/bin/env python3
"""
Unit tests for the Heartbeat Hook hold-artifact module.

Target: 100% line + branch + function coverage of
    src/lupin_cli/claude_code/hooks/lib/heartbeat_hold.py

Design authority: planning-is-prompting →
    src/rnd/2026.06.02-stop-hook-natural-heartbeat-poker.md §0 decision #7.
All tests inject `base_dir` (tmp_path) or `now` so they are hermetic and
never touch the real project root.
"""
import json
import datetime

import pytest

from lupin_cli.claude_code.hooks.lib import heartbeat_hold as hh


UTC = datetime.timezone.utc


# ── hold_path / _resolve_base_dir ─────────────────────────────────────────────

def test_hold_path_with_base_dir( tmp_path ):
    p = hh.hold_path( "abc12345", base_dir=tmp_path )
    assert p == tmp_path / ".heartbeat-hold-abc12345.json"


def test_hold_path_empty_session_collapses_to_unknown( tmp_path ):
    p = hh.hold_path( "", base_dir=tmp_path )
    assert p == tmp_path / ".heartbeat-hold-unknown.json"


def test_hold_path_default_base_dir_uses_project_root( monkeypatch, tmp_path ):
    import cosa.utils.util as cu
    monkeypatch.setattr( cu, "get_project_root", lambda: str( tmp_path ) )
    p = hh.hold_path( "abc12345" )
    assert p == tmp_path / ".heartbeat-hold-abc12345.json"


# ── _now ──────────────────────────────────────────────────────────────────────

def test_now_is_timezone_aware_utc():
    now = hh._now()
    assert now.tzinfo is not None
    assert now.utcoffset() == datetime.timedelta( 0 )


# ── _parse_iso ────────────────────────────────────────────────────────────────

def test_parse_iso_none_and_non_string():
    assert hh._parse_iso( None ) is None
    assert hh._parse_iso( "" ) is None
    assert hh._parse_iso( 12345 ) is None


def test_parse_iso_zulu_suffix_normalized():
    dt = hh._parse_iso( "2026-06-04T12:00:00Z" )
    assert dt == datetime.datetime( 2026, 6, 4, 12, 0, 0, tzinfo=UTC )


def test_parse_iso_unparseable_returns_none():
    assert hh._parse_iso( "not-a-timestamp" ) is None


def test_parse_iso_naive_assumed_utc():
    dt = hh._parse_iso( "2026-06-04T12:00:00" )
    assert dt.tzinfo is not None
    assert dt == datetime.datetime( 2026, 6, 4, 12, 0, 0, tzinfo=UTC )


def test_parse_iso_aware_offset_preserved():
    dt = hh._parse_iso( "2026-06-04T12:00:00+05:00" )
    assert dt.utcoffset() == datetime.timedelta( hours=5 )


# ── write_hold ────────────────────────────────────────────────────────────────

def test_write_hold_default_held_at_and_schema_order( tmp_path ):
    hold = hh.write_hold( "sid1", "María 🌸", "holding on seam review",
                          work_owed=True, ttl_seconds=900, awaiting="peer:Rachel",
                          base_dir=tmp_path )
    # Returned dict holds EXACTLY the 7 schema fields, in order
    assert tuple( hold.keys() ) == hh.HOLD_SCHEMA_FIELDS
    assert hold[ "held_at" ]                                            # auto-stamped
    assert hold[ "session_id" ] == "sid1"
    assert hold[ "awaiting" ]   == "peer:Rachel"

    # File written, parses back to the same dict, no leftover temp file
    path = tmp_path / ".heartbeat-hold-sid1.json"
    assert path.exists()
    assert json.loads( path.read_text() ) == hold
    assert not ( tmp_path / ".heartbeat-hold-sid1.json.tmp" ).exists()


def test_write_hold_explicit_held_at_and_defaults( tmp_path ):
    hold = hh.write_hold( "sid2", "Tiffany 💍", "done",
                          work_owed=False, held_at="2026-06-04T00:00:00Z",
                          base_dir=tmp_path )
    assert hold[ "held_at" ]     == "2026-06-04T00:00:00Z"
    assert hold[ "work_owed" ]   is False
    assert hold[ "ttl_seconds" ] == hh.DEFAULT_TTL_SECONDS
    assert hold[ "awaiting" ]    == hh.AWAITING_NONE


def test_write_hold_raises_on_missing_directory( tmp_path ):
    with pytest.raises( OSError ):
        hh.write_hold( "sid3", "P", "r", base_dir=tmp_path / "does_not_exist" )


# ── read_hold ─────────────────────────────────────────────────────────────────

def test_read_hold_absent_returns_none( tmp_path ):
    assert hh.read_hold( "nope", base_dir=tmp_path ) is None


def test_read_hold_roundtrip( tmp_path ):
    written = hh.write_hold( "sid4", "P", "r", base_dir=tmp_path )
    assert hh.read_hold( "sid4", base_dir=tmp_path ) == written


def test_read_hold_corrupt_json_returns_none( tmp_path ):
    ( tmp_path / ".heartbeat-hold-bad.json" ).write_text( "{not valid json" )
    assert hh.read_hold( "bad", base_dir=tmp_path ) is None


def test_read_hold_non_object_json_returns_none( tmp_path ):
    ( tmp_path / ".heartbeat-hold-list.json" ).write_text( "[1, 2, 3]" )
    assert hh.read_hold( "list", base_dir=tmp_path ) is None


def test_read_hold_oserror_returns_none( tmp_path ):
    # Path exists but is a directory → read_text raises IsADirectoryError (OSError)
    ( tmp_path / ".heartbeat-hold-dir.json" ).mkdir()
    assert hh.read_hold( "dir", base_dir=tmp_path ) is None


# ── clear_hold ────────────────────────────────────────────────────────────────

def test_clear_hold_removes_file( tmp_path ):
    hh.write_hold( "sid5", "P", "r", base_dir=tmp_path )
    hh.clear_hold( "sid5", base_dir=tmp_path )
    assert not ( tmp_path / ".heartbeat-hold-sid5.json" ).exists()


def test_clear_hold_absent_is_noop( tmp_path ):
    hh.clear_hold( "ghost", base_dir=tmp_path )   # must not raise


def test_clear_hold_oserror_swallowed( tmp_path ):
    # Path is a directory → unlink raises OSError, must be swallowed
    ( tmp_path / ".heartbeat-hold-cdir.json" ).mkdir()
    hh.clear_hold( "cdir", base_dir=tmp_path )     # must not raise


# ── is_fresh ──────────────────────────────────────────────────────────────────

def _hold( held_at, ttl_seconds=900, reason="r", work_owed=True ):
    return {
        "session_id"  : "s",
        "persona"     : "P",
        "held_at"     : held_at,
        "ttl_seconds" : ttl_seconds,
        "work_owed"   : work_owed,
        "reason"      : reason,
        "awaiting"    : "none",
    }


def test_is_fresh_missing_hold():
    assert hh.is_fresh( None ) is False
    assert hh.is_fresh( {} ) is False


def test_is_fresh_bad_held_at():
    assert hh.is_fresh( _hold( "garbage" ) ) is False


def test_is_fresh_non_numeric_ttl():
    assert hh.is_fresh( _hold( "2026-06-04T12:00:00Z", ttl_seconds="900" ) ) is False


def test_is_fresh_bool_ttl_rejected():
    # bool is a subclass of int — must be explicitly rejected
    assert hh.is_fresh( _hold( "2026-06-04T12:00:00Z", ttl_seconds=True ) ) is False


def test_is_fresh_within_window():
    now      = datetime.datetime( 2026, 6, 4, 12, 0, 0, tzinfo=UTC )
    held_at  = ( now - datetime.timedelta( seconds=100 ) ).isoformat()
    assert hh.is_fresh( _hold( held_at, ttl_seconds=900 ), now=now ) is True


def test_is_fresh_expired():
    now      = datetime.datetime( 2026, 6, 4, 12, 0, 0, tzinfo=UTC )
    held_at  = ( now - datetime.timedelta( seconds=1000 ) ).isoformat()
    assert hh.is_fresh( _hold( held_at, ttl_seconds=900 ), now=now ) is False


def test_is_fresh_default_now_branch( tmp_path ):
    # now=None path: a just-written hold is fresh against the real clock
    hold = hh.write_hold( "sidnow", "P", "r", ttl_seconds=900, base_dir=tmp_path )
    assert hh.is_fresh( hold ) is True


# ── is_honored ────────────────────────────────────────────────────────────────

def test_is_honored_not_fresh():
    assert hh.is_honored( _hold( "garbage" ) ) is False


def test_is_honored_fresh_but_empty_reason():
    now     = datetime.datetime( 2026, 6, 4, 12, 0, 0, tzinfo=UTC )
    held_at = now.isoformat()
    assert hh.is_honored( _hold( held_at, reason="" ), now=now ) is False


def test_is_honored_fresh_but_whitespace_reason():
    now     = datetime.datetime( 2026, 6, 4, 12, 0, 0, tzinfo=UTC )
    held_at = now.isoformat()
    assert hh.is_honored( _hold( held_at, reason="   " ), now=now ) is False


def test_is_honored_fresh_with_reason():
    now     = datetime.datetime( 2026, 6, 4, 12, 0, 0, tzinfo=UTC )
    held_at = now.isoformat()
    assert hh.is_honored( _hold( held_at, reason="holding on Tiberius" ), now=now ) is True


# ── declared_work_owed ────────────────────────────────────────────────────────

def test_declared_work_owed_no_hold():
    assert hh.declared_work_owed( None ) is None
    assert hh.declared_work_owed( {} ) is None


def test_declared_work_owed_true_and_false():
    assert hh.declared_work_owed( _hold( "x", work_owed=True ) ) is True
    assert hh.declared_work_owed( _hold( "x", work_owed=False ) ) is False


def test_declared_work_owed_non_bool_returns_none():
    hold = _hold( "x" )
    hold[ "work_owed" ] = "yes"
    assert hh.declared_work_owed( hold ) is None


# ── quick_smoke_test ──────────────────────────────────────────────────────────

def test_quick_smoke_test_passes():
    assert hh.quick_smoke_test() is True
