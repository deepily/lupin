"""
The :8000 server's coverage of main.py, folded into the gate.

What each group pins:

  - the content hash equals what `git hash-object` prints, so staleness is about main.py's
    bytes and not the tree HEAD
  - every state of the server data that cannot be used gets a named reason, and the message
    names the scheduled run that produces the data
  - a fold takes only main.py's arcs from the server file, and leaves the target untouched on
    any reason other than ok
  - one fixture comes from the real producer, `coverage run --parallel-mode`, run over a
    stand-in main.py under a fake container root and read back through the real reader

Venue: :7999-eligible. No server, no network; every file lives under tmp_path.
"""

import json
import os
import sqlite3
import subprocess
import sys
from contextlib import closing

import coverage
import pytest

import cosa.utils.server_coverage as sc
import cosa.utils.util as cu

CONTAINER = "/var/lupin"
MAIN_SRC  = "import os\n\ndef boot( flag ):\n    if flag:\n        return 1\n    return 2\n\nboot( True )\n"


def _host_main( tmp_path, text=MAIN_SRC ):
    """A stand-in main.py in a fake host tree."""
    path = tmp_path / "host" / "src" / "lupin_app" / "main.py"
    path.parent.mkdir( parents=True, exist_ok=True )
    path.write_text( text )
    return str( path )


def _server_file( directory, files, name=".coverage.box.1.abc" ):
    """Write one parallel data file. `files` maps recorded path -> arcs, or None for lines only."""
    directory.mkdir( parents=True, exist_ok=True )
    data = coverage.CoverageData( basename=str( directory / name ) )
    for path, arcs in files.items():
        if arcs is None: data.add_lines( { path: [ 1, 2 ] } )
        else:            data.add_arcs( { path: arcs } )
    data.write()
    return str( directory / name )


def _boot( directory, main_py ):
    directory.mkdir( parents=True, exist_ok=True )
    ( directory / sc.BOOT_NAME ).write_text( json.dumps( { "main_py_hash": sc.blob_hash( main_py ) } ) )


CONTAINER_MAIN = f"{CONTAINER}/{sc.MAIN_PY_REL}"
ARCS           = [ ( -1, 1 ), ( 1, 3 ), ( 3, 4 ), ( 4, 5 ) ]


# ── paths and hashing ────────────────────────────────────────────────────────

def test_server_dir_defaults_under_the_project_root( monkeypatch ):
    monkeypatch.delenv( sc.DIR_ENV, raising=False )
    assert sc.server_dir( "/some/root" ) == "/some/root/io/coverage/server"
    assert sc.server_dir() == cu.get_project_root() + "/io/coverage/server"


def test_server_dir_honours_the_override( monkeypatch ):
    monkeypatch.setenv( sc.DIR_ENV, "/elsewhere" )
    assert sc.server_dir( "/some/root" ) == "/elsewhere"


def test_server_dir_ignores_an_empty_override( monkeypatch ):
    monkeypatch.setenv( sc.DIR_ENV, "" )
    assert sc.server_dir( "/r" ) == "/r/io/coverage/server"


def test_blob_hash_equals_git_hash_object( tmp_path ):
    path = _host_main( tmp_path )
    git  = subprocess.run( [ "git", "hash-object", path ], capture_output=True, text=True, check=True )
    assert sc.blob_hash( path ) == git.stdout.strip()


def test_blob_hash_changes_with_one_byte( tmp_path ):
    first  = sc.blob_hash( _host_main( tmp_path ) )
    second = sc.blob_hash( _host_main( tmp_path, MAIN_SRC + "#" ) )
    assert first != second


def test_blob_hash_of_a_missing_file_raises( tmp_path ):
    with pytest.raises( FileNotFoundError ):
        sc.blob_hash( str( tmp_path / "nope.py" ) )


# ── discovery, reset, boot ───────────────────────────────────────────────────

