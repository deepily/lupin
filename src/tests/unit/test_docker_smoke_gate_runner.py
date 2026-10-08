"""
The runner script of the docker smoke step, driven in a scratch tree with stubs.

The merge pyramid calls the script on the host. These tests pin its exit codes: 0 every test passed,
1 a failure, a skip or a missing file, 2 nothing checked, 3 no interpreter. No real container starts.
A stub docker and a stub interpreter stand in for the real ones. The stub answers `-m pytest` by copying
a canned junit report and runs everything else with the real interpreter, so the real report reader runs.

Venue: :7999-eligible. No server, no docker, no state outside tmp_path.
"""

import os
import shutil
import stat
import subprocess
import sys

import pytest

import cosa.utils.util as cu
from cosa.agents.test_suite.job import TestSuiteJob

PROJECT_ROOT = cu.get_project_root()
RUNNER       = os.path.join( PROJECT_ROOT, "src", "tests", "run-docker-smoke-gate.sh" )
RESOLVER     = os.path.join( PROJECT_ROOT, "src", "scripts", "lib", "resolve-venv-pytest.sh" )
MODULES      = ( "test_credential_mount_shape", "test_db_roles_rollback_real_postgres", "test_db_grants_real_postgres" )

STUB_PYTHON = """#!/bin/bash
case "$1" in
    --version) echo "Python 3.13 (stub)"; exit 0 ;;
    -m)
        if [ "$2" = "pytest" ]; then
            echo "$@" >> "$STUB_PYTEST_ARGS"
            for a in "$@"; do case "$a" in --junit-xml=*) OUT="${a#--junit-xml=}" ;; esac; done
            if [ -n "${STUB_JUNIT:-}" ]; then cp "$STUB_JUNIT" "$OUT"; fi
            exit "${STUB_PYTEST_RC:-0}"
        fi
        exec "$STUB_REAL_PYTHON" "$@" ;;
esac
exec "$STUB_REAL_PYTHON" "$@"
"""

STUB_DOCKER = """#!/bin/bash
exit "${STUB_DOCKER_RC:-0}"
"""


def _executable( path, text ):
    path.parent.mkdir( parents=True, exist_ok=True )
    path.write_text( text )
    path.chmod( path.stat().st_mode | stat.S_IXUSR )


def _case( module, name, outcome=None, message="" ):
    inner = f'<{outcome} message="{message}"/>' if outcome else ""
    return f'<testcase classname="src.tests.smoke.{module}" name="{name}">{inner}</testcase>'


def _junit( tmp_path, cases, name="canned.xml" ):
    path = tmp_path / name
    path.write_text( f'<?xml version="1.0"?><testsuites><testsuite>{"".join( cases )}</testsuite></testsuites>', encoding="utf-8" )
    return str( path )


@pytest.fixture
def tree( tmp_path ):
    """A scratch tree with the real runner, resolver and cosa package, and stub tools."""
    root = tmp_path / "tree"
    ( root / "src" / "tests" ).mkdir( parents=True )
    ( root / "src" / "scripts" / "lib" ).mkdir( parents=True )
    shutil.copy( RUNNER, root / "src" / "tests" / "run-docker-smoke-gate.sh" )
    shutil.copy( RESOLVER, root / "src" / "scripts" / "lib" / "resolve-venv-pytest.sh" )
    os.symlink( os.path.join( PROJECT_ROOT, "src", "cosa" ), root / "src" / "cosa" )
    _executable( root / ".venv" / "bin" / "python3", STUB_PYTHON )
    _executable( tmp_path / "bin" / "docker", STUB_DOCKER )
    return root


def _run( tree, tmp_path, junit=None, pytest_rc=0, docker_rc=0 ):
    env = dict( os.environ )
    env.update( {
        "PATH"             : f"{tmp_path / 'bin'}:{env[ 'PATH' ]}",
        "STUB_REAL_PYTHON" : sys.executable,
        "STUB_PYTEST_ARGS" : str( tmp_path / "pytest-args.txt" ),
        "STUB_PYTEST_RC"   : str( pytest_rc ),
        "STUB_DOCKER_RC"   : str( docker_rc ),
    } )
    env.pop( "STUB_JUNIT", None )
    if junit: env[ "STUB_JUNIT" ] = junit
    done = subprocess.run( [ "bash", str( tree / "src" / "tests" / "run-docker-smoke-gate.sh" ) ], capture_output=True, text=True, timeout=120, env=env )
    return done.returncode, done.stdout + done.stderr


