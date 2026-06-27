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


def _persisted( hold ):
    """A read_hold result minus the in-memory `_`-prefixed annotations (B1 mtime
    stamp). write_hold returns ONLY the persisted schema fields, so comparing a
    read result against a write return must drop the read-time annotation."""
    return { k: v for k, v in hold.items() if not k.startswith( "_" ) }


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
    assert _persisted( hh.read_hold( "sid4", base_dir=tmp_path ) ) == written


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


# ── prune_stale_hold_files — bug b39562e4 pt2 (janitor seam) ──────────────────

_PRUNE_NOW = datetime.datetime( 2026, 6, 23, 12, 0, 0, tzinfo=UTC )


def _hold_file( base, sid, age_seconds, ttl=900, **extra ):
    """Write a hold file for `sid` whose held_at is `age_seconds` before _PRUNE_NOW."""
    held_at = ( _PRUNE_NOW - datetime.timedelta( seconds=age_seconds ) ).isoformat()
    d = { "session_id": sid, "held_at": held_at, "ttl_seconds": ttl,
          "work_owed": True, "reason": "x" }
    d.update( extra )
    ( base / f".heartbeat-hold-{sid}.json" ).write_text( json.dumps( d ) )


def test_prune_reaps_only_ancient_keeps_fresh_and_within_grace( tmp_path ):
    # ancient: expired > ttl + 6h grace → REAP ; fresh: now → KEEP ;
    # within-grace: expired but inside grace window → KEEP
    _hold_file( tmp_path, "ancient", age_seconds=900 + 21600 + 100 )
    _hold_file( tmp_path, "fresh",   age_seconds=0 )
    _hold_file( tmp_path, "recent",  age_seconds=900 + 60 )   # expired 1m ago, < grace
    pruned = hh.prune_stale_hold_files( base_dir=tmp_path, now=_PRUNE_NOW )
    assert pruned == [ str( tmp_path / ".heartbeat-hold-ancient.json" ) ]
    assert     ( tmp_path / ".heartbeat-hold-fresh.json"  ).exists()
    assert     ( tmp_path / ".heartbeat-hold-recent.json" ).exists()
    assert not ( tmp_path / ".heartbeat-hold-ancient.json" ).exists()


def test_prune_never_reaps_a_live_session_even_if_ancient( tmp_path ):
    _hold_file( tmp_path, "livesid", age_seconds=900 + 21600 + 999 )
    pruned = hh.prune_stale_hold_files( base_dir=tmp_path, now=_PRUNE_NOW,
                                        live_session_ids=[ "livesid" ] )
    assert pruned == [ ]
    assert ( tmp_path / ".heartbeat-hold-livesid.json" ).exists()


def test_prune_authoritative_set_dead_session_reaped_at_ttl_within_grace( tmp_path ):
    """Ping-storm Fix 1 belt-and-suspenders: with an AUTHORITATIVE live-set, a hold
    whose session is ABSENT from it (provably dead) and EXPIRED past its own TTL — but
    still WITHIN the +6h grace — is pruned SOONER (at TTL). Without the live-set this
    same hold is KEPT (the conservative branch)."""
    _hold_file( tmp_path, "deadsid", age_seconds=900 + 60 )           # expired 1m past TTL, < grace
    # conservative (no authoritative set) → KEPT
    assert hh.prune_stale_hold_files( base_dir=tmp_path, now=_PRUNE_NOW ) == [ ]
    assert ( tmp_path / ".heartbeat-hold-deadsid.json" ).exists()
    # authoritative set NOT containing deadsid → positive-dead → pruned at TTL
    pruned = hh.prune_stale_hold_files( base_dir=tmp_path, now=_PRUNE_NOW,
                                        live_session_ids=[ "someone-else" ] )
    assert pruned == [ str( tmp_path / ".heartbeat-hold-deadsid.json" ) ]
    assert not ( tmp_path / ".heartbeat-hold-deadsid.json" ).exists()


def test_prune_authoritative_set_dead_session_not_yet_expired_is_kept( tmp_path ):
    """Positive-dead but NOT yet past its own TTL → KEPT (a dead session's hold is
    only reclaimed once its TTL has actually elapsed — never before)."""
    _hold_file( tmp_path, "deadsid", age_seconds=300 )                # ttl 900 → not expired
    pruned = hh.prune_stale_hold_files( base_dir=tmp_path, now=_PRUNE_NOW,
                                        live_session_ids=[ "someone-else" ] )
    assert pruned == [ ]
    assert ( tmp_path / ".heartbeat-hold-deadsid.json" ).exists()


