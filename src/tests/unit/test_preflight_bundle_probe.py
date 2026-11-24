"""
The bundle freshness gate refuses a stale dist/ bundle.

One test drives the real lib script, checker and esbuild in a scratch copy of the tree.
The served dist/ is never read or written.
Venue: :7999 (unit).
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path( os.environ[ "LUPIN_ROOT" ] )
LIB  = ROOT / "src/scripts/lib/preflight-bundle-probe.sh"


def _gate( tmp_path, *args, checker_rc=None, rebuild_log=None ):
    """Run the gate against stub commands; return ( rc, output, calls )."""
    env = dict( os.environ )
    checker = tmp_path / "checker"
    checker.write_text( f"#!/bin/sh\necho checked >> {tmp_path}/calls\necho 'checker report'\nexit $( cat {tmp_path}/rc )\n" )
    checker.chmod( 0o755 )
    env[ "LUPIN_BUNDLE_FRESHNESS_CMD" ] = str( checker )
    rebuild = tmp_path / "rebuild"
    rebuild.write_text( f"#!/bin/sh\necho rebuilt >> {tmp_path}/calls\necho 0 > {tmp_path}/rc\n" )
    rebuild.chmod( 0o755 )
    env[ "LUPIN_BUNDLE_REBUILD_CMD" ] = str( rebuild )
    ( tmp_path / "rc" ).write_text( f"{checker_rc}\n" )
    done = subprocess.run( [ "bash", "-c", f"source {LIB}; bundle_freshness_gate {' '.join( args )}" ],
                           env=env, capture_output=True, text=True, timeout=60 )
    calls = ( tmp_path / "calls" ).read_text().split() if ( tmp_path / "calls" ).exists() else [ ]
    return done.returncode, done.stdout, calls


@pytest.mark.parametrize( "checker_rc", [ 0, 1, 2, 3 ] )
def test_the_gate_passes_the_checkers_verdict_through_and_never_rebuilds_unasked( tmp_path, checker_rc ):
    rc, out, calls = _gate( tmp_path, checker_rc=checker_rc )
    assert rc == checker_rc and calls == [ "checked" ] and "checker report" in out


def test_rebuild_flag_rebuilds_a_stale_bundle_then_rechecks_to_green( tmp_path ):
    rc, out, calls = _gate( tmp_path, "--rebuild", checker_rc=1 )
    assert rc == 0 and calls == [ "checked", "rebuilt", "checked" ]


@pytest.mark.parametrize( "checker_rc", [ 0, 2, 3 ] )
def test_rebuild_flag_does_not_rebuild_unless_the_bundle_is_stale( tmp_path, checker_rc ):
    rc, out, calls = _gate( tmp_path, "--rebuild", checker_rc=checker_rc )
    assert rc == checker_rc and calls == [ "checked" ]


def test_rebuild_that_changes_nothing_stays_stale( tmp_path ):
    """A no-op rebuild leaves the second check red, so the gate still fails."""
    env = dict( os.environ, LUPIN_BUNDLE_FRESHNESS_CMD="/bin/false", LUPIN_BUNDLE_REBUILD_CMD="/bin/true" )
    done = subprocess.run( [ "bash", "-c", f"source {LIB}; bundle_freshness_gate --rebuild" ], env=env, capture_output=True, text=True )
    assert done.returncode == 1


def test_a_ts_file_touched_after_the_build_turns_the_real_checker_red_and_a_fresh_build_green( tmp_path ):
    """A changed source turns the real checker red; a rebuild turns it green."""
    esbuild = ROOT / "node_modules/.bin/esbuild"
    if not esbuild.exists(): pytest.skip( "esbuild not installed in this tree" )
    scratch = tmp_path / "tree"
    for rel in ( "src/scripts", "src/lupin_app/static/js" ):
        shutil.copytree( ROOT / rel, scratch / rel, symlinks=True, ignore=shutil.ignore_patterns( "__pycache__" ) )
    shutil.copy( ROOT / "package.json", scratch / "package.json" )
    os.symlink( ROOT / "node_modules", scratch / "node_modules" )
    # Only the multiplexer driver: the scratch tree's package.json build script is replaced to match.
    ( scratch / "package.json" ).write_text( '{"scripts":{"build":"bash src/scripts/build-multiplexer.sh"}}' )
    for driver in ( scratch / "src/scripts" ).glob( "build-*.sh" ):
        if driver.name != "build-multiplexer.sh": driver.unlink()
    env  = { k: v for k, v in os.environ.items() if k != "LUPIN_BUNDLE_FRESHNESS_CMD" }
    run  = lambda cmd: subprocess.run( cmd, cwd=scratch, env=env, capture_output=True, text=True, timeout=300 )
    gate = lambda *a: run( [ "bash", "-c", f"source {scratch}/src/scripts/lib/preflight-bundle-probe.sh; bundle_freshness_gate {' '.join( a )}" ] )

    assert run( [ "bash", "src/scripts/build-multiplexer.sh" ] ).returncode == 0
    assert gate().returncode == 0, "a bundle just built must read FRESH"

    entry = scratch / "src/lupin_app/static/js/multiplexer/boot.ts"
    entry.write_text( entry.read_text() + "\nexport const __bundle_probe_marker = 12345;\nconsole.log( __bundle_probe_marker );\n" )
    stale = gate()
    assert stale.returncode == 1, stale.stdout + stale.stderr

    healed = gate( "--rebuild" )
    assert healed.returncode == 0, healed.stdout + healed.stderr


# ── the two callers: the real scripts, with a stubbed checker verdict ───────────

LAUNCHER  = ROOT / "src/scripts/run-e2e-ui-tests.sh"
PREFLIGHT = ROOT / "src/scripts/preflight-test-container.sh"


def _stub_checker( tmp_path, rc ):
    """A checker that prints one line and exits rc."""
    stub = tmp_path / "stub-checker"
    stub.write_text( f"#!/bin/sh\necho 'stub checker report'\nexit {rc}\n" )
    stub.chmod( 0o755 )
    return str( stub )


def _launch( tmp_path, rc ):
    """Run the real launcher in a scratch tree with a stub database check."""
    tree = tmp_path / "tree"
    ( tree / "src/tests" ).mkdir( parents=True )
    shutil.copytree( ROOT / "src/scripts", tree / "src/scripts", symlinks=True, ignore=shutil.ignore_patterns( "__pycache__" ) )
    ( tree / "src/tests/preflight_test_db.py" ).write_text( "import sys\nsys.exit( 0 )\n" )
    ( tree / ".venv/bin" ).mkdir( parents=True )
    os.symlink( shutil.which( "python3" ), tree / ".venv/bin/python3" )
    env = dict( os.environ, LUPIN_ROOT=str( tree ), LUPIN_BUNDLE_FRESHNESS_CMD=_stub_checker( tmp_path, rc ),
                LUPIN_E2E_PID_FILE=str( tmp_path / "e2e.pid" ), LUPIN_TEST_BASE_URL="http://127.0.0.1:1" )
    return subprocess.run( [ "bash", str( tree / "src/scripts/run-e2e-ui-tests.sh" ) ], env=env, capture_output=True, text=True, timeout=60 )


def test_launcher_exits_one_on_a_stale_bundle_before_it_looks_for_the_server( tmp_path ):
    done = _launch( tmp_path, 1 )
    assert done.returncode == 1 and "bundle is STALE" in done.stdout and "--rebuild-bundle" in done.stdout
    assert "Test Server Not Running" not in done.stdout, "a stale bundle must stop the run before the server probe"


@pytest.mark.parametrize( "checker_rc", [ 2, 3 ] )
def test_launcher_warns_and_continues_when_the_checker_cannot_answer( tmp_path, checker_rc ):
    done = _launch( tmp_path, checker_rc )
    assert f"could not be checked (exit {checker_rc})" in done.stdout and "STALE" not in done.stdout
    assert "Test Server Not Running" in done.stdout, "the run must go on to the server probe"


def test_launcher_says_nothing_about_the_bundle_when_it_is_fresh( tmp_path ):
    done = _launch( tmp_path, 0 )
    assert "bundle" not in done.stdout.lower() and "Test Server Not Running" in done.stdout


def _preflight( tmp_path, rc, *flags ):
    """Run the real preflight against a fake docker and a stub checker; return its stdout."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker = bin_dir / "docker"
    docker.write_text( '#!/bin/bash\ncase "$1" in\n  info) exit 0 ;;\n  ps) echo "fake-test"; exit 0 ;;\nesac\nexit 1\n' )
    docker.chmod( 0o755 )
    env = dict( os.environ, PATH=f"{bin_dir}:{os.environ[ 'PATH' ]}", PREFLIGHT_CONTAINER="fake-test",
                LUPIN_BUNDLE_FRESHNESS_CMD=_stub_checker( tmp_path, rc ), LUPIN_BUNDLE_REBUILD_CMD="/bin/true" )
    return subprocess.run( [ "bash", str( PREFLIGHT ), *flags ], env=env, capture_output=True, text=True, cwd=ROOT, timeout=120 ).stdout


