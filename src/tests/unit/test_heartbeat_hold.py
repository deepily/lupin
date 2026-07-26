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
import os
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


# ── multi-root recursive sweep (2026-07-16) ───────────────────────────────────
# The janitor swept ONE directory, non-recursively, while holds land wherever a
# session's cwd happened to be. NOTE: not one assertion here hardcodes a corpus
# census — the live count went 41 → 43 → 44 → 45 across five honest measurements
# by four seats in one evening, with zero errors anywhere. A fixed count is a test
# of a moving target and will flake. Assert on PROPERTIES.

def test_sweep_is_recursive_within_a_root( tmp_path ):
    """Root-only globbing missed strays — a real hold lives under
    lupin/src/migrations/versions/, deposited by a session whose cwd was a subdir."""
    deep = tmp_path / "src" / "migrations" / "versions"
    deep.mkdir( parents=True )
    _hold_file( tmp_path, "atroot",  age_seconds=0 )
    _hold_file( deep,     "instray", age_seconds=0 )

    roots, unreachable, paths, skipped = hh._iter_hold_paths( base_dirs=[ tmp_path ] )

    assert { p.name for p in paths } == { ".heartbeat-hold-atroot.json",
                                          ".heartbeat-hold-instray.json" }
    assert roots == [ str( tmp_path ) ] and unreachable == [ ] and skipped == [ ]


def test_sweep_legacy_single_root_mode_is_NOT_recursive( tmp_path ):
    """base_dirs=None preserves the exact legacy behavior every existing caller
    depends on: one directory, non-recursive."""
    deep = tmp_path / "sub"
    deep.mkdir()
    _hold_file( tmp_path, "atroot",  age_seconds=0 )
    _hold_file( deep,     "instray", age_seconds=0 )

    _roots, _unreachable, paths, _skipped = hh._iter_hold_paths( base_dir=tmp_path )

    assert { p.name for p in paths } == { ".heartbeat-hold-atroot.json" }   # stray NOT reached


def test_sweep_multi_root_dedups_and_reports_unreachable( tmp_path ):
    root_a = tmp_path / "a"; root_a.mkdir()
    root_b = tmp_path / "b"; root_b.mkdir()
    _hold_file( root_a, "ha", age_seconds=0 )
    _hold_file( root_b, "hb", age_seconds=0 )
    missing = tmp_path / "does-not-exist-on-this-host"      # the container-path trap

    roots, unreachable, paths, _skipped = hh._iter_hold_paths(
        base_dirs=[ root_a, root_b, root_a, missing ] )     # root_a listed TWICE

    assert roots == [ str( root_a ), str( root_b ) ]        # swept once each
    assert len( paths ) == 2
    assert unreachable == [ { "root": str( missing ), "error": "not_a_directory" } ]


def test_sweep_root_is_a_file_not_a_directory_is_unreachable( tmp_path ):
    not_a_dir = tmp_path / "file.txt"
    not_a_dir.write_text( "x" )
    roots, unreachable, _paths, _skipped = hh._iter_hold_paths( base_dirs=[ not_a_dir ] )
    assert roots == [ ] and unreachable[ 0 ][ "error" ] == "not_a_directory"


def test_sweep_root_is_dir_oserror_is_unreachable( tmp_path, monkeypatch ):
    import pathlib
    def _boom( self ): raise OSError( "permission denied" )
    monkeypatch.setattr( pathlib.Path, "is_dir", _boom )
    roots, unreachable, _paths, _skipped = hh._iter_hold_paths( base_dirs=[ tmp_path ] )
    assert roots == [ ] and len( unreachable ) == 1


def test_sweep_depth_bound_stops_descending( tmp_path ):
    deep = tmp_path / "a" / "b" / "c" / "d" / "e"
    deep.mkdir( parents=True )
    _hold_file( deep, "toodeep", age_seconds=0 )
    _roots, _unreachable, paths, _skipped = hh._iter_hold_paths( base_dirs=[ tmp_path ], max_depth=2 )
    assert paths == [ ]
    # PRESENCE-assertion: a deeper bound DOES reach it — the bound is what stopped
    # the sweep, not an inability to find anything.
    _r, _u, paths_deep, _s = hh._iter_hold_paths( base_dirs=[ tmp_path ], max_depth=5 )
    assert [ p.name for p in paths_deep ] == [ ".heartbeat-hold-toodeep.json" ]


def test_sweep_skips_listed_dirs_but_SURFACES_the_holds_it_stepped_over( tmp_path ):
    """A skip-list that silently swallows a hold-bearing dir reports 'nothing there'.
    Measured: a hold lives under lupin/.claude/worktrees/cheech-orphan-bridge."""
    venv = tmp_path / ".venv"; venv.mkdir()
    _hold_file( venv, "invenv", age_seconds=0 )
    wt = tmp_path / ".claude" / "worktrees" / "cheech-orphan-bridge"
    wt.mkdir( parents=True )
    _hold_file( wt, "inworktree", age_seconds=0 )

    _roots, _unreachable, paths, skipped = hh._iter_hold_paths( base_dirs=[ tmp_path ] )

    assert paths == [ ]                                    # correctly NOT swept
    # Reported at the SKIP BOUNDARY — the dir the sweep refused to enter — with the
    # count found beneath it. The worktree hold is 2 levels below .claude/worktrees;
    # what matters is that its existence is accounted for, not swallowed.
    skipped_dirs = { s[ "dir" ]: s[ "hold_count" ] for s in skipped }
    assert skipped_dirs == { str( venv ): 1,
                             str( tmp_path / ".claude" / "worktrees" ): 1 }


