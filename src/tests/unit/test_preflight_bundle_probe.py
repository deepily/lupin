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
