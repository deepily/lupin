"""
Unit tests for the Phi-4 vs Flash-Lite replay-set freeze (handoff §7 item 1).

THE HEADLINE TEST IS `test_guard_raises_on_the_REAL_live_corpus_path`. The plan's
original freeze guard was vacuous: it named `/var/lupin/dm-corpus/...`, a path
that does not exist on the host, so the guard could never match and passed by
default. This suite proves the opposite property — the guard is fed the path the
PRODUCTION resolver returns, with no mock in the way, and must raise. If someone
later re-points the harness at a hardcoded container path, that test goes red.

Imports the module NORMALLY, as a package. The first cut lived in a dashed script
directory loaded through `importlib.util.spec_from_file_location`, which coverage
cannot attribute by module name — so Convention 6 was unevidenceable and the
`# pragma: no cover` markers were decorative. A plain package makes the number
obtainable and lets `main()` be tested instead of excluded.

Venue: :7999-eligible. Pure unit — tmp_path only, no server, no DB, and it never
writes to the live corpus directory.
"""

import os
import json

import pytest

from cosa.research.phi4_flash_lite_study import freeze_corpus as FZ


def _row( body, ts="2026-08-17T10:00:00", sender="maria" ):
    return { "ts": ts, "from": sender, "body": body, "words": len( body.split() ) }


SHORT_BODY = "One claim here. Two claims here."
LONG_BODY  = (
    "The first claim is here. The second claim follows it. A third claim lands next. "
    "A fourth claim arrives. A fifth claim closes the message."
)


# ─────────────────────────────────────────────────────────────────────────────
# THE FREEZE GUARD — the whole reason this module exists
# ─────────────────────────────────────────────────────────────────────────────

def test_guard_raises_on_the_REAL_live_corpus_path():
    """
    EXECUTOR: AI.

    Feeds the guard the path the PRODUCTION resolver returns — not a mock, not a
    fixture, not `/var/lupin`. The guard must raise. This is the assertion the
    cascade found missing: a guard aimed at a path that cannot occur passes by
    default and protects nothing.
    """
    live = FZ.resolve_live_corpus_path()

    # Sanity on the resolution itself: it must be the host path, not the container
    # mount, or the test below would be re-testing the vacuous guard.
    assert live.endswith( "dm_traffic.jsonl" )
    assert not live.startswith( "/var/lupin" ), (
        f"resolver returned the container mount {live} — the harness would guard a "
        f"path that never occurs on this host"
    )

    with pytest.raises( FZ.LivePathRefused ) as excinfo:
        FZ.assert_snapshot_is_not_live( live )

    assert "LIVE corpus" in str( excinfo.value )


def test_dir_guard_raises_on_the_REAL_live_corpus_directory():
    """
    EXECUTOR: AI.

    The hole the file-level guard has, closed. Point a caller at the live corpus
    DIRECTORY and the filenames differ — `dm_replay_frozen.jsonl` is not
    `dm_traffic.jsonl` — so the file guard passes and the caller gets a
    FileNotFoundError instead of a refusal. Found by this suite's own replay-side
    test, not by reading the code.
    """
    live_dir = os.path.dirname( FZ.resolve_live_corpus_path() )

    with pytest.raises( FZ.LivePathRefused ) as excinfo:
        FZ.assert_dir_is_not_live_corpus_dir( live_dir )
    assert "LIVE corpus directory" in str( excinfo.value )


def test_dir_guard_allows_a_separate_directory( tmp_path ):
    live = tmp_path / "live" / "dm_traffic.jsonl"
    live.parent.mkdir()
    live.write_text( "" )
    got = FZ.assert_dir_is_not_live_corpus_dir( str( tmp_path / "frozen" ), live_path=str( live ) )
    assert got == os.path.realpath( str( tmp_path / "frozen" ) )