def test_sweep_ignores_ordinary_non_hold_files( tmp_path ):
    """The overwhelmingly common case, and the one the first draft of these tests
    missed entirely: a real project root is mostly NOT hold files. Only
    `.heartbeat-hold-*.json` is a candidate — everything else is invisible."""
    ( tmp_path / "README.md"                    ).write_text( "x" )
    ( tmp_path / "settings.json"                ).write_text( "{}" )
    ( tmp_path / ".heartbeat-hold-real.json.tmp" ).write_text( "{}" )   # atomic-write artifact
    _hold_file( tmp_path, "real", age_seconds=0 )

    _roots, _unreachable, paths, _skipped = hh._iter_hold_paths( base_dirs=[ tmp_path ] )

    assert [ p.name for p in paths ] == [ ".heartbeat-hold-real.json" ]


def test_probe_of_a_skipped_dir_ignores_ordinary_files( tmp_path ):
    venv = tmp_path / ".venv"; venv.mkdir()
    ( venv / "pyvenv.cfg" ).write_text( "x" )      # non-hold file inside a skipped dir
    _roots, _unreachable, _paths, skipped = hh._iter_hold_paths( base_dirs=[ tmp_path ] )
    assert skipped == [ ]                           # ordinary files are not holds → not news


def test_sweep_skipped_dir_without_holds_is_not_reported( tmp_path ):
    ( tmp_path / "node_modules" ).mkdir()                   # empty → not news
    _roots, _unreachable, _paths, skipped = hh._iter_hold_paths( base_dirs=[ tmp_path ] )
    assert skipped == [ ]


def test_sweep_probe_does_not_descend_into_nested_skipped_dirs( tmp_path ):
    outer = tmp_path / ".venv"; outer.mkdir()
    inner = outer / "node_modules"; inner.mkdir()
    _hold_file( inner, "buried", age_seconds=0 )
    _roots, _unreachable, _paths, skipped = hh._iter_hold_paths( base_dirs=[ tmp_path ] )
    assert skipped == [ ]                                   # nested skip → not probed


def test_sweep_unreadable_directory_is_skipped_not_fatal( tmp_path, monkeypatch ):
    _hold_file( tmp_path, "h", age_seconds=0 )
    def _boom( path ): raise OSError( "permission denied" )
    monkeypatch.setattr( hh.os, "scandir", _boom )
    _roots, _unreachable, paths, _skipped = hh._iter_hold_paths( base_dirs=[ tmp_path ] )
    assert paths == [ ]                                     # swallowed, never raised


def test_sweep_entry_is_dir_oserror_is_skipped( tmp_path, monkeypatch ):
    _hold_file( tmp_path, "h", age_seconds=0 )
    class _BadEntry:
        name = ".heartbeat-hold-h.json"
        path = str( tmp_path / ".heartbeat-hold-h.json" )
        def is_dir( self, follow_symlinks=True ): raise OSError( "stat failed" )
    monkeypatch.setattr( hh.os, "scandir", lambda p: [ _BadEntry() ] )
    _roots, _unreachable, paths, _skipped = hh._iter_hold_paths( base_dirs=[ tmp_path ] )
    assert paths == [ ]


def test_probe_entry_is_dir_oserror_is_skipped( tmp_path, monkeypatch ):
    class _BadEntry:
        name = "whatever"
        path = "/x/whatever"
        def is_dir( self, follow_symlinks=True ): raise OSError( "stat failed" )
    monkeypatch.setattr( hh.os, "scandir", lambda p: [ _BadEntry() ] )
    assert hh._probe_dir_for_holds( tmp_path, 3 ) == [ ]


def test_probe_unreadable_dir_returns_empty( tmp_path, monkeypatch ):
    def _boom( path ): raise OSError( "denied" )
    monkeypatch.setattr( hh.os, "scandir", _boom )
    assert hh._probe_dir_for_holds( tmp_path, 3 ) == [ ]


def test_is_skipped_dir_names_and_claude_worktrees( tmp_path ):
    assert hh._is_skipped_dir( tmp_path / ".venv", hh.SWEEP_SKIP_DIR_NAMES )  is True
    assert hh._is_skipped_dir( tmp_path / ".git",  hh.SWEEP_SKIP_DIR_NAMES )  is True
    assert hh._is_skipped_dir( tmp_path / ".claude" / "worktrees",
                               hh.SWEEP_SKIP_DIR_NAMES ) is True
    # A dir merely NAMED worktrees, not under .claude, is NOT skipped — the rule is
    # about the .claude/worktrees tree specifically, not the word.
    assert hh._is_skipped_dir( tmp_path / "worktrees", hh.SWEEP_SKIP_DIR_NAMES ) is False
    assert hh._is_skipped_dir( tmp_path / "src",       hh.SWEEP_SKIP_DIR_NAMES ) is False


