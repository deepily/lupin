"""
Unit tests for src/scripts/migrate_solution_snapshots.py — the snapshot user_id migrator.

WHY THIS FILE EXISTS (row e2099400): `src/scripts` is entering the coverage frame, and this
module sat at ZERO — 154 statements, nothing measured (Tiberius's census, 2026-08-29, a full
unit tier with --cov=src/scripts at 31b2cfce). These are behaviour tests, not a coverage
veneer: every assertion names something the migrator must do, and the mutation table on the
row records which named test reddens when each behaviour is broken.

⚠️ THE ISOLATION HAZARD, AND WHY THE FIXTURE IS AUTOUSE.
`save_snapshot` REWRITES snapshot files in place, and `migrate_all` walks every `*.json` under
`<project_root>/src/conf/long-term-memory/solutions` and rewrites each one. The project root
comes from `du.get_project_root()`, which reads `LUPIN_ROOT` at call time — so the lever is
`monkeypatch.setenv( "LUPIN_ROOT", ... )`: process-local, restored automatically, and it moves
the WHOLE resolution rather than one module's reference to it.

Deliberately NOT `monkeypatch.setattr( mod.du, "get_project_root", ... )`. `mod.du` IS the
shared `cosa.utils.util` module object, so patching an attribute on it leaks into every other
module in the process that imported the same utility.

The redirect is autouse so a test cannot reach the real tree by forgetting a fixture — the
failure has to be opted out of, not opted into. Two tests assert the redirect itself rather
than trusting it.

MEASURED, so the hazard is stated at its true size rather than dramatised: the `solutions/`
directory does not exist in this checkout today, so `migrate_all` returns early here. The
guard is not therefore optional — it is what makes these tests give the same answer on a box
that HAS one.
"""

import json
import os
import sys
from pathlib import Path

import pytest


def _load_module():
    """Import the script under its real name (src/scripts on path) so coverage targets the file."""
    root        = os.environ[ "LUPIN_ROOT" ]
    scripts_dir = os.path.join( root, "src", "scripts" )
    if scripts_dir not in sys.path:
        sys.path.insert( 0, scripts_dir )
    import migrate_solution_snapshots
    return migrate_solution_snapshots


mod = _load_module()


# ── fixtures ─────────────────────────────────────────────────────────────────────

@pytest.fixture( autouse=True )
def fake_root( tmp_path, monkeypatch ):
    """
    Point LUPIN_ROOT at a temp tree for EVERY test in this file.

    Autouse on purpose: this module rewrites files in place, so reaching the real
    checkout must not be reachable by omission.
    """
    root = tmp_path / "root"
    root.mkdir()
    monkeypatch.setenv( "LUPIN_ROOT", str( root ) )
    return root


@pytest.fixture
def solutions_dir( fake_root ):
    """The directory the module will compute — asserted equal, not assumed."""
    path = fake_root / "src" / "conf" / "long-term-memory" / "solutions"
    path.mkdir( parents=True )
    assert mod.SolutionSnapshotMigrator().get_solutions_directory() == path
    return path


def _snapshot( **overrides ):
    """A minimally-valid solution snapshot: the three fields needs_migration requires."""
    data = { "question": "what is 2+2", "answer": "4", "id_hash": "abc123" }
    data.update( overrides )
    return data


def _write( path, data ):
    path.parent.mkdir( parents=True, exist_ok=True )
    path.write_text( json.dumps( data ), encoding="utf-8" )
    return path


def _read( path ):
    return json.loads( path.read_text( encoding="utf-8" ) )


# ── the isolation guard itself ───────────────────────────────────────────────────

def test_the_redirect_moves_the_resolved_project_root( fake_root ):
    """The guard is asserted, not assumed: a zero-damage run and a broken redirect look alike."""
    import cosa.utils.util as du
    assert du.get_project_root() == str( fake_root )


def test_the_redirect_never_resolves_into_the_real_checkout( fake_root ):
    """A redirect that still pointed at the developer's tree would pass every other test here."""
    import cosa.utils.util as du
    computed = du.get_project_root() + mod.SolutionSnapshotMigrator.SOLUTIONS_DIR
    assert str( fake_root ) in computed
    assert "/projects/lupin/src/conf" not in computed


# ── construction ─────────────────────────────────────────────────────────────────