def test_dir_guard_catches_a_bind_mount_style_alias( tmp_path ):
    """Same directory inode under a second path — realpath alone would let it through."""
    live_dir = tmp_path / "live"
    live_dir.mkdir()
    live = live_dir / "dm_traffic.jsonl"
    live.write_text( "" )
    alias = tmp_path / "alias"
    alias.symlink_to( live_dir )

    with pytest.raises( FZ.LivePathRefused ):
        FZ.assert_dir_is_not_live_corpus_dir( str( alias ), live_path=str( live ) )


def test_freeze_refuses_an_out_dir_inside_the_live_corpus_directory( tmp_path ):
    """The freeze must not drop a snapshot into the append-only tree."""
    live_dir = tmp_path / "dm-corpus"
    live_dir.mkdir()
    live = live_dir / "dm_traffic.jsonl"
    live.write_text( json.dumps( _row( LONG_BODY ) ) + "\n" )

    with pytest.raises( FZ.LivePathRefused ) as excinfo:
        FZ.freeze( out_dir=str( live_dir ), live_path=str( live ) )
    assert "LIVE corpus directory" in str( excinfo.value )


def test_guard_raises_when_a_symlink_points_at_the_live_corpus( tmp_path ):
    """A realpath comparison, not a string comparison — a symlink cannot walk around it."""
    live = tmp_path / "dm_traffic.jsonl"
    live.write_text( "" )
    link = tmp_path / "looks_frozen.jsonl"
    link.symlink_to( live )

    with pytest.raises( FZ.LivePathRefused ):
        FZ.assert_snapshot_is_not_live( str( link ), live_path=str( live ) )


def test_guard_raises_through_a_dotdot_segment( tmp_path ):
    """`<dir>/sub/../dm_traffic.jsonl` is the live file; the guard must say so."""
    live = tmp_path / "dm_traffic.jsonl"
    live.write_text( "" )
    ( tmp_path / "sub" ).mkdir()
    sneaky = str( tmp_path / "sub" / ".." / "dm_traffic.jsonl" )

    with pytest.raises( FZ.LivePathRefused ):
        FZ.assert_snapshot_is_not_live( sneaky, live_path=str( live ) )


def test_guard_raises_on_a_HARD_LINK_to_the_live_corpus( tmp_path ):
    """
    The bind-mount case in miniature. `/var/lupin/dm-corpus` and the host's
    `projects-data/lupin/dm-corpus` are the same bytes under two paths whose
    realpaths compare UNEQUAL — only inode identity catches that.
    """
    live = tmp_path / "dm_traffic.jsonl"
    live.write_text( json.dumps( _row( LONG_BODY ) ) + "\n" )
    linked = tmp_path / "elsewhere.jsonl"
    os.link( str( live ), str( linked ) )

    assert os.path.realpath( str( linked ) ) != os.path.realpath( str( live ) )   # paths differ...
    with pytest.raises( FZ.LivePathRefused ) as excinfo:
        FZ.assert_snapshot_is_not_live( str( linked ), live_path=str( live ) )    # ...bytes do not
    assert "SAME FILE" in str( excinfo.value )


def test_file_identity_returns_none_for_a_missing_path( tmp_path ):
    """A snapshot that has not been written yet cannot be the live file."""
    assert FZ._file_identity( str( tmp_path / "nope.jsonl" ) ) is None


def test_guard_passes_when_the_live_corpus_does_not_exist( tmp_path ):
    """Neither file exists: two Nones must not compare equal into a false refusal."""
    got = FZ.assert_snapshot_is_not_live( str( tmp_path / "snap.jsonl" ), live_path=str( tmp_path / "live.jsonl" ) )
    assert got == os.path.realpath( str( tmp_path / "snap.jsonl" ) )


def test_guard_returns_realpath_for_a_genuine_snapshot( tmp_path ):
    """The happy path returns the resolved snapshot path rather than None."""
    live = tmp_path / "dm_traffic.jsonl"
    live.write_text( "" )
    snap = tmp_path / "frozen" / "dm_replay_frozen.jsonl"

    got = FZ.assert_snapshot_is_not_live( str( snap ), live_path=str( live ) )
    assert got == os.path.realpath( str( snap ) )