def _bundle_line( out ):
    return [ line for line in out.splitlines() if "client bundle" in line ]


def test_preflight_fails_on_a_stale_bundle_and_names_the_rebuild_flag( tmp_path ):
    out = _preflight( tmp_path, 1 )
    assert any( "[FAIL]" in line and "STALE" in line for line in _bundle_line( out ) )
    assert "--rebuild-bundle" in out


@pytest.mark.parametrize( "checker_rc", [ 2, 3 ] )
def test_preflight_only_warns_when_the_checker_cannot_answer( tmp_path, checker_rc ):
    lines = _bundle_line( _preflight( tmp_path, checker_rc ) )
    assert any( "[WARN]" in line and f"exit {checker_rc}" in line for line in lines )
    assert not any( "[FAIL]" in line for line in lines )


def test_preflight_passes_a_fresh_bundle( tmp_path ):
    assert any( "[OK]" in line and "is fresh" in line for line in _bundle_line( _preflight( tmp_path, 0 ) ) )


def test_preflight_rebuild_flag_turns_a_stale_verdict_into_an_ok_only_when_the_rebuild_heals_it( tmp_path ):
    """A no-op rebuild leaves the checker red, so the probe still fails."""
    out = _preflight( tmp_path, 1, "--rebuild-bundle" )
    assert "rebuilding" in out and any( "[FAIL]" in line for line in _bundle_line( out ) )