def test_a_new_migrator_starts_with_every_counter_at_zero():
    migrator = mod.SolutionSnapshotMigrator()
    assert migrator.stats == {
        "total_files"    : 0,
        "migrated_files" : 0,
        "skipped_files"  : 0,
        "error_files"    : 0,
        "backup_files"   : 0,
    }
    assert migrator.dry_run is False
    assert migrator.create_backup is False
    assert migrator.debug is False


def test_the_flags_are_carried_as_given():
    migrator = mod.SolutionSnapshotMigrator( dry_run=True, create_backup=True, debug=True )
    assert ( migrator.dry_run, migrator.create_backup, migrator.debug ) == ( True, True, True )


# ── logging ──────────────────────────────────────────────────────────────────────

def test_log_prefixes_the_level( capsys ):
    mod.SolutionSnapshotMigrator().log( "hello" )
    assert "[INFO] hello" in capsys.readouterr().out


def test_log_carries_an_explicit_level( capsys ):
    mod.SolutionSnapshotMigrator().log( "boom", "ERROR" )
    assert "[ERROR] boom" in capsys.readouterr().out


def test_debug_log_is_silent_when_debug_is_off( capsys ):
    mod.SolutionSnapshotMigrator( debug=False ).debug_log( "detail" )
    assert capsys.readouterr().out == ""


def test_debug_log_speaks_when_debug_is_on( capsys ):
    mod.SolutionSnapshotMigrator( debug=True ).debug_log( "detail" )
    assert "[DEBUG] detail" in capsys.readouterr().out


# ── locating the solutions directory ─────────────────────────────────────────────

def test_get_solutions_directory_returns_the_path_when_it_exists( solutions_dir ):
    assert mod.SolutionSnapshotMigrator().get_solutions_directory() == solutions_dir


def test_get_solutions_directory_raises_when_the_directory_is_absent( fake_root ):
    """Absent is the state of this checkout today, so the raising arm is the live one."""
    with pytest.raises( FileNotFoundError ) as info:
        mod.SolutionSnapshotMigrator().get_solutions_directory()
    assert "Solutions directory not found" in str( info.value )


# ── finding files ────────────────────────────────────────────────────────────────

def test_find_snapshot_files_returns_every_json_sorted( solutions_dir ):
    _write( solutions_dir / "b.json", _snapshot() )
    _write( solutions_dir / "a.json", _snapshot() )
    ( solutions_dir / "notes.txt" ).write_text( "not json", encoding="utf-8" )

    found = mod.SolutionSnapshotMigrator().find_snapshot_files( solutions_dir )
    assert [ p.name for p in found ] == [ "a.json", "b.json" ]


class _FixedOrderDir:
    """
    A stand-in for the solutions directory whose rglob yields a KNOWN, reversed order.

    The plain sorted-order test above cannot pin sorting on its own: `rglob` happened to
    return these two names already in order on this filesystem, so removing `sorted()`
    left it green — measured, as mutation M5, and this test is the answer to that survivor.
    Feeding a deterministic reversed order is what makes the sort observable.

    A stub is used rather than patching `rglob` on the Path instance because `pathlib.Path`
    uses __slots__ (no instance attribute to set) and patching the CLASS would leak into
    every other module in the process.
    """

    def __init__( self, entries ):
        self._entries = entries

    def rglob( self, pattern ):
        assert pattern == "*.json", "the module must ask for json files, not everything"
        return iter( self._entries )


def test_find_snapshot_files_sorts_what_the_filesystem_hands_it_out_of_order( solutions_dir ):
    """Removing sorted() must redden something; without a controlled order it did not."""
    a = _write( solutions_dir / "a.json", _snapshot() )
    b = _write( solutions_dir / "b.json", _snapshot() )

    found = mod.SolutionSnapshotMigrator().find_snapshot_files( _FixedOrderDir( [ b, a ] ) )
    assert [ p.name for p in found ] == [ "a.json", "b.json" ]


def test_find_snapshot_files_recurses_into_subdirectories( solutions_dir ):
    _write( solutions_dir / "nested" / "deep.json", _snapshot() )
    found = mod.SolutionSnapshotMigrator().find_snapshot_files( solutions_dir )
    assert [ p.name for p in found ] == [ "deep.json" ]


def test_find_snapshot_files_skips_a_directory_named_like_a_file( solutions_dir ):
    """rglob matches directories too; the is_file filter is the thing under test."""
    ( solutions_dir / "decoy.json" ).mkdir()
    _write( solutions_dir / "real.json", _snapshot() )

    found = mod.SolutionSnapshotMigrator().find_snapshot_files( solutions_dir )
    assert [ p.name for p in found ] == [ "real.json" ]