# ─────────────────────────────────────────────────────────────────────────────
# CHECKSUMS + THE MANIFEST
# ─────────────────────────────────────────────────────────────────────────────

def test_sha256_of_rows_matches_the_bytes_written( tmp_path ):
    """The manifest checksum must be re-derivable from the file on disk."""
    rows = [ _row( LONG_BODY ), _row( SHORT_BODY ) ]
    out  = tmp_path / "snap.jsonl"
    FZ.write_snapshot( rows, str( out ) )

    assert FZ.sha256_of_file( str( out ) ) == FZ.sha256_of_rows( rows )


def test_sha256_of_file_changes_when_a_byte_changes( tmp_path ):
    """A checksum that cannot go red is not a checksum."""
    one = tmp_path / "a.txt"; one.write_text( "alpha" )
    two = tmp_path / "b.txt"; two.write_text( "alphb" )
    assert FZ.sha256_of_file( str( one ) ) != FZ.sha256_of_file( str( two ) )


def test_read_corpus_rows_counts_unparseable_lines_and_ignores_blanks( tmp_path ):
    """A truncated tail (the writer appending mid-read) is counted, not fatal."""
    path = tmp_path / "dm_traffic.jsonl"
    path.write_text(
        json.dumps( _row( SHORT_BODY ) ) + "\n"
        + "\n"
        + '{"ts": "2026-08-17T10:00:0'          # truncated by a concurrent append
        + "\n"
    )
    rows, skipped = FZ.read_corpus_rows( str( path ) )
    assert len( rows ) == 1
    assert skipped    == 1


def test_freeze_writes_snapshot_and_manifest_with_full_provenance( tmp_path ):
    """Source path + timestamp + row count + checksum — all four, per the work order."""
    live_dir = tmp_path / "live"; live_dir.mkdir()
    live     = live_dir / "dm_traffic.jsonl"
    live.write_text(
        json.dumps( _row( LONG_BODY ) ) + "\n"
        + json.dumps( _row( SHORT_BODY ) ) + "\n"
        + json.dumps( _row( LONG_BODY, sender="rio" ) ) + "\n"
    )
    out_dir = tmp_path / "frozen"

    manifest = FZ.freeze( out_dir=str( out_dir ), live_path=str( live ), now="2026-08-17T18:00:00+00:00" )

    assert manifest[ "source_path" ]        == str( live )
    assert manifest[ "frozen_at_utc" ]      == "2026-08-17T18:00:00+00:00"
    assert manifest[ "source_row_count" ]   == 3
    assert manifest[ "source_sha256" ]      == FZ.sha256_of_file( str( live ) )
    assert manifest[ "snapshot_row_count" ] == 2                    # only the two over-trigger bodies
    assert manifest[ "manifest_version" ]   == FZ.MANIFEST_VERSION
    assert manifest[ "selection" ][ "trigger_claims" ] == 4

    snap = out_dir / "dm_replay_frozen.jsonl"
    assert snap.exists()
    assert ( out_dir / "manifest.json" ).exists()
    assert FZ.sha256_of_file( str( snap ) ) == manifest[ "snapshot_sha256" ]


def test_freeze_all_rows_keeps_the_under_trigger_bodies( tmp_path ):
    """--all-rows is a real switch, not decoration."""
    live_dir = tmp_path / "live"; live_dir.mkdir()
    live     = live_dir / "dm_traffic.jsonl"
    live.write_text( json.dumps( _row( LONG_BODY ) ) + "\n" + json.dumps( _row( SHORT_BODY ) ) + "\n" )

    manifest = FZ.freeze( out_dir=str( tmp_path / "f" ), live_path=str( live ), eligible_only=False )
    assert manifest[ "snapshot_row_count" ] == 2