def test_prune_authoritative_set_no_session_id_stays_conservative( tmp_path ):
    """Bias-to-keep: even WITH an authoritative live-set, a hold with NO session_id
    can't yield a positive-dead reading → conservative TTL+grace. Expired-within-grace
    → KEPT."""
    ( tmp_path / ".heartbeat-hold-nosid.json" ).write_text( json.dumps(
        { "held_at": ( _PRUNE_NOW - datetime.timedelta( seconds=900 + 60 ) ).isoformat(),
          "ttl_seconds": 900, "work_owed": True, "reason": "x" } ) )   # no session_id key
    pruned = hh.prune_stale_hold_files( base_dir=tmp_path, now=_PRUNE_NOW,
                                        live_session_ids=[ "someone-else" ] )
    assert pruned == [ ]
    assert ( tmp_path / ".heartbeat-hold-nosid.json" ).exists()


def test_prune_authoritative_set_still_reaps_ancient_dead_session( tmp_path ):
    """No regression: an ancient (past TTL+grace) dead session is still reaped with an
    authoritative set (the TTL threshold is ≤ the old TTL+grace, so ancient still goes)."""
    _hold_file( tmp_path, "ancientdead", age_seconds=900 + 21600 + 100 )
    pruned = hh.prune_stale_hold_files( base_dir=tmp_path, now=_PRUNE_NOW,
                                        live_session_ids=[ "someone-else" ] )
    assert pruned == [ str( tmp_path / ".heartbeat-hold-ancientdead.json" ) ]


def test_prune_keeps_unprovable_files( tmp_path ):
    # garbage JSON / non-dict / missing held_at / non-numeric ttl / bool ttl → all KEPT
    ( tmp_path / ".heartbeat-hold-garbage.json" ).write_text( "{not json" )
    ( tmp_path / ".heartbeat-hold-list.json"    ).write_text( "[]" )
    _hold_file( tmp_path, "noheld",  age_seconds=999999 ); \
        ( tmp_path / ".heartbeat-hold-noheld.json" ).write_text( json.dumps(
            { "session_id": "noheld", "ttl_seconds": 900, "reason": "x" } ) )
    _hold_file( tmp_path, "strttl",  age_seconds=999999, ttl="nope" )
    _hold_file( tmp_path, "boolttl", age_seconds=999999, ttl=True )
    pruned = hh.prune_stale_hold_files( base_dir=tmp_path, now=_PRUNE_NOW )
    assert pruned == [ ]
    for sid in ( "garbage", "list", "noheld", "strttl", "boolttl" ):
        assert ( tmp_path / f".heartbeat-hold-{sid}.json" ).exists()


def test_prune_defaults_now_and_no_files( tmp_path ):
    # empty dir → [] ; also exercises the now=None default path
    assert hh.prune_stale_hold_files( base_dir=tmp_path ) == [ ]


def test_prune_glob_oserror_returns_empty( monkeypatch ):
    class _BadBase:
        def glob( self, pattern ):
            raise OSError( "boom" )
    monkeypatch.setattr( hh, "_resolve_base_dir", lambda b: _BadBase() )
    assert hh.prune_stale_hold_files( base_dir="anything", now=_PRUNE_NOW ) == [ ]


def test_prune_unlink_oserror_is_skipped( tmp_path, monkeypatch ):
    import pathlib
    _hold_file( tmp_path, "ancient", age_seconds=900 + 21600 + 100 )
    def _boom( self, *a, **k ):
        raise OSError( "unlink denied" )
    monkeypatch.setattr( pathlib.Path, "unlink", _boom )
    pruned = hh.prune_stale_hold_files( base_dir=tmp_path, now=_PRUNE_NOW )
    assert pruned == [ ]                                   # unlink failed → not reported pruned


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


# ── B1 mtime-anchored freshness (bug d44b7068) ────────────────────────────────
#
# Freshness is measured from the hold FILE's host-real mtime (the annotation the
# reader stamps), NOT the agent-supplied held_at — agents have no reliable clock,
# so an old/anchored held_at must NOT make a freshly-written hold read stale.