def test_find_snapshot_files_reports_its_count_in_debug( solutions_dir, capsys ):
    _write( solutions_dir / "a.json", _snapshot() )
    mod.SolutionSnapshotMigrator( debug=True ).find_snapshot_files( solutions_dir )
    assert "Found 1 JSON files" in capsys.readouterr().out


# ── loading ──────────────────────────────────────────────────────────────────────

def test_load_snapshot_returns_the_parsed_document( solutions_dir ):
    path = _write( solutions_dir / "a.json", _snapshot() )
    assert mod.SolutionSnapshotMigrator().load_snapshot( path ) == _snapshot()


def test_load_snapshot_raises_a_value_error_naming_the_file_on_bad_json( solutions_dir ):
    path = solutions_dir / "broken.json"
    path.write_text( "{ not json", encoding="utf-8" )

    with pytest.raises( ValueError ) as info:
        mod.SolutionSnapshotMigrator().load_snapshot( path )
    assert "broken.json" in str( info.value )


def test_load_snapshot_reports_the_filename_in_debug( solutions_dir, capsys ):
    path = _write( solutions_dir / "a.json", _snapshot() )
    mod.SolutionSnapshotMigrator( debug=True ).load_snapshot( path )
    assert "Loaded snapshot: a.json" in capsys.readouterr().out


# ── deciding what needs migrating ────────────────────────────────────────────────

def test_a_snapshot_without_user_id_needs_migration():
    assert mod.SolutionSnapshotMigrator().needs_migration( _snapshot() ) is True


def test_a_snapshot_that_already_has_user_id_is_left_alone():
    assert mod.SolutionSnapshotMigrator().needs_migration( _snapshot( user_id="someone" ) ) is False


@pytest.mark.parametrize( "missing", [ "question", "answer", "id_hash" ] )
def test_a_document_missing_any_required_field_is_not_a_snapshot( missing ):
    """Each field separately: a loop that stopped at the first would still pass one case."""
    data = _snapshot()
    del data[ missing ]
    assert mod.SolutionSnapshotMigrator().needs_migration( data ) is False


def test_the_skip_reason_is_visible_in_debug( capsys ):
    mod.SolutionSnapshotMigrator( debug=True ).needs_migration( _snapshot( user_id="someone" ) )
    assert "already has user_id" in capsys.readouterr().out


def test_the_missing_field_is_named_in_debug( capsys ):
    data = _snapshot()
    del data[ "answer" ]
    mod.SolutionSnapshotMigrator( debug=True ).needs_migration( data )
    assert "missing required field 'answer'" in capsys.readouterr().out


# ── the migration itself ─────────────────────────────────────────────────────────

def test_migrate_snapshot_adds_the_default_user_id():
    migrated = mod.SolutionSnapshotMigrator().migrate_snapshot( _snapshot() )
    assert migrated[ "user_id" ] == mod.SolutionSnapshotMigrator.DEFAULT_USER_ID


def test_migrate_snapshot_does_not_mutate_its_input():
    """It returns a copy; a caller holding the original must not see the new key appear."""
    original = _snapshot()
    mod.SolutionSnapshotMigrator().migrate_snapshot( original )
    assert "user_id" not in original


def test_migrate_snapshot_preserves_every_existing_field():
    migrated = mod.SolutionSnapshotMigrator().migrate_snapshot( _snapshot( extra="keep me" ) )
    assert migrated[ "extra" ] == "keep me"
    assert migrated[ "question" ] == "what is 2+2"


def test_migrate_snapshot_announces_the_id_in_debug( capsys ):
    mod.SolutionSnapshotMigrator( debug=True ).migrate_snapshot( _snapshot() )
    assert mod.SolutionSnapshotMigrator.DEFAULT_USER_ID in capsys.readouterr().out


# ── saving ───────────────────────────────────────────────────────────────────────

def test_a_dry_run_leaves_the_file_byte_for_byte_unchanged( solutions_dir, capsys ):
    path   = _write( solutions_dir / "a.json", _snapshot() )
    before = path.read_bytes()

    mod.SolutionSnapshotMigrator( dry_run=True ).save_snapshot( path, _snapshot( user_id="x" ) )

    assert path.read_bytes() == before
    assert "DRY RUN: Would save" in capsys.readouterr().out


def test_a_real_save_writes_the_migrated_document( solutions_dir ):
    path = _write( solutions_dir / "a.json", _snapshot() )
    mod.SolutionSnapshotMigrator().save_snapshot( path, _snapshot( user_id="x" ) )
    assert _read( path )[ "user_id" ] == "x"