def test_data_files_lists_parallel_files_and_not_the_sidecar( tmp_path ):
    ( tmp_path / ".coverage.a" ).write_text( "" )
    ( tmp_path / ".coverage.b" ).write_text( "" )
    ( tmp_path / sc.BOOT_NAME ).write_text( "{}" )
    ( tmp_path / "notes.txt" ).write_text( "" )
    assert [ os.path.basename( f ) for f in sc.data_files( str( tmp_path ) ) ] == [ ".coverage.a", ".coverage.b" ]


def test_data_files_of_a_missing_directory_is_empty( tmp_path ):
    assert sc.data_files( str( tmp_path / "absent" ) ) == []


def test_reset_clears_data_and_sidecar_and_creates_the_directory( tmp_path ):
    directory = tmp_path / "srv"
    directory.mkdir()
    ( directory / ".coverage.old" ).write_text( "x" )
    ( directory / sc.BOOT_NAME ).write_text( "{}" )
    ( directory / "keep.txt" ).write_text( "k" )
    sc.reset( str( directory ) )
    assert os.listdir( directory ) == [ "keep.txt" ]
    sc.reset( str( tmp_path / "fresh" ) )
    assert ( tmp_path / "fresh" ).is_dir()


def test_write_boot_records_the_hash_and_clears_the_last_boots_data( tmp_path ):
    main_py   = _host_main( tmp_path )
    directory = tmp_path / "srv"
    directory.mkdir()
    ( directory / ".coverage.old" ).write_text( "x" )
    boot = json.loads( open( sc.write_boot( str( directory ), main_py ) ).read() )
    assert boot[ "main_py_hash" ] == sc.blob_hash( main_py )
    assert boot[ "boot_utc" ].endswith( "+00:00" )
    assert sc.data_files( str( directory ) ) == [], "the previous boot's data survived"


# ── the verdict: one test per reason ─────────────────────────────────────────

def _verdict( tmp_path, directory ):
    return sc.verdict( str( directory ), _host_main( tmp_path ), CONTAINER )


def test_verdict_ok_returns_the_arcs_with_the_hash_in_the_message( tmp_path ):
    main_py   = _host_main( tmp_path )
    directory = tmp_path / "srv"
    _server_file( directory, { CONTAINER_MAIN: ARCS } )
    _boot( directory, main_py )
    reason, message, arcs = sc.verdict( str( directory ), main_py, CONTAINER )
    assert reason == "ok"
    assert arcs == sorted( ARCS )
    assert sc.blob_hash( main_py )[ :12 ] in message


def test_verdict_unions_arcs_across_parallel_files( tmp_path ):
    main_py   = _host_main( tmp_path )
    directory = tmp_path / "srv"
    _server_file( directory, { CONTAINER_MAIN: [ ( -1, 1 ), ( 1, 3 ) ] }, ".coverage.box.1.a" )
    _server_file( directory, { CONTAINER_MAIN: [ ( 3, 4 ), ( 1, 3 ) ] }, ".coverage.box.2.b" )
    _boot( directory, main_py )
    reason, _, arcs = sc.verdict( str( directory ), main_py, CONTAINER )
    assert reason == "ok" and arcs == [ ( -1, 1 ), ( 1, 3 ), ( 3, 4 ) ]


def test_no_data_directory_is_no_data_and_names_the_scheduled_run( tmp_path ):
    reason, message, arcs = _verdict( tmp_path, tmp_path / "absent" )
    assert ( reason, arcs ) == ( "no-data", None )
    assert "LUPIN_SERVER_COVERAGE=1" in message and "/api/v2/submit" in message


def test_a_directory_with_only_a_sidecar_is_no_data( tmp_path ):
    directory = tmp_path / "srv"
    _boot( directory, _host_main( tmp_path ) )
    assert _verdict( tmp_path, directory )[ 0 ] == "no-data"


def test_data_without_a_sidecar_is_no_boot( tmp_path ):
    directory = tmp_path / "srv"
    _server_file( directory, { CONTAINER_MAIN: ARCS } )
    reason, message, _ = _verdict( tmp_path, directory )
    assert reason == "no-boot" and "/api/v2/submit" in message