def test_verify_snapshot_passes_on_a_fresh_freeze( tmp_path ):
    live_dir = tmp_path / "live"; live_dir.mkdir()
    live     = live_dir / "dm_traffic.jsonl"
    live.write_text( json.dumps( _row( LONG_BODY ) ) + "\n" )
    out_dir = tmp_path / "frozen"
    FZ.freeze( out_dir=str( out_dir ), live_path=str( live ) )

    ok, detail = FZ.verify_snapshot( str( out_dir / "dm_replay_frozen.jsonl" ), str( out_dir / "manifest.json" ) )
    assert ok, detail


def test_verify_snapshot_catches_a_tampered_row( tmp_path ):
    """Editing one body after the freeze must fail verification, naming the sha."""
    live_dir = tmp_path / "live"; live_dir.mkdir()
    live     = live_dir / "dm_traffic.jsonl"
    live.write_text( json.dumps( _row( LONG_BODY ) ) + "\n" )
    out_dir = tmp_path / "frozen"
    FZ.freeze( out_dir=str( out_dir ), live_path=str( live ) )

    snap = out_dir / "dm_replay_frozen.jsonl"
    row  = json.loads( snap.read_text().strip() )
    row[ "body" ] = row[ "body" ] + " A sixth claim was smuggled in."
    snap.write_text( json.dumps( row, sort_keys=True, ensure_ascii=False ) + "\n" )

    ok, detail = FZ.verify_snapshot( str( snap ), str( out_dir / "manifest.json" ) )
    assert not ok
    assert "sha256" in detail


def test_verify_snapshot_catches_an_appended_row( tmp_path ):
    """A row count that grew after the freeze is the exact drift the freeze prevents."""
    live_dir = tmp_path / "live"; live_dir.mkdir()
    live     = live_dir / "dm_traffic.jsonl"
    live.write_text( json.dumps( _row( LONG_BODY ) ) + "\n" )
    out_dir = tmp_path / "frozen"
    FZ.freeze( out_dir=str( out_dir ), live_path=str( live ) )

    snap = out_dir / "dm_replay_frozen.jsonl"
    with open( snap, "a", encoding="utf-8" ) as handle:
        handle.write( json.dumps( _row( LONG_BODY, sender="late" ), sort_keys=True ) + "\n" )

    ok, detail = FZ.verify_snapshot( str( snap ), str( out_dir / "manifest.json" ) )
    assert not ok
    assert "row count" in detail


def test_verify_snapshot_reports_an_unparseable_line( tmp_path ):
    live_dir = tmp_path / "live"; live_dir.mkdir()
    live     = live_dir / "dm_traffic.jsonl"
    live.write_text( json.dumps( _row( LONG_BODY ) ) + "\n" )
    out_dir = tmp_path / "frozen"
    FZ.freeze( out_dir=str( out_dir ), live_path=str( live ) )

    snap = out_dir / "dm_replay_frozen.jsonl"
    with open( snap, "a", encoding="utf-8" ) as handle:
        handle.write( "{not json\n" )

    ok, detail = FZ.verify_snapshot( str( snap ), str( out_dir / "manifest.json" ) )
    assert not ok
    assert "unparseable" in detail


# ─────────────────────────────────────────────────────────────────────────────
# SELECTION + SAMPLING
# ─────────────────────────────────────────────────────────────────────────────

def test_select_eligible_uses_strictly_greater_than_the_trigger():
    """The router returns early on `claims_in <= trigger`; selection must agree."""
    exactly_four = "One claim. Two claims. Three claims. Four claims."
    five         = exactly_four + " Five claims."

    assert FZ.count_claims( exactly_four ) == 4
    kept = FZ.select_eligible( [ _row( exactly_four ), _row( five ) ], 4 )
    assert len( kept ) == 1
    assert kept[ 0 ][ "body" ] == five


def test_select_eligible_drops_blank_bodies():
    kept = FZ.select_eligible( [ _row( "" ), _row( "   " ), _row( LONG_BODY ) ], 4 )
    assert len( kept ) == 1