def test_no_backup_is_written_unless_it_was_asked_for( solutions_dir ):
    path = _write( solutions_dir / "a.json", _snapshot() )
    mod.SolutionSnapshotMigrator().save_snapshot( path, _snapshot( user_id="x" ) )
    assert not ( solutions_dir / "a.json.bak" ).exists()


def test_the_backup_holds_the_pre_migration_content( solutions_dir ):
    """A .bak that captured the NEW content would be worthless — assert it holds the OLD."""
    path = _write( solutions_dir / "a.json", _snapshot() )

    migrator = mod.SolutionSnapshotMigrator( create_backup=True )
    migrator.save_snapshot( path, _snapshot( user_id="x" ) )

    backup = solutions_dir / "a.json.bak"
    assert backup.exists()
    assert "user_id" not in _read( backup )
    assert migrator.stats[ "backup_files" ] == 1


def test_a_dry_run_writes_no_backup_either( solutions_dir ):
    path     = _write( solutions_dir / "a.json", _snapshot() )
    migrator = mod.SolutionSnapshotMigrator( dry_run=True, create_backup=True )
    migrator.save_snapshot( path, _snapshot( user_id="x" ) )

    assert not ( solutions_dir / "a.json.bak" ).exists()
    assert migrator.stats[ "backup_files" ] == 0


def test_the_written_file_keeps_unicode_unescaped( solutions_dir ):
    """ensure_ascii=False is the point: an escaped form would still parse but is not what it writes."""
    path = _write( solutions_dir / "a.json", _snapshot() )
    mod.SolutionSnapshotMigrator().save_snapshot( path, _snapshot( question="¿cuánto es 2+2?" ) )
    assert "¿cuánto es 2+2?" in path.read_text( encoding="utf-8" )


def test_saving_reports_the_path_in_debug( solutions_dir, capsys ):
    path = _write( solutions_dir / "a.json", _snapshot() )
    mod.SolutionSnapshotMigrator( debug=True ).save_snapshot( path, _snapshot( user_id="x" ) )
    assert "Saved migrated snapshot" in capsys.readouterr().out


def test_the_backup_path_is_reported_in_debug( solutions_dir, capsys ):
    path = _write( solutions_dir / "a.json", _snapshot() )
    mod.SolutionSnapshotMigrator( create_backup=True, debug=True ).save_snapshot(
        path, _snapshot( user_id="x" )
    )
    assert "Created backup" in capsys.readouterr().out


# ── one file end to end ──────────────────────────────────────────────────────────

def test_migrate_file_reports_true_and_writes_the_id( solutions_dir, capsys ):
    path = _write( solutions_dir / "a.json", _snapshot() )
    assert mod.SolutionSnapshotMigrator().migrate_file( path ) is True
    assert _read( path )[ "user_id" ] == mod.SolutionSnapshotMigrator.DEFAULT_USER_ID
    assert "MIGRATED: a.json" in capsys.readouterr().out


def test_migrate_file_reports_false_and_changes_nothing_when_already_migrated( solutions_dir, capsys ):
    path   = _write( solutions_dir / "a.json", _snapshot( user_id="someone" ) )
    before = path.read_bytes()

    assert mod.SolutionSnapshotMigrator().migrate_file( path ) is False

    assert path.read_bytes() == before
    assert "SKIPPED: a.json" in capsys.readouterr().out


def test_migrate_file_logs_and_re_raises_a_load_failure( solutions_dir, capsys ):
    path = solutions_dir / "broken.json"
    path.write_text( "{ not json", encoding="utf-8" )

    with pytest.raises( ValueError ):
        mod.SolutionSnapshotMigrator().migrate_file( path )
    assert "ERROR loading broken.json" in capsys.readouterr().out


def test_migrate_file_logs_and_re_raises_a_save_failure( solutions_dir, capsys, monkeypatch ):
    path = _write( solutions_dir / "a.json", _snapshot() )

    def _explode( *args, **kwargs ):
        raise OSError( "disk full" )

    monkeypatch.setattr( mod.SolutionSnapshotMigrator, "save_snapshot", _explode )

    with pytest.raises( OSError ):
        mod.SolutionSnapshotMigrator().migrate_file( path )
    assert "ERROR migrating a.json" in capsys.readouterr().out


# ── the whole run ────────────────────────────────────────────────────────────────