def _passing( tmp_path ):
    return _junit( tmp_path, [ _case( m, f"test_{i}" ) for i, m in enumerate( MODULES ) ] )


def test_a_green_run_exits_zero_and_the_job_reads_every_test_as_passed( tree, tmp_path ):
    code, text = _run( tree, tmp_path, junit=_passing( tmp_path ) )
    assert code == 0, text
    assert "Total Tests: 3\nPassed: 3\nFailed: 0\nSkipped: 0" in text
    assert TestSuiteJob._parse_non_pytest_stdout( "docker_smoke", text ) == { "passed": 3, "failed": 0, "skipped": 0, "errors": 0, "not_executed": 0 }


def test_one_skip_exits_one_names_the_reason_and_the_job_reads_it_as_failed( tree, tmp_path ):
    cases = [ _case( m, f"test_{i}" ) for i, m in enumerate( MODULES ) ] + [ _case( MODULES[ 0 ], "test_compute", "skipped", "no lupin-rest container is up" ) ]
    code, text = _run( tree, tmp_path, junit=_junit( tmp_path, cases ) )
    assert code == 1, text
    assert f"SKIPPED src.tests.smoke.{MODULES[ 0 ]}::test_compute: no lupin-rest container is up" in text
    assert "Failed: 1" in text and "Skipped: 1" in text
    assert TestSuiteJob._parse_non_pytest_stdout( "docker_smoke", text )[ "failed" ] == 1


def test_a_file_missing_from_the_report_exits_one_and_is_named( tree, tmp_path ):
    code, text = _run( tree, tmp_path, junit=_junit( tmp_path, [ _case( m, "test_a" ) for m in MODULES[ :2 ] ] ) )
    assert code == 1, text
    assert f"MISSING {MODULES[ 2 ]}" in text and "Failed: 1" in text


def test_docker_not_usable_exits_two_prints_no_counts_and_the_job_reads_it_as_not_executed( tree, tmp_path ):
    code, text = _run( tree, tmp_path, junit=_passing( tmp_path ), docker_rc=1 )
    assert code == 2, text
    assert "REFUSING: docker is not usable here. Nothing was checked." in text
    assert "Total Tests" not in text and "Passed:" not in text
    assert TestSuiteJob._parse_non_pytest_stdout( "docker_smoke", text ) is None
    assert not ( tmp_path / "pytest-args.txt" ).exists(), "pytest must not start when docker is unusable"


def test_the_pytest_that_failed_while_the_report_reads_clean_exits_two_with_no_counts( tree, tmp_path ):
    code, text = _run( tree, tmp_path, junit=_passing( tmp_path ), pytest_rc=2 )
    assert code == 2, text
    assert "REFUSING: pytest exited 2 while the report read clean. Nothing was checked." in text
    assert "Total Tests" not in text


def test_an_unreadable_report_exits_two_with_no_counts( tree, tmp_path ):
    code, text = _run( tree, tmp_path, junit=None )
    assert code == 2, text
    assert "REFUSING: the junit report could not be read" in text and "Total Tests" not in text


def test_a_failing_pytest_with_a_failing_report_exits_one( tree, tmp_path ):
    cases = [ _case( m, f"test_{i}" ) for i, m in enumerate( MODULES ) ] + [ _case( MODULES[ 1 ], "test_bad", "failure", "assert" ) ]
    code, text = _run( tree, tmp_path, junit=_junit( tmp_path, cases ), pytest_rc=1 )
    assert code == 1, text
    assert "Failed: 1" in text


def test_the_runner_hands_pytest_the_three_files_one_junit_path_and_the_skip_reasons_flag( tree, tmp_path ):
    _run( tree, tmp_path, junit=_passing( tmp_path ) )
    args = ( tmp_path / "pytest-args.txt" ).read_text().split()
    for module in MODULES: assert f"src/tests/smoke/{module}.py" in args
    assert sum( a.startswith( "--junit-xml=" ) for a in args ) == 1
    assert "-rs" in args


def test_a_tree_with_no_interpreter_exits_three( tree, tmp_path ):
    os.unlink( tree / ".venv" / "bin" / "python3" )
    code, text = _run( tree, tmp_path, junit=_passing( tmp_path ) )
    assert code == 3, text
    assert "Total Tests" not in text
