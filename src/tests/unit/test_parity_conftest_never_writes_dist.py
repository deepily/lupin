"""
The parity-oracle conftest must never write under src/lupin_app/static/dist.

That folder is what :8000 serves from the main checkout. The conftest used to build into it.
That rebuilt the live bundle mid-run in an E2E run on 14 Nov 2026, with 10 false failures.
It now builds into a session temp folder through LUPIN_DIST_OUTDIR. When the live bundle is
stale it refuses and does not rebuild.

Every test here runs in any tree and writes only to pytest's tmp_path. The build scripts run
from a sandbox copy whose own dist/ is the thing watched, never from the tree under test.
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

import pytest

import cosa.utils.util as cu

ROOT           = Path( cu.get_project_root() )
CONFTEST       = ROOT / "src" / "tests" / "parity_oracle" / "conftest.py"
BUILD_SCRIPTS  = ( "build-parity-harness.sh", "build-multiplexer.sh" )
SANDBOX_DIST   = Path( "src" ) / "lupin_app" / "static" / "dist" / "multiplexer"


def _load_conftest():
    """Import the parity conftest as a plain module, so its fixtures can be called directly."""
    spec   = importlib.util.spec_from_file_location( "parity_oracle_conftest_under_test", CONFTEST )
    module = importlib.util.module_from_spec( spec )
    spec.loader.exec_module( module )
    return module


def _raw( fixture ):
    """The undecorated function behind a pytest fixture."""
    return fixture._get_wrapped_function()


@pytest.fixture
def sandbox( tmp_path ):
    """A fake tree: the real build scripts and sources, with its own empty dist/.

    A script resolves its project root from its own location, so a copy here writes into
    <tmp_path>/sandbox/src/lupin_app/static/dist, never into the tree under test.
    """
    box = tmp_path / "sandbox"
    ( box / "src" / "scripts" ).mkdir( parents=True )
    ( box / "src" / "lupin_app" / "static" ).mkdir( parents=True )
    for name in BUILD_SCRIPTS:
        shutil.copy( ROOT / "src" / "scripts" / name, box / "src" / "scripts" / name )
    ( box / "node_modules" ).symlink_to( ROOT / "node_modules" )
    ( box / "src" / "lupin_app" / "static" / "js" ).symlink_to( ROOT / "src" / "lupin_app" / "static" / "js" )
    for extra in ROOT.glob( "tsconfig*.json" ):
        shutil.copy( extra, box / extra.name )
    return box


def _run_build( box, script, outdir=None ):
    env = { k: v for k, v in os.environ.items() if k != "LUPIN_DIST_OUTDIR" }
    if outdir is not None: env[ "LUPIN_DIST_OUTDIR" ] = str( outdir )
    return subprocess.run( [ "bash", str( box / "src" / "scripts" / script ) ], env=env,
                           capture_output=True, text=True, timeout=180 )


@pytest.mark.parametrize( "script", BUILD_SCRIPTS )
def test_a_build_with_an_outdir_writes_nothing_under_the_trees_own_dist( sandbox, tmp_path, script ):
    """The default build fills the sandbox dist; with the override the dist stays absent.

    The first half is the positive control. It shows an empty dist later means the override
    held, not that the build never ran.
    """
    control = _run_build( sandbox, script )
    assert control.returncode == 0, control.stderr
    assert any( ( sandbox / SANDBOX_DIST ).iterdir() ), "positive control: the default build must write to dist/"
    shutil.rmtree( sandbox / "src" / "lupin_app" / "static" / "dist" )

    out    = tmp_path / "private-out"
    result = _run_build( sandbox, script, outdir=out )
    assert result.returncode == 0, result.stderr
    assert any( out.iterdir() ), "the build must land in LUPIN_DIST_OUTDIR"
    assert not ( sandbox / "src" / "lupin_app" / "static" / "dist" ).exists(), \
        "a build with LUPIN_DIST_OUTDIR set must write nothing under the tree's own dist/"


def test_the_conftest_builds_both_bundles_into_its_private_folder( monkeypatch, tmp_path ):
    """_fresh_bundles must hand every build script the private folder, and nothing else."""
    calls = []
    monkeypatch.setattr( subprocess, "run", lambda argv, **kw: calls.append( ( argv, kw ) ) )
    _raw( _load_conftest()._fresh_bundles )( tmp_path )

    assert [ Path( argv[ 1 ] ).name for argv, _ in calls ] == list( BUILD_SCRIPTS )
    for _, kw in calls:
        assert kw[ "env" ][ "LUPIN_DIST_OUTDIR" ] == str( tmp_path )
        assert kw[ "check" ] is True


def test_the_private_folder_is_outside_the_repo_and_empty( tmp_path_factory ):
    folder = _raw( _load_conftest().parity_dist_dir )( tmp_path_factory )
    assert folder.is_dir() and not any( folder.iterdir() )
    assert ROOT not in folder.parents


def test_static_origin_serves_the_private_bundle_and_the_trees_own_static_files( tmp_path ):
    """The bundle path is answered from the private folder, every other path from the tree."""
    ( tmp_path / "accordion-harness.js" ).write_text( "// private build" )
    page   = ROOT / "src" / "lupin_app" / "static" / "html" / "accordion-harness.html"
    origin = _raw( _load_conftest().static_origin )( tmp_path )
    origin_value = next( origin )
    try:
        with urllib.request.urlopen( f"{origin_value}/static/dist/multiplexer/accordion-harness.js?x=1" ) as r:
            assert r.read() == b"// private build"
        with urllib.request.urlopen( f"{origin_value}/static/html/accordion-harness.html" ) as r:
            assert r.read() == page.read_bytes()
    finally:
        with pytest.raises( StopIteration ):
            next( origin )


class _Done:
    def __init__( self, returncode, stdout="", stderr="" ):
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr


def test_a_fresh_live_bundle_passes_and_only_the_checker_runs( monkeypatch ):
    calls = []
    monkeypatch.setattr( subprocess, "run", lambda argv, **kw: calls.append( argv ) or _Done( 0 ) )
    _raw( _load_conftest().live_bundle_fresh )()
    assert [ Path( a[ 1 ] ).name for a in calls ] == [ "check_bundle_freshness.py" ]
    assert all( a[ 0 ] == sys.executable for a in calls )


def test_a_stale_live_bundle_is_refused_with_the_rebuild_command_and_never_rebuilt( monkeypatch ):
    calls = []
    monkeypatch.setattr( subprocess, "run",
                         lambda argv, **kw: calls.append( argv ) or _Done( 1, stdout="multiplexer STALE\n" ) )
    with pytest.raises( pytest.fail.Exception ) as raised:
        _raw( _load_conftest().live_bundle_fresh )()
    message = str( raised.value )
    assert "bash src/scripts/build-multiplexer.sh" in message
    assert "multiplexer STALE" in message
    assert [ Path( a[ 1 ] ).name for a in calls ] == [ "check_bundle_freshness.py" ], "the guard must not run a build"


@pytest.mark.parametrize( "script", BUILD_SCRIPTS )
def test_the_override_keeps_the_literal_outdir_the_freshness_checker_parses( script ):
    """The first OUTDIR= line stays a literal path, which the freshness checker parses."""
    spec    = importlib.util.spec_from_file_location( "cbf_under_test", ROOT / "src" / "scripts" / "check_bundle_freshness.py" )
    checker = importlib.util.module_from_spec( spec )
    spec.loader.exec_module( checker )
    if script == "build-multiplexer.sh":
        parsed = checker.parse_build_script( ROOT / "src" / "scripts" / script )
        assert parsed[ "outdir" ] == "src/lupin_app/static/dist/multiplexer"
    text = ( ROOT / "src" / "scripts" / script ).read_text( encoding="utf-8" )
    assert text.count( 'OUTDIR="src/lupin_app/static/dist/multiplexer"' ) == 1
    assert text.index( 'OUTDIR="src/lupin_app/static/dist/multiplexer"' ) < text.index( "LUPIN_DIST_OUTDIR" )