def test_prune_multi_root_recursive_reaps_across_roots( tmp_path ):
    root_a = tmp_path / "a"; ( root_a / "deep" ).mkdir( parents=True )
    root_b = tmp_path / "b"; root_b.mkdir()
    _hold_file( root_a / "deep", "ancient_a", age_seconds=900 + 21600 + 100 )
    _hold_file( root_b,          "ancient_b", age_seconds=900 + 21600 + 100 )
    _hold_file( root_b,          "fresh_b",   age_seconds=0 )

    pruned = hh.prune_stale_hold_files( base_dirs=[ root_a, root_b ], now=_PRUNE_NOW )

    assert set( pruned ) == { str( root_a / "deep" / ".heartbeat-hold-ancient_a.json" ),
                              str( root_b / ".heartbeat-hold-ancient_b.json" ) }
    assert ( root_b / ".heartbeat-hold-fresh_b.json" ).exists()      # control: fresh survives


# ── classify_hold_file ────────────────────────────────────────────────────────

def test_classify_prunable_ancient( tmp_path ):
    _hold_file( tmp_path, "ancient", age_seconds=900 + 21600 + 100, persona="María 🌸" )
    row = hh.classify_hold_file( tmp_path / ".heartbeat-hold-ancient.json", now=_PRUNE_NOW )
    assert row[ "verdict" ]           == hh.VERDICT_PRUNABLE
    assert row[ "reason" ]            == hh.VERDICT_PRUNABLE
    assert row[ "session_id" ]        == "ancient"
    assert row[ "persona" ]           == "María 🌸"
    assert row[ "ttl_usable" ]        is True
    assert row[ "threshold_seconds" ] == 900 + 21600
    assert row[ "held_at_age_seconds" ] > 0 and row[ "mtime_age_seconds" ] is not None


def test_classify_keep_reasons_name_the_guard( tmp_path ):
    ( tmp_path / ".heartbeat-hold-garbage.json" ).write_text( "{not json" )
    ( tmp_path / ".heartbeat-hold-list.json"    ).write_text( "[]" )
    _hold_file( tmp_path, "live",   age_seconds=999999 )
    _hold_file( tmp_path, "nottl",  age_seconds=999999, ttl="nope" )
    _hold_file( tmp_path, "recent", age_seconds=900 + 60 )
    def _c( sid, **kw ):
        return hh.classify_hold_file( tmp_path / f".heartbeat-hold-{sid}.json", now=_PRUNE_NOW, **kw )

    assert _c( "garbage" )[ "reason" ] == hh.KEEP_UNREADABLE
    assert _c( "list"    )[ "reason" ] == hh.KEEP_NOT_AN_OBJECT
    assert _c( "live", live_session_ids=[ "live" ] )[ "reason" ] == hh.KEEP_LIVE_SESSION
    assert _c( "nottl"   )[ "reason" ] == hh.KEEP_NO_PROVABLE_AGE
    assert _c( "recent"  )[ "reason" ] == hh.KEEP_WITHIN_THRESHOLD
    for sid in ( "garbage", "list", "live", "nottl", "recent" ):
        assert ( tmp_path / f".heartbeat-hold-{sid}.json" ).exists()   # classify deletes NOTHING


def test_classify_missing_held_at_is_no_provable_age( tmp_path ):
    ( tmp_path / ".heartbeat-hold-noheld.json" ).write_text( json.dumps(
        { "session_id": "noheld", "ttl_seconds": 900, "reason": "x" } ) )
    row = hh.classify_hold_file( tmp_path / ".heartbeat-hold-noheld.json", now=_PRUNE_NOW )
    assert row[ "reason" ] == hh.KEEP_NO_PROVABLE_AGE
    assert row[ "held_at_age_seconds" ] is None and row[ "ttl_usable" ] is True


def test_classify_missing_file_is_unreadable_with_no_mtime( tmp_path ):
    row = hh.classify_hold_file( tmp_path / ".heartbeat-hold-ghost.json", now=_PRUNE_NOW )
    assert row[ "reason" ] == hh.KEEP_UNREADABLE and row[ "mtime_age_seconds" ] is None


def test_classify_flags_cargo_bearing( tmp_path ):
    _hold_file( tmp_path, "memento", age_seconds=0,
                note_to_my_successor="the only copy", board=[ "x" ] )
    row = hh.classify_hold_file( tmp_path / ".heartbeat-hold-memento.json", now=_PRUNE_NOW )
    assert row[ "cargo_bearing" ] is True
    assert row[ "cargo_keys" ]    == [ "board", "note_to_my_successor" ]