def test_migrate_all_counts_migrated_skipped_and_errored_separately( solutions_dir, capsys ):
    _write( solutions_dir / "needs.json", _snapshot() )
    _write( solutions_dir / "done.json",  _snapshot( user_id="someone" ) )
    ( solutions_dir / "broken.json" ).write_text( "{ not json", encoding="utf-8" )

    migrator = mod.SolutionSnapshotMigrator()
    migrator.migrate_all()

    assert migrator.stats[ "total_files" ]    == 3
    assert migrator.stats[ "migrated_files" ] == 1
    assert migrator.stats[ "skipped_files" ]  == 1
    assert migrator.stats[ "error_files" ]    == 1
    assert "Failed to process broken.json" in capsys.readouterr().out


def test_migrate_all_returns_quietly_when_the_directory_is_missing( fake_root, capsys ):
    migrator = mod.SolutionSnapshotMigrator()
    migrator.migrate_all()

    assert migrator.stats[ "total_files" ] == 0
    out = capsys.readouterr().out
    assert "FATAL" in out
    assert "MIGRATION SUMMARY" not in out, "a fatal directory error must not print a summary"


def test_migrate_all_stops_when_the_directory_holds_no_json( solutions_dir, capsys ):
    mod.SolutionSnapshotMigrator().migrate_all()

    out = capsys.readouterr().out
    assert "No JSON files found" in out
    assert "MIGRATION SUMMARY" not in out


def test_migrate_all_announces_dry_run_and_backup_modes( solutions_dir, capsys ):
    mod.SolutionSnapshotMigrator( dry_run=True, create_backup=True ).migrate_all()
    out = capsys.readouterr().out
    assert "DRY RUN MODE" in out
    assert "BACKUP MODE" in out


def test_a_dry_run_over_a_real_directory_writes_nothing( solutions_dir ):
    path   = _write( solutions_dir / "a.json", _snapshot() )
    before = path.read_bytes()

    mod.SolutionSnapshotMigrator( dry_run=True ).migrate_all()

    assert path.read_bytes() == before


# ── the summary ──────────────────────────────────────────────────────────────────

def _summary_of( capsys, **flags ):
    ctor     = { k: v for k, v in flags.items() if k in ( "dry_run", "create_backup" ) }
    migrator = mod.SolutionSnapshotMigrator( **ctor )
    migrator.stats.update( { k: v for k, v in flags.items() if k in migrator.stats } )
    migrator.print_summary()
    return capsys.readouterr().out


def test_the_summary_warns_when_anything_errored( capsys ):
    assert "WARNING: Some files had errors" in _summary_of( capsys, error_files=1, migrated_files=5 )


def test_a_dry_run_summary_tells_you_how_to_apply_it( capsys ):
    assert "Re-run without --dry-run" in _summary_of( capsys, migrated_files=2, dry_run=True )


def test_a_real_summary_reports_completion( capsys ):
    out = _summary_of( capsys, migrated_files=2 )
    assert "Migration completed successfully!" in out
    assert "Re-run without --dry-run" not in out


def test_a_no_op_summary_says_nothing_needed_migration( capsys ):
    assert "No files needed migration." in _summary_of( capsys )


def test_the_backup_count_is_only_printed_in_backup_mode( capsys ):
    assert "Backup files created" in _summary_of( capsys, create_backup=True, backup_files=3 )
    assert "Backup files created" not in _summary_of( capsys )


# ── the CLI ──────────────────────────────────────────────────────────────────────

def _run_main( monkeypatch, argv ):
    monkeypatch.setattr( sys, "argv", [ "migrate_solution_snapshots.py" ] + argv )
    return mod.main()


def test_main_defaults_to_a_live_run_with_no_backups( solutions_dir, monkeypatch ):
    path = _write( solutions_dir / "a.json", _snapshot() )
    _run_main( monkeypatch, [] )

    assert _read( path )[ "user_id" ] == mod.SolutionSnapshotMigrator.DEFAULT_USER_ID
    assert not ( solutions_dir / "a.json.bak" ).exists()


def test_main_honours_dry_run( solutions_dir, monkeypatch ):
    path   = _write( solutions_dir / "a.json", _snapshot() )
    before = path.read_bytes()

    _run_main( monkeypatch, [ "--dry-run" ] )

    assert path.read_bytes() == before


def test_main_honours_backup( solutions_dir, monkeypatch ):
    _write( solutions_dir / "a.json", _snapshot() )
    _run_main( monkeypatch, [ "--backup" ] )
    assert ( solutions_dir / "a.json.bak" ).exists()


