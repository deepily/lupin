"""
Row d51ffc36: a unit session must not wipe the last E2E run's failure PNGs, and each visual
session writes to its own run folder.

The proof runs REAL pytest sessions in a subprocess (src/conftest.py copied in as the conftest, the stock
playwright-visual plugin loaded by its entry point), not a fake of the fixture: a session with no
visual test leaves a planted PNG alone, and a visual session leaves sibling runs alone.

Venue: :7999-eligible / local — tmp_path only, no server, no state outside /tmp.
"""
import os
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest

import cosa.utils.util as cu
from cosa.utils import visual_failures as vf

ROOT = cu.get_project_root()


# --- the pure helpers ---------------------------------------------------------------------

def test_run_id_prefers_the_explicit_override_then_the_job_id_then_a_timestamp():
    assert vf.make_run_id( { vf.RUN_ID_ENV: "mine", vf.JOB_ID_ENV: "ts-deadbeef" } ) == "mine"
    assert vf.make_run_id( { vf.JOB_ID_ENV: "ts-deadbeef" } ) == "ts-deadbeef"
    assert vf.make_run_id( { vf.RUN_ID_ENV: "  ", vf.JOB_ID_ENV: "ts-deadbeef" } ) == "ts-deadbeef"
    from datetime import datetime, timezone
    assert vf.make_run_id( {}, now=datetime( 2026, 9, 30, 20, 27, 59, tzinfo=timezone.utc ), pid=42 ) == "20260930T202759Z-42"


def test_run_id_reads_the_real_environment_by_default( monkeypatch ):
    monkeypatch.delenv( vf.RUN_ID_ENV, raising=False )
    monkeypatch.setenv( vf.JOB_ID_ENV, "ts-0a0a0a0a" )
    assert vf.make_run_id() == "ts-0a0a0a0a"
    monkeypatch.delenv( vf.JOB_ID_ENV )
    assert vf.make_run_id().endswith( f"-{os.getpid()}" )


def test_session_collects_visual_looks_for_the_assert_snapshot_family():
    item = lambda *names: SimpleNamespace( fixturenames=list( names ) )
    assert vf.session_collects_visual( [ item( "page" ), item( "tmp_path", "assert_snapshot" ) ] ) is True
    assert vf.session_collects_visual( [ item( "assert_snapshot_height_tolerant" ) ] ) is True
    assert vf.session_collects_visual( [ item( "page" ), item( "snapshot" ) ] ) is False
    assert vf.session_collects_visual( [] ) is False


def test_prepare_run_dir_creates_it_and_never_empties_an_existing_one( tmp_path ):
    run = vf.prepare_run_dir( str( tmp_path / "vf" ), "ts-aaaaaaaa" )
    ( tmp_path / "vf" / "ts-aaaaaaaa" / "kept.png" ).write_bytes( b"x" )
    assert vf.prepare_run_dir( str( tmp_path / "vf" ), "ts-aaaaaaaa" ) == run
    assert ( tmp_path / "vf" / "ts-aaaaaaaa" / "kept.png" ).read_bytes() == b"x"      # the second half of a job shares it


@pytest.mark.parametrize( "bad", [ "", ".", "..", "a/b", "../x" ] )
def test_prepare_run_dir_refuses_a_run_id_that_is_not_a_plain_name( tmp_path, bad ):
    with pytest.raises( ValueError, match="plain directory name" ):
        vf.prepare_run_dir( str( tmp_path ), bad )


def test_prune_needs_old_AND_outside_the_newest_N_and_never_touches_the_current_run( tmp_path ):
    base = tmp_path / "vf"
    now  = time.time()
    names = {}                                           # name -> age in days
    for i, age in enumerate( [ 60, 50, 40, 30, 20, 10, 1 ] ):
        names[ f"old{i}" ] = age
    for name, age in names.items():
        d = base / name; d.mkdir( parents=True )
        os.utime( d, ( now - age * 86400, now - age * 86400 ) )
    ( base / "loose.png" ).write_bytes( b"p" )
    current = base / "cur"; current.mkdir(); os.utime( current, ( now - 99 * 86400, now - 99 * 86400 ) )   # ancient, but CURRENT

    vf.prepare_run_dir( str( base ), "cur", keep_days=14, keep_newest=3, now=now )

    left = sorted( p.name for p in base.iterdir() )
    # newest 3 of the others are old5(10d), old6(1d), old4(20d) -> kept by rank; old3..old0 are >14d and outside them -> pruned
    assert left == [ "cur", "loose.png", "old4", "old5", "old6" ]