def test_classify_authoritative_dead_drops_grace_but_no_sid_stays_conservative( tmp_path ):
    _hold_file( tmp_path, "deadsid", age_seconds=900 + 60 )          # past TTL, inside grace
    ( tmp_path / ".heartbeat-hold-nosid.json" ).write_text( json.dumps(
        { "held_at": ( _PRUNE_NOW - datetime.timedelta( seconds=900 + 60 ) ).isoformat(),
          "ttl_seconds": 900, "reason": "x" } ) )                    # no session_id
    dead  = hh.classify_hold_file( tmp_path / ".heartbeat-hold-deadsid.json",
                                   now=_PRUNE_NOW, live_session_ids=[ "someone-else" ] )
    nosid = hh.classify_hold_file( tmp_path / ".heartbeat-hold-nosid.json",
                                   now=_PRUNE_NOW, live_session_ids=[ "someone-else" ] )
    assert dead[ "verdict" ] == hh.VERDICT_PRUNABLE and dead[ "threshold_seconds" ] == 900
    # bias-to-keep: no session_id ⇒ no positive-dead reading ⇒ conservative TTL+grace
    assert nosid[ "verdict" ] == hh.VERDICT_KEEP and nosid[ "threshold_seconds" ] == 900 + 21600


def test_classify_flags_anchor_disagreement_between_the_two_readers( tmp_path ):
    """The janitor ages on held_at; the HOOK's is_fresh anchors on the file's mtime
    (B1 — "agents have no reliable wall-clock"). Where they disagree, the file is now
    KEPT: pruning requires BOTH clocks to call it ancient.

    ⚠️ THIS ASSERTION WAS FLIPPED ON PURPOSE — store row `8670731d`, 2026-07-26. It
    used to read `verdict == VERDICT_PRUNABLE`, pinning the behavior that the
    disagreement was *reported and then ignored*: "reported as data, not acted on."
    That was an accurate description of the code and a faithful test OF THE DEFECT.
    The row's whole content is that a hold the fleet is actively HONORING must not be
    deletable, so the old expectation could not survive the fix.

    The flip is recorded here rather than only in the commit, because "my change broke
    a test so I changed the test" is the shape that deserves a reader's suspicion. What
    changed is the POLICY, deliberately; the disagreement detection itself is unchanged
    and is still asserted below, along with its presence-control.
    """
    _hold_file( tmp_path, "disagree", age_seconds=900 + 21600 + 100 )   # ancient held_at
    path = tmp_path / ".heartbeat-hold-disagree.json"
    fresh_epoch = _PRUNE_NOW.timestamp() - 10                            # ...but JUST written
    os.utime( path, ( fresh_epoch, fresh_epoch ) )

    row = hh.classify_hold_file( path, now=_PRUNE_NOW )
    assert row[ "verdict" ] == hh.VERDICT_KEEP                     # one clock says alive
    assert row[ "reason" ]  == hh.KEEP_ANCHOR_DISAGREEMENT         # ...and it says why
    assert row[ "anchor_disagreement" ] is True                    # the detection, unchanged
    # PRESENCE-control: an ancient file with an ancient mtime does NOT get flagged.
    _hold_file( tmp_path, "agree", age_seconds=900 + 21600 + 100 )
    old_epoch = _PRUNE_NOW.timestamp() - ( 900 + 21600 + 100 )
    os.utime( tmp_path / ".heartbeat-hold-agree.json", ( old_epoch, old_epoch ) )
    agreed = hh.classify_hold_file( tmp_path / ".heartbeat-hold-agree.json", now=_PRUNE_NOW )
    assert agreed[ "verdict" ] == hh.VERDICT_PRUNABLE and agreed[ "anchor_disagreement" ] is False


def test_classify_defaults_now_to_current_time( tmp_path ):
    # Anchored on REAL now, not _PRUNE_NOW — the now=None path measures against the
    # wall clock, so a fixture-dated hold would read as a year stale.
    hh.write_hold( "fresh", "p", "r", ttl_seconds=900, base_dir=tmp_path )
    row = hh.classify_hold_file( tmp_path / ".heartbeat-hold-fresh.json" )   # now=None path
    assert row[ "verdict" ] == hh.VERDICT_KEEP


# ── report_hold_files — REACH and CLASSIFY, delete nothing ────────────────────

def test_report_SWEPT_ZERO_ROOTS_is_distinguishable_from_FOUND_ZERO_PRUNABLE( tmp_path ):
    """THE distinction the acceptance evidence turns on. A janitor pointed at roots
    that do not exist on this host (the config-derived /var/external-projects trap)
    reaches nothing — and must NOT look identical to a clean sweep that found
    nothing to reap. A lone zero cannot tell those apart; these two reports can."""
    missing = tmp_path / "not-on-this-host"
    swept_nothing = hh.report_hold_files( base_dirs=[ missing ], now=_PRUNE_NOW )

    _hold_file( tmp_path, "fresh", age_seconds=0 )
    found_nothing = hh.report_hold_files( base_dirs=[ tmp_path ], now=_PRUNE_NOW )

    # Both have prunable == 0. That is the whole trap.
    assert swept_nothing[ "counts" ][ "prunable" ] == found_nothing[ "counts" ][ "prunable" ] == 0
    # But they are NOT the same fact, and the report says so:
    assert swept_nothing[ "roots_swept" ] == [ ]                 # reached NOTHING
    assert swept_nothing[ "roots_unreachable" ] == [ { "root": str( missing ),
                                                       "error": "not_a_directory" } ]
    assert swept_nothing[ "files_found" ] == 0
    assert found_nothing[ "roots_swept" ] == [ str( tmp_path ) ] # reached a root
    assert found_nothing[ "files_found" ] == 1                   # ...and SAW a file


