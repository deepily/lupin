#!/usr/bin/env python3
"""
Unit tests for the by-hand runner of the test-suite live pipeline smoke.

That smoke submits a test-suite job, which cannot run inside any suite job.
The runner is the one named door for it: it runs the file against :8000 from the host.
It refuses unless cosa.rest.venue_idle exits 0, and it passes pytest's exit code through.

The tests copy the runner and its libraries into a temporary tree.
A fake python3 stands in for the venue check and a fake pytest records how it was called.
Nothing here touches a server.
"""

import importlib
import os
import shutil
import stat
import subprocess

import pytest

import cosa.utils.util as cu

ROOT        = cu.get_project_root()
RUNNER      = "src/scripts/run-test-suite-live-smoke.sh"
SMOKE_FILE  = "src/tests/smoke/test_test_suite_live_pipeline.py"
REFUSED     = 64


def _executable( path, body ):
    with open( path, "w" ) as f: f.write( body )
    os.chmod( path, os.stat( path ).st_mode | stat.S_IXUSR )


@pytest.fixture
def tree( tmp_path ):
    """A copy of the runner and its libraries, a fake python3 and a fake venv pytest."""
    root = tmp_path / "tree"
    ( root / "src/scripts" ).mkdir( parents=True )
    shutil.copy( os.path.join( ROOT, RUNNER ), root / RUNNER )
    shutil.copytree( os.path.join( ROOT, "src/scripts/lib" ), root / "src/scripts/lib" )
    ( root / ".venv/bin" ).mkdir( parents=True )
    ( tmp_path / "bin" ).mkdir()
    _executable( tmp_path / "bin/python3",
                 '#!/bin/bash\necho "$@" >> "$FAKE_PYTHON_LOG"\n'
                 'case "$*" in *cosa.rest.venue_idle*) exit "${FAKE_IDLE_CODE:-0}" ;; esac\nexit 0\n' )
    _executable( root / ".venv/bin/pytest",
                 '#!/bin/bash\n[ "$1" = "--version" ] && exit 0\n'
                 'echo "$@" >> "$FAKE_PYTEST_LOG"\n'
                 'echo "base=${LUPIN_TEST_BASE_URL:-unset} parent=${LUPIN_TEST_MONOPOLIZE_PARENT_ID:-unset}" >> "$FAKE_PYTEST_LOG"\n'
                 'exit "${FAKE_PYTEST_CODE:-0}"\n' )
    return root


def _run( tree, tmp_path, idle=0, pytest_code=0, extra_env=None, args=() ):
    env = { k: v for k, v in os.environ.items() if k not in ( "LUPIN_TEST_MONOPOLIZE_PARENT_ID", "LUPIN_ROOT", "PYTHONPATH" ) }
    env.update( PATH=f"{tmp_path / 'bin'}:{env[ 'PATH' ]}", FAKE_IDLE_CODE=str( idle ), FAKE_PYTEST_CODE=str( pytest_code ),
                FAKE_PYTHON_LOG=str( tmp_path / "python.log" ), FAKE_PYTEST_LOG=str( tmp_path / "pytest.log" ) )
    env.update( extra_env or {} )
    done = subprocess.run( [ "bash", str( tree / RUNNER ), *args ], capture_output=True, text=True, env=env, cwd=tree )
    read = lambda name: ( tmp_path / name ).read_text() if ( tmp_path / name ).exists() else ""
    return done, read( "python.log" ), read( "pytest.log" )


def test_the_runner_exists_and_is_executable():
    path = os.path.join( ROOT, RUNNER )
    assert os.path.isfile( path ) and os.access( path, os.X_OK )


@pytest.mark.parametrize( "code, word", [ ( 1, "BUSY" ), ( 2, "UNKNOWN" ) ] )
def test_it_refuses_when_the_venue_is_not_verified_idle_and_runs_no_pytest( tree, tmp_path, code, word ):
    done, python_log, pytest_log = _run( tree, tmp_path, idle=code )
    assert done.returncode == REFUSED, done.stderr
    assert word in done.stderr and "venue_idle" in done.stderr, done.stderr
    assert pytest_log == ""


def test_it_asks_the_venue_check_about_port_8000( tree, tmp_path ):
    _, python_log, _ = _run( tree, tmp_path )
    assert "-m cosa.rest.venue_idle --port 8000" in python_log, python_log


def test_on_an_idle_venue_it_runs_the_one_file_against_8000_and_passes_the_exit_code_through( tree, tmp_path ):
    done, _, pytest_log = _run( tree, tmp_path, pytest_code=7, args=( "-x", ) )
    assert done.returncode == 7, ( done.stdout, done.stderr )
    assert SMOKE_FILE in pytest_log and "-x" in pytest_log, pytest_log
    assert "base=http://localhost:8000" in pytest_log, pytest_log


def test_a_green_run_exits_zero( tree, tmp_path ):
    done, _, _ = _run( tree, tmp_path, pytest_code=0 )
    assert done.returncode == 0, ( done.stdout, done.stderr )


def test_it_refuses_inside_a_suite_job_before_asking_the_venue( tree, tmp_path ):
    done, python_log, pytest_log = _run( tree, tmp_path, extra_env={ "LUPIN_TEST_MONOPOLIZE_PARENT_ID": "ts-abc123" } )
    assert done.returncode == REFUSED, done.stderr
    assert "suite job" in done.stderr, done.stderr
    assert python_log == "" and pytest_log == ""


def test_the_pytest_it_starts_does_not_see_a_suite_id( tree, tmp_path ):
    _, _, pytest_log = _run( tree, tmp_path )
    assert "parent=unset" in pytest_log, pytest_log


def test_the_skip_reason_names_the_runner():
    import tests.smoke.test_test_suite_live_pipeline as smoke
    assert RUNNER in smoke.TIER_SKIP_REASON
    assert "Run this file as its own scheduled run" not in smoke.TIER_SKIP_REASON


def test_the_scheduling_guide_names_the_runner():
    guide = open( os.path.join( ROOT, "src/docs/agents/test-suite-scheduling-guide.md" ) ).read()
    assert RUNNER in guide


@pytest.mark.parametrize( "value, expected", [ ( None, "http://localhost:7999" ), ( "http://localhost:8000", "http://localhost:8000" ) ] )
def test_the_base_url_reads_the_test_base_url_variable( monkeypatch, value, expected ):
    import tests.smoke.utilities.live_pipeline_base as lpb
    if value is None: monkeypatch.delenv( "LUPIN_TEST_BASE_URL", raising=False )
    else:             monkeypatch.setenv( "LUPIN_TEST_BASE_URL", value )
    try:
        assert importlib.reload( lpb ).LivePipelineTestBase.BASE_URL == expected
    finally:
        monkeypatch.undo()
        importlib.reload( lpb )