@pytest.mark.parametrize( "text", [ "not json", "[]", "{}", '{"main_py_hash": 7}' ] )
def test_an_unusable_sidecar_is_bad_boot( tmp_path, text ):
    directory = tmp_path / "srv"
    _server_file( directory, { CONTAINER_MAIN: ARCS } )
    ( directory / sc.BOOT_NAME ).write_text( text )
    reason, message, _ = _verdict( tmp_path, directory )
    assert reason == "bad-boot" and "/api/v2/submit" in message


def test_a_sidecar_that_is_a_directory_is_bad_boot( tmp_path ):
    directory = tmp_path / "srv"
    _server_file( directory, { CONTAINER_MAIN: ARCS } )
    ( directory / sc.BOOT_NAME ).mkdir()
    assert _verdict( tmp_path, directory )[ 0 ] == "bad-boot"


def test_a_different_main_py_is_stale_and_names_both_hashes( tmp_path ):
    directory = tmp_path / "srv"
    new       = _host_main( tmp_path )
    old       = str( tmp_path / "old-main.py" )
    open( old, "w" ).write( MAIN_SRC + "# old\n" )
    _server_file( directory, { CONTAINER_MAIN: ARCS } )
    _boot( directory, old )
    reason, message, _ = sc.verdict( str( directory ), new, CONTAINER )
    assert reason == "stale"
    assert sc.blob_hash( old )[ :12 ] in message and sc.blob_hash( new )[ :12 ] in message
    assert "/api/v2/submit" in message


def test_a_new_commit_that_leaves_main_py_alone_is_not_stale( tmp_path ):
    """The reason staleness is keyed on content: HEAD moving must not matter."""
    main_py   = _host_main( tmp_path )
    directory = tmp_path / "srv"
    _server_file( directory, { CONTAINER_MAIN: ARCS } )
    _boot( directory, main_py )
    ( tmp_path / "host" / "src" / "other.py" ).write_text( "x = 1\n" )
    assert sc.verdict( str( directory ), main_py, CONTAINER )[ 0 ] == "ok"


def test_a_corrupt_data_file_is_unreadable( tmp_path ):
    main_py   = _host_main( tmp_path )
    directory = tmp_path / "srv"
    directory.mkdir()
    ( directory / ".coverage.bad" ).write_text( "this is not a database" )
    _boot( directory, main_py )
    reason, message, _ = sc.verdict( str( directory ), main_py, CONTAINER )
    assert reason == "unreadable" and "/api/v2/submit" in message


def test_a_data_file_with_nothing_measured_is_empty( tmp_path ):
    main_py   = _host_main( tmp_path )
    directory = tmp_path / "srv"
    path = _server_file( directory, { CONTAINER_MAIN: ARCS }, ".coverage.none" )
    with closing( sqlite3.connect( path ) ) as db:
        db.execute( "DELETE FROM file" )
        db.commit()
    _boot( directory, main_py )
    assert sc.verdict( str( directory ), main_py, CONTAINER )[ 0 ] == "empty"


def test_data_that_never_measured_main_py_is_main_missing( tmp_path ):
    main_py   = _host_main( tmp_path )
    directory = tmp_path / "srv"
    _server_file( directory, { f"{CONTAINER}/src/cosa/other.py": ARCS } )
    _boot( directory, main_py )
    assert sc.verdict( str( directory ), main_py, CONTAINER )[ 0 ] == "main-missing"


def test_main_py_measured_by_line_only_is_no_arcs( tmp_path ):
    main_py   = _host_main( tmp_path )
    directory = tmp_path / "srv"
    _server_file( directory, { CONTAINER_MAIN: None } )
    _boot( directory, main_py )
    assert sc.verdict( str( directory ), main_py, CONTAINER )[ 0 ] == "no-arcs"