def test_main_honours_debug( solutions_dir, monkeypatch, capsys ):
    _write( solutions_dir / "a.json", _snapshot() )
    _run_main( monkeypatch, [ "--debug" ] )
    assert "[DEBUG]" in capsys.readouterr().out


def test_main_exits_1_on_keyboard_interrupt( monkeypatch, capsys ):
    def _interrupt( self ):
        raise KeyboardInterrupt

    monkeypatch.setattr( mod.SolutionSnapshotMigrator, "migrate_all", _interrupt )

    with pytest.raises( SystemExit ) as info:
        _run_main( monkeypatch, [] )

    assert info.value.code == 1
    assert "interrupted by user" in capsys.readouterr().out


def test_main_exits_1_and_names_the_failure_on_any_other_error( monkeypatch, capsys ):
    def _explode( self ):
        raise RuntimeError( "something specific" )

    monkeypatch.setattr( mod.SolutionSnapshotMigrator, "migrate_all", _explode )

    with pytest.raises( SystemExit ) as info:
        _run_main( monkeypatch, [] )

    assert info.value.code == 1
    assert "something specific" in capsys.readouterr().out


def test_an_unknown_flag_is_rejected_rather_than_ignored( monkeypatch ):
    """argparse exits 2; a script that silently accepted --dryrun would run live."""
    with pytest.raises( SystemExit ) as info:
        _run_main( monkeypatch, [ "--dryrun" ] )
    assert info.value.code == 2


# ── the import-time bootstrap ────────────────────────────────────────────────────
#
# Lines 25-36 run ONCE, at import, before any test exists — so no ordinary test can reach
# the LUPIN_ROOT-missing arm or the sys.path insert. They are re-executed here from source
# under controlled conditions, which is the only honest way to cover an import-time guard:
# a pragma there would assert nothing and still read as complete.

def _exec_bootstrap( namespace_name="migrate_solution_snapshots_bootstrap_probe" ):
    """
    Re-execute the module's own source, compiled under its REAL filename so coverage
    attributes the lines to the file rather than to a synthetic one.

    The path is resolved from the ALREADY-IMPORTED module, never from LUPIN_ROOT — these
    tests manipulate that variable, so reading the path from it would point the probe at a
    directory the test just invented.
    """
    source_path = Path( mod.__file__ )
    code        = compile( source_path.read_text( encoding="utf-8" ), str( source_path ), "exec" )
    namespace   = { "__name__": namespace_name, "__file__": str( source_path ) }
    exec( code, namespace )
    return namespace


def test_the_bootstrap_raises_when_lupin_root_is_not_set( monkeypatch ):
    """
    A standalone run with no LUPIN_ROOT must die immediately with a usable message, not
    stumble on into os.path.join( None, 'src' ) and raise a bare TypeError.
    """
    monkeypatch.delenv( "LUPIN_ROOT", raising=False )

    with pytest.raises( RuntimeError ) as info:
        _exec_bootstrap()

    message = str( info.value )
    assert "LUPIN_ROOT environment variable not set" in message
    assert "export LUPIN_ROOT=" in message


def test_the_bootstrap_puts_src_on_sys_path_when_it_is_absent( monkeypatch, tmp_path ):
    """
    The insert arm never runs under pytest because conftest has already put src on the
    path. Pointing LUPIN_ROOT at a directory whose src is NOT on the path exercises it.
    """
    fake = tmp_path / "elsewhere"
    ( fake / "src" ).mkdir( parents=True )
    expected = os.path.join( str( fake ), "src" )

    original_path = list( sys.path )
    assert expected not in sys.path
    try:
        monkeypatch.setenv( "LUPIN_ROOT", str( fake ) )
        _exec_bootstrap()
        assert sys.path[ 0 ] == expected, "the bootstrap must insert at position 0, not append"
    finally:
        sys.path[ : ] = original_path

    assert expected not in sys.path


def test_the_bootstrap_does_not_insert_a_duplicate_when_src_is_already_present( monkeypatch ):
    """The `not in sys.path` guard: a second run must leave the path length unchanged."""
    root = os.environ[ "LUPIN_ROOT" ]
    src  = os.path.join( root, "src" )

    original_path = list( sys.path )
    try:
        sys.path.insert( 0, src )
        length_before = len( sys.path )
        _exec_bootstrap()
        assert len( sys.path ) == length_before
    finally:
        sys.path[ : ] = original_path