def _hold_mtime( mtime_epoch, ttl_seconds=900, held_at="garbage", reason="r" ):
    """A hold dict carrying the B1 mtime annotation (held_at deliberately bad by
    default, to prove the mtime anchor wins over the agent's clock)."""
    h = _hold( held_at, ttl_seconds=ttl_seconds, reason=reason )
    h[ hh.HOLD_MTIME_ANNOTATION ] = mtime_epoch
    return h


def test_file_mtime_success( tmp_path ):
    p = tmp_path / "f.json"
    p.write_text( "{}" )
    assert hh._file_mtime( p ) == p.stat().st_mtime


def test_file_mtime_oserror_returns_none( tmp_path ):
    # A non-existent path → stat raises OSError → None (the degrade-safe branch).
    assert hh._file_mtime( tmp_path / "does-not-exist.json" ) is None


def test_read_hold_stamps_mtime_annotation( tmp_path ):
    hh.write_hold( "sidm", "P", "r", base_dir=tmp_path )
    hold = hh.read_hold( "sidm", base_dir=tmp_path )
    path = tmp_path / ".heartbeat-hold-sidm.json"
    assert hold[ hh.HOLD_MTIME_ANNOTATION ] == path.stat().st_mtime


def test_read_hold_omits_annotation_when_mtime_unavailable( tmp_path, monkeypatch ):
    # _file_mtime returns None (stat failure) → annotation absent → legacy path.
    hh.write_hold( "sidm2", "P", "r", base_dir=tmp_path )
    monkeypatch.setattr( hh, "_file_mtime", lambda p: None )
    hold = hh.read_hold( "sidm2", base_dir=tmp_path )
    assert hold is not None
    assert hh.HOLD_MTIME_ANNOTATION not in hold


def test_is_fresh_mtime_overrides_bad_held_at():
    # The core B1 repro: held_at is garbage, but a fresh file mtime → FRESH.
    now = datetime.datetime( 2026, 6, 4, 12, 0, 0, tzinfo=UTC )
    assert hh.is_fresh( _hold_mtime( now.timestamp() - 100, ttl_seconds=900 ), now=now ) is True


def test_is_fresh_mtime_expired():
    now = datetime.datetime( 2026, 6, 4, 12, 0, 0, tzinfo=UTC )
    assert hh.is_fresh( _hold_mtime( now.timestamp() - 1000, ttl_seconds=900 ), now=now ) is False


def test_is_fresh_mtime_boundary_excludes_equal():
    # elapsed == ttl is NOT fresh (strict <), mirroring the held_at rule.
    now = datetime.datetime( 2026, 6, 4, 12, 0, 0, tzinfo=UTC )
    assert hh.is_fresh( _hold_mtime( now.timestamp() - 900, ttl_seconds=900 ), now=now ) is False


def test_is_fresh_mtime_bool_falls_back_to_held_at():
    # A bool annotation must NOT read as 1.0 — fall back to held_at.
    now   = datetime.datetime( 2026, 6, 4, 12, 0, 0, tzinfo=UTC )
    fresh = _hold_mtime( True, held_at=now.isoformat() )            # bool mtime, fresh held_at
    stale = _hold_mtime( True, held_at="garbage" )                  # bool mtime, bad held_at
    assert hh.is_fresh( fresh, now=now ) is True
    assert hh.is_fresh( stale, now=now ) is False


def test_is_fresh_mtime_non_numeric_falls_back_to_held_at():
    now = datetime.datetime( 2026, 6, 4, 12, 0, 0, tzinfo=UTC )
    h   = _hold_mtime( "not-a-number", held_at=now.isoformat() )
    assert hh.is_fresh( h, now=now ) is True


def test_is_fresh_mtime_present_but_ttl_bad_rejected():
    # ttl validation precedes the mtime path — a bad ttl is False regardless.
    now = datetime.datetime( 2026, 6, 4, 12, 0, 0, tzinfo=UTC )
    assert hh.is_fresh( _hold_mtime( now.timestamp(), ttl_seconds=True ), now=now ) is False