def test_select_eligible_preserves_corpus_order():
    rows = [ _row( LONG_BODY, sender=str( i ) ) for i in range( 5 ) ]
    kept = FZ.select_eligible( rows, 4 )
    assert [ r[ "from" ] for r in kept ] == [ "0", "1", "2", "3", "4" ]


def test_count_claims_is_the_ROUTERS_OWN_counter():
    """
    Not a copy. The study's idea of "eligible" and the tutor's idea of "fires"
    must be the same function, or the frozen set drifts from what the tutor does.
    """
    from cosa.rest.routers.dm import _count_claims

    for body in ( LONG_BODY, SHORT_BODY, "", "One. Two. Three. Four. Five. Six." ):
        assert FZ.count_claims( body ) == _count_claims( body )


def test_sample_rows_is_deterministic_for_a_seed():
    rows = [ _row( LONG_BODY, sender=str( i ) ) for i in range( 100 ) ]
    a = FZ.sample_rows( rows, 10, 42 )
    b = FZ.sample_rows( rows, 10, 42 )
    c = FZ.sample_rows( rows, 10, 43 )

    assert [ r[ "from" ] for r in a ] == [ r[ "from" ] for r in b ]
    assert [ r[ "from" ] for r in a ] != [ r[ "from" ] for r in c ]
    assert len( a ) == 10


def test_sample_rows_preserves_corpus_order():
    rows   = [ _row( LONG_BODY, sender=str( i ) ) for i in range( 50 ) ]
    picked = FZ.sample_rows( rows, 8, 7 )
    order  = [ int( r[ "from" ] ) for r in picked ]
    assert order == sorted( order )


def test_sample_rows_returns_everything_when_sample_is_none_or_too_big():
    rows = [ _row( LONG_BODY ) for _ in range( 5 ) ]
    assert len( FZ.sample_rows( rows, None, 1 ) ) == 5
    assert len( FZ.sample_rows( rows, 99, 1 ) )   == 5


def test_sample_rows_does_not_mutate_the_input():
    rows = [ _row( LONG_BODY, sender=str( i ) ) for i in range( 20 ) ]
    FZ.sample_rows( rows, 3, 1 )
    assert len( rows ) == 20


def test_freeze_records_the_sample_parameters_in_the_manifest( tmp_path ):
    """A sample nobody can reproduce is not evidence."""
    live_dir = tmp_path / "live"; live_dir.mkdir()
    live     = live_dir / "dm_traffic.jsonl"
    live.write_text( "".join( json.dumps( _row( LONG_BODY, sender=str( i ) ) ) + "\n" for i in range( 20 ) ) )

    manifest = FZ.freeze( out_dir=str( tmp_path / "f" ), live_path=str( live ), sample_size=5, seed=99 )
    assert manifest[ "selection" ][ "sample_size" ] == 5
    assert manifest[ "selection" ][ "seed" ]        == 99
    assert manifest[ "snapshot_row_count" ]         == 5


def test_current_git_sha_returns_a_string_or_none():
    """Provenance is best-effort — a missing sha must never abort a freeze."""
    sha = FZ.current_git_sha()
    assert sha is None or isinstance( sha, str )


def test_current_git_sha_swallows_a_failure( monkeypatch ):
    monkeypatch.setattr( FZ.subprocess, "run", lambda *a, **k: ( _ for _ in () ).throw( OSError( "no git" ) ) )
    assert FZ.current_git_sha() is None


def test_write_snapshot_creates_missing_parent_directories( tmp_path ):
    out = tmp_path / "deep" / "deeper" / "snap.jsonl"
    FZ.write_snapshot( [ _row( LONG_BODY ) ], str( out ) )
    assert out.exists()


# ─────────────────────────────────────────────────────────────────────────────
# AN EMPTY FREEZE IS NOT A CLEAN FREEZE
# ─────────────────────────────────────────────────────────────────────────────