def test_prune_keeps_the_newest_N_even_when_they_are_all_ancient( tmp_path ):
    base = tmp_path / "vf"
    now  = time.time()
    for i in range( 4 ):
        d = base / f"r{i}"; d.mkdir( parents=True ); os.utime( d, ( now - ( 100 + i ) * 86400, ) * 2 )
    vf.prepare_run_dir( str( base ), "new", keep_days=14, keep_newest=2, now=now )
    assert sorted( p.name for p in base.iterdir() ) == [ "new", "r0", "r1" ]


# --- REAL pytest sessions -----------------------------------------------------------------

INI = """[pytest]
playwright_visual_snapshot_threshold = 0.1
playwright_visual_snapshots_path = vb
playwright_visual_snapshot_failures_path = vf
"""
UNIT_TEST   = "def test_plain():\n    assert True\n"
VISUAL_TEST = ( "import pytest\n"
                "@pytest.fixture\n"
                "def assert_snapshot_fake():\n    return 1\n"
                "def test_visual( assert_snapshot_fake, request ):\n"
                "    from pytest_playwright_visual_snapshot.plugin import SnapshotPaths\n"
                "    open( 'where.txt', 'w' ).write( str( SnapshotPaths.failures_path ) )\n" )


def _session( tmp_path, test_source, env_extra=None, extra_args=() ):
    ( tmp_path / "pytest.ini" ).write_text( INI )
    ( tmp_path / "test_x.py" ).write_text( test_source )
    # the REAL src/conftest.py, byte for byte, as the session's conftest (a plugin-registered
    # fixture does not outrank the stock plugin's; a conftest one does, which is how it ships)
    ( tmp_path / "conftest.py" ).write_bytes( open( ROOT + "/src/conftest.py", "rb" ).read() )
    env = { **os.environ, "PYTHONPATH": ROOT + "/src", "LUPIN_ROOT": ROOT, **( env_extra or {} ) }
    env.pop( vf.RUN_ID_ENV, None ); env.pop( vf.JOB_ID_ENV, None )
    env.update( env_extra or {} )
    proc = subprocess.run( [ sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                             *extra_args, "--rootdir", str( tmp_path ), "-c", str( tmp_path / "pytest.ini" ), "test_x.py" ],
                           cwd=tmp_path, env=env, capture_output=True, text=True, timeout=120 )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return proc


def test_a_unit_only_session_leaves_a_planted_failure_png_alone( tmp_path ):
    planted = tmp_path / "vf" / "ts-11111111" / "test_file" / "test_name" / "actual_x.png"
    planted.parent.mkdir( parents=True ); planted.write_bytes( b"evidence" )
    _session( tmp_path, UNIT_TEST )
    assert planted.read_bytes() == b"evidence"
    assert sorted( p.name for p in ( tmp_path / "vf" ).iterdir() ) == [ "ts-11111111" ]     # and made no folder of its own


def test_a_visual_session_writes_to_its_own_ts_folder_and_leaves_siblings_alone( tmp_path ):
    sibling = tmp_path / "vf" / "ts-11111111" / "test_file" / "test_name" / "actual_x.png"
    sibling.parent.mkdir( parents=True ); sibling.write_bytes( b"evidence" )
    _session( tmp_path, VISUAL_TEST, { vf.JOB_ID_ENV: "ts-22222222" } )
    assert sibling.read_bytes() == b"evidence"
    assert ( tmp_path / "vf" / "ts-22222222" ).is_dir()
    assert ( tmp_path / "where.txt" ).read_text() == str( tmp_path / "vf" / "ts-22222222" )


def test_a_visual_session_without_a_job_id_gets_a_timestamped_folder( tmp_path ):
    _session( tmp_path, VISUAL_TEST )
    made = [ p.name for p in ( tmp_path / "vf" ).iterdir() ]
    assert len( made ) == 1 and made[ 0 ].endswith( "Z-" + made[ 0 ].rsplit( "-", 1 )[ 1 ] ) and made[ 0 ][ 8 ] == "T"


def test_a_session_without_the_plugin_installed_still_runs( tmp_path ):
    stub = tmp_path / "stub" / "pytest_playwright_visual_snapshot"
    stub.mkdir( parents=True ); ( stub / "__init__.py" ).write_text( "" )             # the package, without .plugin
    proc = _session( tmp_path, UNIT_TEST, { "PYTHONPATH": f"{tmp_path / 'stub'}{os.pathsep}{ROOT}/src" },
                     extra_args=( "-p", "no:playwright_visual_snapshot" ) )
    assert "1 passed" in proc.stdout


def test_prune_spares_a_young_directory_even_when_it_is_outside_the_newest_N( tmp_path ):
    base = tmp_path / "vf"
    ( base / "young" ).mkdir( parents=True )
    vf.prepare_run_dir( str( base ), "new", keep_days=14, keep_newest=0 )
    assert sorted( p.name for p in base.iterdir() ) == [ "new", "young" ]