def test_one_bad_file_among_good_ones_spoils_the_verdict( tmp_path ):
    main_py   = _host_main( tmp_path )
    directory = tmp_path / "srv"
    _server_file( directory, { CONTAINER_MAIN: ARCS }, ".coverage.box.1.a" )
    _server_file( directory, { f"{CONTAINER}/src/x.py": ARCS }, ".coverage.box.2.b" )
    _boot( directory, main_py )
    reason, message, _ = sc.verdict( str( directory ), main_py, CONTAINER )
    assert reason == "main-missing" and ".coverage.box.2.b" in message


# ── fold ─────────────────────────────────────────────────────────────────────

def _target_arcs( target, path ):
    data = coverage.CoverageData( basename=str( target ) )
    data.read()
    return data, ( data.arcs( path ) if path in data.measured_files() else None )


def test_fold_adds_only_main_pys_arcs_under_the_host_path( tmp_path ):
    main_py   = _host_main( tmp_path )
    directory = tmp_path / "srv"
    other     = f"{CONTAINER}/src/cosa/older_tree_file.py"
    _server_file( directory, { CONTAINER_MAIN: ARCS, other: [ ( 1, 2 ) ] } )
    _boot( directory, main_py )
    target = tmp_path / "gate.cov"
    seed   = coverage.CoverageData( basename=str( target ) )
    seed.add_arcs( { "/host/src/cosa/x.py": [ ( 1, 2 ) ] } )
    seed.write()
    reason, _ = sc.fold( str( directory ), main_py, str( target ), CONTAINER )
    data, arcs = _target_arcs( target, main_py )
    assert reason == "ok"
    assert sorted( arcs ) == sorted( ARCS )
    assert sorted( data.measured_files() ) == sorted( [ "/host/src/cosa/x.py", main_py ] ), \
        "a file other than main.py came across from the server data"


def test_fold_unions_with_main_py_arcs_the_tiers_already_hold( tmp_path ):
    main_py   = _host_main( tmp_path )
    directory = tmp_path / "srv"
    _server_file( directory, { CONTAINER_MAIN: [ ( 3, 4 ) ] } )
    _boot( directory, main_py )
    target = tmp_path / "gate.cov"
    seed   = coverage.CoverageData( basename=str( target ) )
    seed.add_arcs( { main_py: [ ( -1, 1 ), ( 3, 4 ) ] } )
    seed.write()
    sc.fold( str( directory ), main_py, str( target ), CONTAINER )
    assert sorted( _target_arcs( target, main_py )[ 1 ] ) == [ ( -1, 1 ), ( 3, 4 ) ]
    _server_file( directory, { CONTAINER_MAIN: [ ( 1, 3 ) ] }, ".coverage.box.9.z" )
    sc.fold( str( directory ), main_py, str( target ), CONTAINER )
    assert sorted( _target_arcs( target, main_py )[ 1 ] ) == [ ( -1, 1 ), ( 1, 3 ), ( 3, 4 ) ]


def test_fold_creates_the_target_when_the_tiers_left_none( tmp_path ):
    main_py   = _host_main( tmp_path )
    directory = tmp_path / "srv"
    _server_file( directory, { CONTAINER_MAIN: ARCS } )
    _boot( directory, main_py )
    target = tmp_path / "fresh.cov"
    assert sc.fold( str( directory ), main_py, str( target ), CONTAINER )[ 0 ] == "ok"
    assert sorted( _target_arcs( target, main_py )[ 1 ] ) == sorted( ARCS )


def test_fold_leaves_the_target_untouched_when_the_data_is_stale( tmp_path ):
    main_py   = _host_main( tmp_path )
    directory = tmp_path / "srv"
    _server_file( directory, { CONTAINER_MAIN: ARCS } )
    other = str( tmp_path / "other-main.py" )
    open( other, "w" ).write( MAIN_SRC + "# other\n" )
    _boot( directory, other )
    target = tmp_path / "gate.cov"
    reason, message = sc.fold( str( directory ), main_py, str( target ), CONTAINER )
    assert reason == "stale" and "/api/v2/submit" in message
    assert not target.exists(), "a refused fold still wrote the target"