def test_freeze_refuses_a_zero_row_replay_set( tmp_path ):
    """
    500 under-trigger rows select down to nothing. Without this the manifest
    records an empty study input as a clean run and --verify agrees.
    """
    live_dir = tmp_path / "live"; live_dir.mkdir()
    live     = live_dir / "dm_traffic.jsonl"
    live.write_text( "".join( json.dumps( _row( SHORT_BODY ) ) + "\n" for _ in range( 500 ) ) )

    with pytest.raises( FZ.EmptyReplaySet ) as excinfo:
        FZ.freeze( out_dir=str( tmp_path / "frozen" ), live_path=str( live ) )

    assert "0 row(s) from 500 source rows" in str( excinfo.value )
    assert "fails open to 0" in str( excinfo.value )
    assert not ( tmp_path / "frozen" / "manifest.json" ).exists(), "an empty freeze must leave no manifest"


def test_freeze_honours_a_higher_minimum( tmp_path ):
    """A sample smaller than the pre-stated minimum is refused too."""
    live_dir = tmp_path / "live"; live_dir.mkdir()
    live     = live_dir / "dm_traffic.jsonl"
    live.write_text( "".join( json.dumps( _row( LONG_BODY ) ) + "\n" for _ in range( 10 ) ) )

    with pytest.raises( FZ.EmptyReplaySet ):
        FZ.freeze( out_dir=str( tmp_path / "f" ), live_path=str( live ), sample_size=3, minimum_rows=6 )


def test_verify_snapshot_fails_a_zero_row_snapshot( tmp_path ):
    """
    A hand-built empty snapshot is internally consistent — its checksum and row
    count match its manifest perfectly — and still measures nothing.
    """
    out_dir = tmp_path / "frozen"; out_dir.mkdir()
    snap    = out_dir / "dm_replay_frozen.jsonl"
    snap.write_text( "" )
    ( out_dir / "manifest.json" ).write_text( json.dumps( {
        "snapshot_row_count" : 0,
        "snapshot_sha256"    : FZ.sha256_of_rows( [] ),
        "minimum_rows"       : 1,
    } ) )

    ok, detail = FZ.verify_snapshot( str( snap ), str( out_dir / "manifest.json" ) )
    assert not ok
    assert "under the minimum" in detail


def test_manifest_records_the_minimum_it_was_frozen_under( tmp_path ):
    live_dir = tmp_path / "live"; live_dir.mkdir()
    live     = live_dir / "dm_traffic.jsonl"
    live.write_text( "".join( json.dumps( _row( LONG_BODY ) ) + "\n" for _ in range( 5 ) ) )

    manifest = FZ.freeze( out_dir=str( tmp_path / "f" ), live_path=str( live ), minimum_rows=3 )
    assert manifest[ "minimum_rows" ]     == 3
    assert manifest[ "manifest_version" ] == 2


# ─────────────────────────────────────────────────────────────────────────────
# THE SOURCE MOVED WHILE WE READ IT
# ─────────────────────────────────────────────────────────────────────────────

def test_freeze_refuses_when_the_source_grew_mid_read( tmp_path, monkeypatch ):
    """
    The corpus gains ~5 rows/min. A digest taken before the read would pin bytes
    nobody replayed; the second checksum is what catches that.
    """
    live_dir = tmp_path / "live"; live_dir.mkdir()
    live     = live_dir / "dm_traffic.jsonl"
    live.write_text( json.dumps( _row( LONG_BODY ) ) + "\n" )

    real_read = FZ.read_corpus_rows

    def read_then_append( path ):
        rows = real_read( path )
        with open( path, "a", encoding="utf-8" ) as handle:          # the fleet, mid-read
            handle.write( json.dumps( _row( LONG_BODY, sender="late" ) ) + "\n" )
        return rows

    monkeypatch.setattr( FZ, "read_corpus_rows", read_then_append )

    with pytest.raises( FZ.SourceChangedDuringRead ) as excinfo:
        FZ.freeze( out_dir=str( tmp_path / "f" ), live_path=str( live ) )
    assert "changed while it was being read" in str( excinfo.value )