def test_is_honored_uses_mtime_anchor( tmp_path ):
    # End-to-end: a hold whose held_at is ancient but file just written is honored;
    # backdating the file mtime past the ttl flips it to not-honored.
    hh.write_hold( "sidh", "P", "holding on peer",
                   held_at="2000-01-01T00:00:00Z", ttl_seconds=900, base_dir=tmp_path )
    assert hh.is_honored( hh.read_hold( "sidh", base_dir=tmp_path ) ) is True
    import os
    path      = tmp_path / ".heartbeat-hold-sidh.json"
    old_epoch = ( hh._now() - datetime.timedelta( seconds=10_000 ) ).timestamp()
    os.utime( path, ( old_epoch, old_epoch ) )
    assert hh.is_honored( hh.read_hold( "sidh", base_dir=tmp_path ) ) is False


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


# ── _read_hold_path — c121037b facet 2 (short/full id-form fallback) ──────────
#
# An agent told to "write .heartbeat-hold-<session_id>.json" may use the SHORT
# 8-char id (get_session_info hands it that form) while the Stop hook reads with
# the FULL stable id. Without the fallback the hold is silently ignored and the
# session is poked forever despite having declared a hold.

_FULL  = "f6292818-1e6d-4a90-8079-37fea46b6db2"
_SHORT = "f6292818"


def test_read_hold_exact_match_takes_precedence( tmp_path ):
    written = hh.write_hold( _FULL, "P", "exact wins", base_dir=tmp_path )
    assert _persisted( hh.read_hold( _FULL, base_dir=tmp_path ) ) == written   # exact path, no glob


def test_read_hold_full_id_finds_hold_written_at_short_id( tmp_path ):
    """The live FM: agent wrote at the SHORT id, hook reads at the FULL id."""
    written = hh.write_hold( _SHORT, "P", "short-id hold", awaiting="peer:tiffany", base_dir=tmp_path )
    got = hh.read_hold( _FULL, base_dir=tmp_path )
    assert _persisted( got ) == written
    assert got[ "awaiting" ] == "peer:tiffany"


def test_read_hold_short_id_finds_hold_written_at_full_id( tmp_path ):
    """Symmetric: hook reads at the SHORT id, hold was written at the FULL id."""
    written = hh.write_hold( _FULL, "P", "full-id hold", base_dir=tmp_path )
    assert _persisted( hh.read_hold( _SHORT, base_dir=tmp_path ) ) == written


def test_read_hold_no_prefix_match_returns_none( tmp_path ):
    hh.write_hold( "aaaaaaaa-1111", "P", "other session", base_dir=tmp_path )
    assert hh.read_hold( "bbbbbbbb-2222", base_dir=tmp_path ) is None    # different 8-char prefix


def test_read_hold_empty_session_id_no_fallback( tmp_path ):
    # `not session_id` short-circuits the fallback (no bare-prefix glob).
    assert hh.read_hold( "", base_dir=tmp_path ) is None


def test_read_hold_fallback_ignores_tmp_artifact( tmp_path ):
    # A half-written atomic-write `.tmp` sharing the prefix must be ignored.
    ( tmp_path / f".heartbeat-hold-{_SHORT}.json.tmp" ).write_text( '{"reason": "partial"}' )
    assert hh.read_hold( _FULL, base_dir=tmp_path ) is None             # only the .tmp shares the prefix


def test_read_hold_fallback_prefers_longest_suffix( tmp_path ):
    """Multiple id-form matches → the FULL hyphenated id wins over the short one."""
    hh.write_hold( _SHORT, "P", "short form", base_dir=tmp_path )
    full_hold = hh.write_hold( _FULL, "P", "full form", base_dir=tmp_path )
    # Reading at a THIRD prefix-sharing id must resolve to the longest-suffix file.
    got = hh.read_hold( "f6292818-9999", base_dir=tmp_path )
    assert _persisted( got ) == full_hold and got[ "reason" ] == "full form"


def test_read_hold_fallback_glob_oserror_returns_none( tmp_path, monkeypatch ):
    """Defensive: a glob OSError during fallback → treat as absent (exact path → None)."""
    from pathlib import Path
    def _boom( self, pattern ):
        raise OSError( "glob blew up" )
    monkeypatch.setattr( Path, "glob", _boom )
    assert hh.read_hold( "ffffffff-1111-2222", base_dir=tmp_path ) is None


# ── resolve_hold_base_dir — c121037b facet 3 (per-session base, not LUPIN_ROOT) ─