def test_report_never_deletes_even_a_provably_ancient_file( tmp_path ):
    """The absolute invariant of this milestone: the report classifies and keeps its
    hands off. Deletion is a separate, gated step.

    ⚠️ THIS FIXTURE USED TO CARRY `note_to_my_successor="irreplaceable"` AND ASSERT
    `prunable == 1`. It was written when cargo was REPORTED but not GUARDED, so one
    file could demonstrate both "ancient enough to prune" and "carries cargo" at
    once. Precondition 1 of `11461241` separates those two properties on purpose —
    a cargo file is no longer prunable at all — so the fixture is SPLIT rather than
    the assertion relaxed. The ancient-and-empty file still proves the report KNOWS
    it could prune; the cargo case gets its own tests below.
    """
    _hold_file( tmp_path, "ancient", age_seconds=900 + 21600 + 100 )
    report = hh.report_hold_files( base_dirs=[ tmp_path ], now=_PRUNE_NOW )
    assert report[ "counts" ][ "prunable" ] == 1                 # it KNOWS it could
    assert report[ "deleted" ] == 0                              # and it did NOT
    assert ( tmp_path / ".heartbeat-hold-ancient.json" ).exists()


def test_an_ancient_CARGO_file_is_not_even_prunable( tmp_path ):
    """Precondition 1 of `11461241` (Rio F-A, BINDING) — the structural cargo guard.

    Same age as the file above, one key different. `allow_cargo_deletion` defaults
    to False, so an ancient hold carrying non-schema cargo is KEEP/`cargo_bearing` —
    and the guard lives in `classify_hold_file`, not at a call site, because A0
    (this milestone's origin bug) WAS a call-site bug.
    """
    _hold_file( tmp_path, "ancient", age_seconds=900 + 21600 + 100,
                note_to_my_successor="irreplaceable" )
    report = hh.report_hold_files( base_dirs=[ tmp_path ], now=_PRUNE_NOW )
    assert report[ "counts" ][ "prunable" ] == 0
    assert report[ "counts" ][ "cargo_bearing" ] == 1
    assert report[ "files" ][ 0 ][ "reason"  ] == hh.KEEP_CARGO_BEARING
    assert report[ "files" ][ 0 ][ "verdict" ] == hh.VERDICT_KEEP


def test_the_cargo_guard_is_OPENABLE_for_the_gated_reclamation_step( tmp_path ):
    """The other half of Rio's F-A, and it is not optional.

    Triage is COPY-FORWARD, so rescued originals KEEP their cargo keys. A cargo
    guard that could never be opened would make those husks unreclaimable forever
    and defeat Rick's Q4 — "if the janitor can't reclaim them, it isn't fixed".
    Structural AND openable; the gated step passes True and has to say so.
    """
    _hold_file( tmp_path, "ancient", age_seconds=900 + 21600 + 100,
                note_to_my_successor="already triaged" )
    report = hh.report_hold_files( base_dirs=[ tmp_path ], now=_PRUNE_NOW,
                                   allow_cargo_deletion=True )
    assert report[ "counts" ][ "prunable" ] == 1
    assert report[ "counts" ][ "cargo_bearing" ] == 1            # still REPORTED as cargo
    assert report[ "deleted" ] == 0                              # report still deletes nothing


def test_the_janitor_itself_will_not_delete_cargo_by_default( tmp_path ):
    """The guard where it actually matters: the path that unlinks.

    `report_hold_files` cannot delete anything by construction, so a guard proven
    only against the report is proven against a function with no teeth. This drives
    `prune_stale_hold_files` — the one holding the `unlink` — and carries a POSITIVE
    CONTROL in the same run, so a surviving cargo file can never be confused with a
    janitor that was pointed at the wrong directory.
    """
    _hold_file( tmp_path, "cargo", age_seconds=900 + 21600 + 100,
                note_to_my_successor="irreplaceable" )
    _hold_file( tmp_path, "plain", age_seconds=900 + 21600 + 100 )
    pruned = hh.prune_stale_hold_files( base_dirs=[ tmp_path ], now=_PRUNE_NOW )
    assert ( tmp_path / ".heartbeat-hold-cargo.json" ).exists()      # survived the janitor
    assert not ( tmp_path / ".heartbeat-hold-plain.json" ).exists()  # CONTROL: it can still kill
    assert len( pruned ) == 1


def test_report_counts_and_kept_reason_tally( tmp_path ):
    _hold_file( tmp_path, "ancient", age_seconds=900 + 21600 + 100 )
    _hold_file( tmp_path, "recent",  age_seconds=900 + 60 )
    _hold_file( tmp_path, "nottl",   age_seconds=999999, ttl="nope" )
    _hold_file( tmp_path, "memento", age_seconds=0, note_to_my_successor="x" )

    report = hh.report_hold_files( base_dirs=[ tmp_path ], now=_PRUNE_NOW )
    counts = report[ "counts" ]

    assert counts[ "prunable" ]      == 1
    assert counts[ "keep" ]          == 3
    assert counts[ "cargo_bearing" ] == 1
    assert counts[ "ttl_unusable" ]  == 1
    assert counts[ "reachable_but_kept_reasons" ] == {
        hh.KEEP_WITHIN_THRESHOLD : 2,      # recent + memento
        hh.KEEP_NO_PROVABLE_AGE  : 1,      # nottl
    }