# ─────────────────────────────────────────────────────────────────────────────
# THE CLI — tested, not pragma'd
# ─────────────────────────────────────────────────────────────────────────────

def _seed_live( tmp_path, n=4 ):
    live_dir = tmp_path / "live"; live_dir.mkdir()
    live     = live_dir / "dm_traffic.jsonl"
    live.write_text( "".join( json.dumps( _row( LONG_BODY, sender=str( i ) ) ) + "\n" for i in range( n ) ) )
    return live


def test_main_freezes_and_prints_the_manifest( tmp_path, monkeypatch ):
    live = _seed_live( tmp_path )
    monkeypatch.setattr( FZ, "resolve_live_corpus_path", lambda: str( live ) )

    printed = []
    code    = FZ.main( [ "--out-dir", str( tmp_path / "frozen" ) ], printer=printed.append )

    assert code == 0
    manifest = json.loads( printed[ 0 ] )
    assert manifest[ "snapshot_row_count" ] == 4
    assert ( tmp_path / "frozen" / "dm_replay_frozen.jsonl" ).exists()


def test_main_verify_returns_zero_on_a_good_snapshot( tmp_path, monkeypatch ):
    live = _seed_live( tmp_path )
    monkeypatch.setattr( FZ, "resolve_live_corpus_path", lambda: str( live ) )
    out_dir = tmp_path / "frozen"
    FZ.main( [ "--out-dir", str( out_dir ) ], printer=lambda *a: None )

    printed = []
    code    = FZ.main( [ "--out-dir", str( out_dir ), "--verify" ], printer=printed.append )
    assert code == 0
    assert "OK" in printed[ 0 ]


def test_main_verify_returns_one_on_a_tampered_snapshot( tmp_path, monkeypatch ):
    live = _seed_live( tmp_path )
    monkeypatch.setattr( FZ, "resolve_live_corpus_path", lambda: str( live ) )
    out_dir = tmp_path / "frozen"
    FZ.main( [ "--out-dir", str( out_dir ) ], printer=lambda *a: None )

    with open( out_dir / "dm_replay_frozen.jsonl", "a", encoding="utf-8" ) as handle:
        handle.write( json.dumps( _row( LONG_BODY, sender="late" ) ) + "\n" )

    printed = []
    code    = FZ.main( [ "--out-dir", str( out_dir ), "--verify" ], printer=printed.append )
    assert code == 1
    assert "FAIL" in printed[ 0 ]


def test_main_passes_the_sample_and_seed_through( tmp_path, monkeypatch ):
    live = _seed_live( tmp_path, n=20 )
    monkeypatch.setattr( FZ, "resolve_live_corpus_path", lambda: str( live ) )

    printed = []
    FZ.main( [ "--out-dir", str( tmp_path / "f" ), "--sample", "5", "--seed", "77" ], printer=printed.append )
    manifest = json.loads( printed[ 0 ] )
    assert manifest[ "selection" ][ "sample_size" ] == 5
    assert manifest[ "selection" ][ "seed" ]        == 77


def test_main_all_rows_switch( tmp_path, monkeypatch ):
    live_dir = tmp_path / "live"; live_dir.mkdir()
    live     = live_dir / "dm_traffic.jsonl"
    live.write_text( json.dumps( _row( LONG_BODY ) ) + "\n" + json.dumps( _row( SHORT_BODY ) ) + "\n" )
    monkeypatch.setattr( FZ, "resolve_live_corpus_path", lambda: str( live ) )

    printed = []
    FZ.main( [ "--out-dir", str( tmp_path / "f" ), "--all-rows" ], printer=printed.append )
    assert json.loads( printed[ 0 ] )[ "snapshot_row_count" ] == 2