def test_resolve_hold_base_dir_uses_cwd_when_given( tmp_path ):
    """A truthy cwd (the Stop payload's working dir) → that dir, per-session."""
    assert hh.resolve_hold_base_dir( str( tmp_path ) ) == tmp_path
    assert hh.resolve_hold_base_dir( tmp_path ) == tmp_path             # path-like accepted


def test_resolve_hold_base_dir_non_lupin_session_isolated( tmp_path ):
    """A NON-lupin session's hold resolves to ITS root, not the lupin root."""
    other_project = tmp_path / "some-other-repo"
    other_project.mkdir()
    base = hh.resolve_hold_base_dir( str( other_project ) )
    assert base == other_project
    # And a hold written there is read back from there (round-trip via the base).
    written = hh.write_hold( "s9", "P", "non-lupin hold", base_dir=base )
    assert _persisted( hh.read_hold( "s9", base_dir=base ) ) == written


def test_resolve_hold_base_dir_none_falls_back_to_project_root( monkeypatch, tmp_path ):
    """Falsy/None cwd → cu.get_project_root() (the LUPIN_ROOT fallback seam)."""
    import cosa.utils.util as cu
    monkeypatch.setattr( cu, "get_project_root", lambda: str( tmp_path ) )
    assert hh.resolve_hold_base_dir( None ) == tmp_path
    assert hh.resolve_hold_base_dir( "" )   == tmp_path                 # empty string is falsy


# ── read_hold_resilient — bug 1789f197 (cwd vs project-root write/read mismatch) ─

def test_read_hold_resilient_finds_hold_in_cwd( tmp_path, monkeypatch ):
    """A per-session hold under the session's cwd is found (cwd-first preference)."""
    import cosa.utils.util as cu
    cwd_dir  = tmp_path / "cwd";  cwd_dir.mkdir()
    root_dir = tmp_path / "root"; root_dir.mkdir()
    monkeypatch.setattr( cu, "get_project_root", lambda: str( root_dir ) )
    hh.write_hold( "sid12345", "Rio", "holding", base_dir=cwd_dir )
    hold = hh.read_hold_resilient( "sid12345", cwd=str( cwd_dir ) )
    assert hold is not None
    assert hold[ "persona" ] == "Rio"


def test_read_hold_resilient_finds_hold_at_project_root_when_cwd_differs( tmp_path, monkeypatch ):
    """THE BUG: write_hold default lands at project root; a reader whose cwd is a
    worktree (≠ project root) must STILL find the honored hold via the fallback."""
    import cosa.utils.util as cu
    cwd_dir  = tmp_path / "worktree"; cwd_dir.mkdir()
    root_dir = tmp_path / "root";     root_dir.mkdir()
    monkeypatch.setattr( cu, "get_project_root", lambda: str( root_dir ) )
    hh.write_hold( "sid12345", "Rio", "holding", base_dir=root_dir )   # default-write location
    # cwd dir holds NO file — resilient read must fall through to the project root.
    hold = hh.read_hold_resilient( "sid12345", cwd=str( cwd_dir ) )
    assert hold is not None
    assert hold[ "persona" ] == "Rio"


def test_read_hold_resilient_returns_none_when_absent_everywhere( tmp_path, monkeypatch ):
    """No hold in cwd OR project root → None (both candidates exhausted)."""
    import cosa.utils.util as cu
    cwd_dir  = tmp_path / "cwd";  cwd_dir.mkdir()
    root_dir = tmp_path / "root"; root_dir.mkdir()
    monkeypatch.setattr( cu, "get_project_root", lambda: str( root_dir ) )
    assert hh.read_hold_resilient( "sid12345", cwd=str( cwd_dir ) ) is None


def test_read_hold_resilient_dedups_when_cwd_is_project_root( tmp_path, monkeypatch ):
    """cwd IS the project root → the two candidates collapse to one (dedup); the
    hold is still found (exercises the `key in seen → continue` branch)."""
    import cosa.utils.util as cu
    monkeypatch.setattr( cu, "get_project_root", lambda: str( tmp_path ) )
    hh.write_hold( "sid12345", "Rio", "holding", base_dir=tmp_path )
    hold = hh.read_hold_resilient( "sid12345", cwd=str( tmp_path ) )
    assert hold is not None
    assert hold[ "persona" ] == "Rio"


# ── 6929f4ac §9.2 — pending_user_gates + last_looked_in_on_workers_ts fields ──