def test_report_surfaces_skipped_dirs_and_requested_roots( tmp_path ):
    wt = tmp_path / ".claude" / "worktrees" / "orphan"
    wt.mkdir( parents=True )
    _hold_file( wt, "inworktree", age_seconds=0 )
    missing = tmp_path / "gone"
    report  = hh.report_hold_files( base_dirs=[ tmp_path, missing ], now=_PRUNE_NOW )
    assert report[ "roots_requested" ] == [ str( tmp_path ), str( missing ) ]
    assert report[ "skipped_dirs_with_holds" ] == [
        { "dir": str( tmp_path / ".claude" / "worktrees" ), "hold_count": 1 } ]


def test_report_legacy_single_root_mode_reports_that_root( tmp_path ):
    _hold_file( tmp_path, "h", age_seconds=0 )
    report = hh.report_hold_files( base_dir=tmp_path, now=_PRUNE_NOW )
    assert report[ "roots_swept" ] == [ str( tmp_path ) ]
    assert report[ "roots_requested" ] == [ str( tmp_path ) ]     # mirrors swept in legacy mode
    assert report[ "files_found" ] == 1


def test_report_legacy_glob_oserror_reports_unreachable_root( monkeypatch ):
    class _BadBase:
        def glob( self, pattern ): raise OSError( "boom" )
    monkeypatch.setattr( hh, "_resolve_base_dir", lambda b: _BadBase() )
    report = hh.report_hold_files( base_dir="anything", now=_PRUNE_NOW )
    assert report[ "roots_swept" ] == [ ]
    assert report[ "roots_unreachable" ][ 0 ][ "error" ] == "glob_failed"


def test_report_defaults_now_to_current_time( tmp_path ):
    _hold_file( tmp_path, "fresh", age_seconds=0 )
    assert hh.report_hold_files( base_dirs=[ tmp_path ] )[ "files_found" ] == 1


# ── NEGATIVE CONTROL (R-3, non-negotiable) ────────────────────────────────────
# "The check existing is not the check working." An absence-assertion with no
# presence-assertion beside it cannot distinguish "the guard held" from "the sweep
# never ran" — the exact defect class this milestone was made of. Every survival
# claim below is paired, in ONE test, with a reaping claim on the same call.

def test_NEGATIVE_CONTROL_fresh_hold_survives_the_same_sweep_that_reaps_an_ancient_one( tmp_path ):
    """The mandated control. A FRESH hold must SURVIVE the very sweep that PROVES
    it can delete by reaping an ancient one beside it. Without the reaping half,
    'the fresh file still exists' is equally consistent with a janitor that did
    nothing at all."""
    _hold_file( tmp_path, "fresh",   age_seconds=0 )
    _hold_file( tmp_path, "ancient", age_seconds=900 + 21600 + 100 )

    pruned = hh.prune_stale_hold_files( base_dir=tmp_path, now=_PRUNE_NOW )

    # PRESENCE-assertion: the sweep provably CAN delete — it just did.
    assert pruned == [ str( tmp_path / ".heartbeat-hold-ancient.json" ) ]
    assert not ( tmp_path / ".heartbeat-hold-ancient.json" ).exists()
    # ABSENCE-assertion: and it spared the fresh one. Now this means something.
    assert ( tmp_path / ".heartbeat-hold-fresh.json" ).exists()


def test_NEGATIVE_CONTROL_fresh_ttl_unusable_hold_survives_beside_a_reaped_ancient( tmp_path ):
    """A2's mandated control, applied to the ttl-unusable population: a hold with NO
    usable ttl and a FRESH mtime must SURVIVE — proven against a same-sweep reap."""
    # ttl-unusable + fresh → the janitor cannot prove age → KEEP
    ( tmp_path / ".heartbeat-hold-nottl.json" ).write_text( json.dumps(
        { "session_id": "nottl", "held_at": _PRUNE_NOW.isoformat(), "reason": "x",
          "note_to_my_successor": "irreplaceable" } ) )
    _hold_file( tmp_path, "ancient", age_seconds=900 + 21600 + 100 )

    pruned = hh.prune_stale_hold_files( base_dir=tmp_path, now=_PRUNE_NOW )

    assert pruned == [ str( tmp_path / ".heartbeat-hold-ancient.json" ) ]   # the check CAN fire
    assert ( tmp_path / ".heartbeat-hold-nottl.json" ).exists()             # ...and it spared this