# ── captured from the real producer ──────────────────────────────────────────

def test_a_real_coverage_run_under_a_fake_container_root_folds_cleanly( tmp_path ):
    """
    Fold data captured from the same `coverage run` command the start script uses.

    The file name suffix, the absolute path and the arc set all come from coverage itself.
    A hand-built CoverageData is better formed than that.
    """
    fake_container = tmp_path / "container"
    produced       = fake_container / sc.MAIN_PY_REL
    produced.parent.mkdir( parents=True )
    produced.write_text( MAIN_SRC )
    directory = tmp_path / "srv"
    directory.mkdir()
    done = subprocess.run( [ sys.executable, "-m", "coverage", "run", "--parallel-mode", "--branch",
                             f"--data-file={directory}/{sc.DATA_PREFIX}", f"--include={produced}",
                             str( produced ) ], capture_output=True, text=True, cwd=tmp_path, timeout=60 )
    assert done.returncode == 0, done.stderr
    assert len( sc.data_files( str( directory ) ) ) == 1
    host = _host_main( tmp_path )
    ( directory / sc.BOOT_NAME ).write_text( json.dumps( { "main_py_hash": sc.blob_hash( host ) } ) )
    target = tmp_path / "gate.cov"
    reason, _ = sc.fold( str( directory ), host, str( target ), str( fake_container ) )
    assert reason == "ok"
    arcs = _target_arcs( target, host )[ 1 ]
    assert ( 4, 5 ) in arcs and ( 4, 6 ) not in arcs, "the real run took the True branch only"


# ── the command line ─────────────────────────────────────────────────────────

def test_cli_write_boot_data_file_and_verdict( tmp_path, monkeypatch, capsys ):
    monkeypatch.setenv( sc.DIR_ENV, str( tmp_path / "srv" ) )
    assert sc._main( [ "data-file" ] ) == 0
    assert capsys.readouterr().out.strip() == str( tmp_path / "srv" / sc.DATA_PREFIX )
    assert sc._main( [ "write-boot" ] ) == 0
    assert capsys.readouterr().out.strip() == str( tmp_path / "srv" / sc.BOOT_NAME )
    assert sc._main( [ "verdict" ] ) == 2
    assert "no-data" in capsys.readouterr().out


def test_cli_fold_reports_and_exits_2_when_not_usable( tmp_path, monkeypatch, capsys ):
    monkeypatch.setenv( sc.DIR_ENV, str( tmp_path / "nothing" ) )
    assert sc._main( [ "fold", "--target", str( tmp_path / "t.cov" ) ] ) == 2
    out = capsys.readouterr().out
    assert out.startswith( "[server-coverage] no-data:" ) and "/api/v2/submit" in out


def test_cli_exits_0_on_a_usable_verdict_and_fold( tmp_path, monkeypatch, capsys ):
    directory = tmp_path / "srv"
    real_main = os.path.join( cu.get_project_root(), sc.MAIN_PY_REL )
    monkeypatch.setenv( sc.DIR_ENV, str( directory ) )
    _server_file( directory, { f"{sc.CONTAINER_ROOT}/{sc.MAIN_PY_REL}": ARCS } )
    _boot( directory, real_main )
    assert sc._main( [ "verdict" ] ) == 0
    assert sc._main( [ "fold", "--target", str( tmp_path / "t.cov" ) ] ) == 0
    assert "[server-coverage] ok:" in capsys.readouterr().out


def test_module_runs_as_a_script( tmp_path ):
    env  = dict( os.environ, **{ sc.DIR_ENV: str( tmp_path / "none" ) } )
    done = subprocess.run( [ sys.executable, "-m", "cosa.utils.server_coverage", "verdict" ],
                           capture_output=True, text=True, env=env, timeout=60 )
    assert done.returncode == 2 and "no-data" in done.stdout