def test_write_hold_includes_6929f4ac_fields_in_schema( tmp_path ):
    gate = { "id": "g1", "answered": False }
    hh.write_hold( "sid12345", "Sam", "holding", base_dir=tmp_path,
                   pending_user_gates=[ gate ],
                   last_looked_in_on_workers_ts="2026-06-22T12:00:00+00:00" )
    hold = hh.read_hold( "sid12345", base_dir=tmp_path )
    assert tuple( k for k in hold.keys() if not k.startswith( "_" ) ) == hh.HOLD_SCHEMA_FIELDS
    assert hold[ "pending_user_gates" ] == [ gate ]
    assert hold[ "last_looked_in_on_workers_ts" ] == "2026-06-22T12:00:00+00:00"


def test_write_hold_defaults_6929f4ac_fields( tmp_path ):
    hh.write_hold( "sid12345", "Sam", "plain hold", base_dir=tmp_path )
    hold = hh.read_hold( "sid12345", base_dir=tmp_path )
    assert hold[ "pending_user_gates" ] == [ ]
    assert hold[ "last_looked_in_on_workers_ts" ] is None


def test_write_hold_defaults_a1_proactive_fields( tmp_path ):
    # A1 Face A / Face B debounce stamps default to None on a plain hold.
    hh.write_hold( "sid12346", "Sam", "plain hold", base_dir=tmp_path )
    hold = hh.read_hold( "sid12346", base_dir=tmp_path )
    assert hold[ "last_spinup_check_ts" ] is None
    assert hold[ "last_surfaced_questions_ts" ] is None


def test_write_hold_round_trips_a1_proactive_fields( tmp_path ):
    hh.write_hold( "sid12347", "Sam", "held", base_dir=tmp_path,
                   last_spinup_check_ts="2026-06-23T10:00:00+00:00",
                   last_surfaced_questions_ts="2026-06-23T11:00:00+00:00" )
    hold = hh.read_hold( "sid12347", base_dir=tmp_path )
    assert hh.get_last_spinup_check_ts( hold )       == "2026-06-23T10:00:00+00:00"
    assert hh.get_last_surfaced_questions_ts( hold ) == "2026-06-23T11:00:00+00:00"


def test_get_pending_user_gates_variants():
    assert hh.get_pending_user_gates( None )                          == [ ]
    assert hh.get_pending_user_gates( { } )                           == [ ]   # field absent
    assert hh.get_pending_user_gates( { "pending_user_gates": "x" } ) == [ ]   # non-list
    rows = [ { "id": "g1" }, { "id": "g2" } ]
    assert hh.get_pending_user_gates( { "pending_user_gates": rows } ) == rows


def test_get_last_looked_in_ts_variants():
    assert hh.get_last_looked_in_ts( None )                                       is None
    assert hh.get_last_looked_in_ts( { } )                                        is None   # field absent
    assert hh.get_last_looked_in_ts( { "last_looked_in_on_workers_ts": 123 } )    is None   # non-str
    ts = "2026-06-22T12:00:00+00:00"
    assert hh.get_last_looked_in_ts( { "last_looked_in_on_workers_ts": ts } )     == ts


def test_get_last_spinup_check_ts_variants():
    assert hh.get_last_spinup_check_ts( None )                              is None
    assert hh.get_last_spinup_check_ts( { } )                              is None   # field absent
    assert hh.get_last_spinup_check_ts( { "last_spinup_check_ts": 123 } )   is None   # non-str
    ts = "2026-06-23T10:00:00+00:00"
    assert hh.get_last_spinup_check_ts( { "last_spinup_check_ts": ts } )    == ts


def test_get_last_surfaced_questions_ts_variants():
    assert hh.get_last_surfaced_questions_ts( None )                                    is None
    assert hh.get_last_surfaced_questions_ts( { } )                                    is None   # field absent
    assert hh.get_last_surfaced_questions_ts( { "last_surfaced_questions_ts": 123 } )   is None   # non-str
    ts = "2026-06-23T11:00:00+00:00"
    assert hh.get_last_surfaced_questions_ts( { "last_surfaced_questions_ts": ts } )    == ts


# ── quick_smoke_test ──────────────────────────────────────────────────────────

def test_quick_smoke_test_passes():
    assert hh.quick_smoke_test() is True