def test_NEGATIVE_CONTROL_report_classifies_fresh_keep_and_ancient_prunable_together( tmp_path ):
    """The report's control: the SAME call must yield BOTH verdicts. A report that
    only ever says 'keep' is indistinguishable from a report that never looked."""
    _hold_file( tmp_path, "fresh",   age_seconds=0 )
    _hold_file( tmp_path, "ancient", age_seconds=900 + 21600 + 100 )

    report   = hh.report_hold_files( base_dirs=[ tmp_path ], now=_PRUNE_NOW )
    verdicts = { row[ "session_id" ]: row[ "verdict" ] for row in report[ "files" ] }

    assert verdicts == { "fresh": hh.VERDICT_KEEP, "ancient": hh.VERDICT_PRUNABLE }
    assert report[ "counts" ][ "prunable" ] == 1 and report[ "counts" ][ "keep" ] == 1
    # ...and the report kept its hands off BOTH regardless of verdict.
    assert ( tmp_path / ".heartbeat-hold-ancient.json" ).exists()
    assert report[ "deleted" ] == 0


# ── ttl_is_usable ─────────────────────────────────────────────────────────────

def test_ttl_is_usable_true_for_numbers():
    assert hh.ttl_is_usable( { "ttl_seconds": 900 } )   is True
    assert hh.ttl_is_usable( { "ttl_seconds": 1.5 } )   is True


def test_ttl_is_usable_false_for_missing_hold_absent_null_bool_and_string():
    assert hh.ttl_is_usable( None )                     is False   # no hold
    assert hh.ttl_is_usable( { } )                      is False   # falsy dict
    assert hh.ttl_is_usable( { "reason": "x" } )        is False   # key ABSENT (22 of 45 on disk)
    assert hh.ttl_is_usable( { "ttl_seconds": None } )  is False   # literal null (0 on disk)
    assert hh.ttl_is_usable( { "ttl_seconds": True } )  is False   # bool must never read as 1
    assert hh.ttl_is_usable( { "ttl_seconds": "900" } ) is False   # string


# ── hold_cargo_keys ───────────────────────────────────────────────────────────

def test_hold_cargo_keys_empty_for_pure_schema_hold( tmp_path ):
    hold = hh.write_hold( "sid1", "María 🌸", "r", base_dir=tmp_path )
    assert hh.hold_cargo_keys( hold ) == [ ]


def test_hold_cargo_keys_returns_sorted_non_schema_keys_and_ignores_annotations():
    hold = { "session_id": "s", "ttl_seconds": 900,
             "note_to_my_successor": "...", "board": [ ], "krishna_must_know": "...",
             hh.HOLD_MTIME_ANNOTATION: 123.0 }          # `_`-prefixed → NOT cargo
    assert hh.hold_cargo_keys( hold ) == [ "board", "krishna_must_know", "note_to_my_successor" ]


def test_hold_cargo_keys_non_dict_is_empty():
    assert hh.hold_cargo_keys( None ) == [ ]
    assert hh.hold_cargo_keys( "nope" ) == [ ]


# ── write_hold ttl validation (loud at write) ─────────────────────────────────

def test_write_hold_rejects_none_bool_and_string_ttl( tmp_path ):
    # The asymmetry this fixes: held_at=None → _now() and pending_user_gates=None →
    # [] were normalized; ttl_seconds=None alone went to disk as a null.
    for bad in ( None, True, False, "900", [ 900 ] ):
        with pytest.raises( ValueError, match="positive number" ):
            hh.write_hold( "sid", "p", "r", ttl_seconds=bad, base_dir=tmp_path )
    assert not ( tmp_path / ".heartbeat-hold-sid.json" ).exists()   # nothing was written


def test_write_hold_rejects_non_positive_ttl( tmp_path ):
    for bad in ( 0, -1, -0.5 ):
        with pytest.raises( ValueError, match="POSITIVE" ):
            hh.write_hold( "sid", "p", "r", ttl_seconds=bad, base_dir=tmp_path )


def test_write_hold_accepts_valid_ttl_including_float( tmp_path ):
    # PRESENCE-assertion beside the rejections above: the guard is not a brick wall.
    assert hh.write_hold( "sid", "p", "r", ttl_seconds=900, base_dir=tmp_path )[ "ttl_seconds" ] == 900
    assert hh.write_hold( "sid", "p", "r", ttl_seconds=1.5, base_dir=tmp_path )[ "ttl_seconds" ] == 1.5


# ── write_hold reason validation (A-1, Rio ⚡ 2026-07-21) ──────────────────────

@pytest.mark.parametrize( "bad", [ "", "   ", "\t\n", " ", None ] )
def test_write_hold_rejects_an_unhonorable_reason( tmp_path, bad ):
    """
    The SECOND prose contract this function enforced with nothing. `is_honored`
    requires a non-empty reason, so an empty one minted a hold that declared
    quiescence and defended nothing — the 22-file corpus shape, produced by the
    writer itself.

    STRIPPED, not `== ""`: the params run past the empty string precisely because
    a narrower guard would let "   " through and reopen the defect one keystroke
    over. The non-breaking space is here because `str.strip()` removes it while a
    hand-rolled equality check would not.
    """
    with pytest.raises( ValueError, match="non-empty" ):
        hh.write_hold( "sid", "p", bad, base_dir=tmp_path )
    assert not ( tmp_path / ".heartbeat-hold-sid.json" ).exists()   # nothing was written


def test_write_hold_reason_guard_agrees_exactly_with_is_honored( tmp_path ):
    """
    THE ANTI-DRIFT ASSERTION, and the whole point of the finding: two checks on
    one property must agree on the property, or the stricter one is just a smaller
    version of the hole. For every candidate, "the writer accepts it" and "the
    reader honors it" must be the SAME boolean — no value may pass the writer and
    fail the reader, which is exactly what A-1 was.
    """
    for candidate in ( "", "   ", "\t\n", " ", "holding", " x ", "0" ):
        try:
            hh.write_hold( "agree", "p", candidate, base_dir=tmp_path )
            writer_accepts = True
        except ValueError:
            writer_accepts = False
        reader_honors = ( hh.is_honored( hh.read_hold( "agree", base_dir=tmp_path ) )
                          if writer_accepts else False )
        assert writer_accepts == reader_honors, \
            f"writer/reader disagree on reason={candidate!r} — that gap IS finding A-1"


def test_write_hold_accepts_a_real_reason( tmp_path ):
    # PRESENCE-assertion beside the rejections: the guard is not a brick wall.
    assert hh.write_hold( "sid", "p", "holding on the seam review",
                          base_dir=tmp_path )[ "reason" ] == "holding on the seam review"


def test_write_hold_reason_guard_precedes_the_write_so_a_refresh_is_safe( tmp_path ):
    """
    Ordering is load-bearing, not tidy: unlinking a bad hold still leaves the
    session undefended, so the only repair that preserves a LIVE defense is
    refusing before the overwrite ever happens.
    """
    hh.write_hold( "live", "p", "genuinely holding", ttl_seconds=14400, base_dir=tmp_path )
    before = hh.read_hold( "live", base_dir=tmp_path )
    assert hh.is_honored( before )

    with pytest.raises( ValueError ):
        hh.write_hold( "live", "p", "", ttl_seconds=14400, base_dir=tmp_path )

    after = hh.read_hold( "live", base_dir=tmp_path )
    assert hh.is_honored( after ),               "a refused write must not cost a live defense"
    assert after[ "reason" ] == before[ "reason" ]


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


# ── read_hold_exact — the reader a GUARD must use (8abdcbbf) ──────────────────
#
# `read_hold` is prefix-tolerant because a READ that resolves to the wrong file
# costs at worst a missed poke. `write_hold`/`clear_hold` act on the EXACT path,
# so a guard resolving prefix-tolerantly objects to a file its action will never
# touch — which refused a session its hold over cargo in a sibling, at exit 6,
# against a path that did not exist.

def test_read_hold_exact_ignores_a_prefix_sibling( tmp_path ):
    """THE WHOLE POINT: `read_hold` finds the sibling, `read_hold_exact` does not.
    Both are correct — for different questions."""
    hh.write_hold( "c121037b-aaaa-1111-2222-3333", "Clayton", "holding", base_dir=tmp_path )
    assert hh.read_hold( "c121037b", base_dir=tmp_path ) is not None        # tolerant: found
    assert hh.read_hold_exact( "c121037b", base_dir=tmp_path ) is None      # exact: absent


def test_read_hold_exact_reads_its_own_file( tmp_path ):
    written = hh.write_hold( "sid-exact", "Clayton", "holding", base_dir=tmp_path )
    assert hh.read_hold_exact( "sid-exact", base_dir=tmp_path ) == written


def test_read_hold_exact_carries_no_mtime_annotation( tmp_path ):
    """Freshness is a question about a RESOLVED hold; this reader resolves
    nothing, so it must not imply an answer it did not compute."""
    hh.write_hold( "sid-exact", "Clayton", "holding", base_dir=tmp_path )
    assert hh.HOLD_MTIME_ANNOTATION not in hh.read_hold_exact( "sid-exact", base_dir=tmp_path )


def test_read_hold_exact_corrupt_json_returns_none( tmp_path ):
    hh.hold_path( "sid-bad", base_dir=tmp_path ).write_text( "{not json" )
    assert hh.read_hold_exact( "sid-bad", base_dir=tmp_path ) is None


def test_read_hold_exact_unreadable_file_returns_none( tmp_path, monkeypatch ):
    """An OSError on read is a null, never a raise — a guard that explodes on a
    permissions blip takes the session's hold down with it."""
    hh.write_hold( "sid-oserr", "Clayton", "holding", base_dir=tmp_path )
    def _boom( self, *a, **k ):
        raise OSError( "permission denied" )
    monkeypatch.setattr( "pathlib.Path.read_text", _boom )
    assert hh.read_hold_exact( "sid-oserr", base_dir=tmp_path ) is None


def test_read_hold_exact_non_object_json_returns_none( tmp_path ):
    """A JSON array parses fine and is not a hold. `hold_cargo_keys` would treat
    a non-dict as a shape it can inspect, so the reader rejects it here."""
    hh.hold_path( "sid-list", base_dir=tmp_path ).write_text( "[1, 2, 3]" )
    assert hh.read_hold_exact( "sid-list", base_dir=tmp_path ) is None
