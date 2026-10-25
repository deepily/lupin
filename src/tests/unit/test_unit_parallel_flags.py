"""Guard: the unit tier runs in parallel and refuses loudly when xdist is missing.

Three things are pinned.
The helper in src/scripts/lib/unit-parallel-flags.sh answers each case a caller can reach.
Those cases are the default, the serial override, the caller's own -n, a collection-only run and a missing xdist.
The runner run-unit-tests.sh hands the flags to its pytest line, because a helper nobody calls passes every test in this file.
The contended-coverage finder does not take an xdist worker for a peer suite.
"""

import os
import shutil
import subprocess
import sys

import pytest

from cosa.utils import coverage_contention as cc


_PROJECT_ROOT = os.environ[ "LUPIN_ROOT" ]
_LIB          = os.path.join( _PROJECT_ROOT, "src/scripts/lib/unit-parallel-flags.sh" )
_RUNNER       = os.path.join( _PROJECT_ROOT, "src/tests/run-unit-tests.sh" )

# The command line execnet gives every xdist worker (pytest-xdist 3.8.0 / execnet 2.1.2, measured
# 2026-10-25 from `ps` during a `-n 4` run). It carries no `pytest` token and no test file.
_XDIST_WORKER_CMDLINE = 'python -u -c import sys;exec(eval(sys.stdin.readline()))'


def _stub_box( tmp_path, has_xdist ):
    """
    A fake venv bin directory: `pytest` and a `python` that answers `-c "import xdist"`.

    Ensures:
        - returns the path of the stub pytest; the stub python exits 0 iff has_xdist
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    ( bin_dir / "pytest" ).write_text( "" )
    python = bin_dir / "python"
    python.write_text( "#!/bin/bash\nexit %d\n" % ( 0 if has_xdist else 1 ) )
    python.chmod( 0o755 )
    return str( bin_dir / "pytest" )


def _flags( pytest_path, args=(), env_workers=None ):
    """
    Run unit_parallel_flags in a clean bash and return (stdout, stderr, returncode).

    Ensures:
        - LUPIN_UNIT_WORKERS is exactly env_workers, or absent when None
    """
    env = { k: v for k, v in os.environ.items() if k != "LUPIN_UNIT_WORKERS" }
    if env_workers is not None: env[ "LUPIN_UNIT_WORKERS" ] = env_workers
    done = subprocess.run(
        [ "bash", "-c", 'source "$1"; shift; unit_parallel_flags "$@"', "_", _LIB, pytest_path, *args ],
        capture_output=True, text=True, env=env, timeout=30
    )
    return done.stdout.strip(), done.stderr, done.returncode


def test_the_default_is_four_workers( tmp_path ):
    out, _, rc = _flags( _stub_box( tmp_path, True ) )
    assert ( out, rc ) == ( "-n 4", 0 )


def test_the_worker_count_is_overridable( tmp_path ):
    out, _, rc = _flags( _stub_box( tmp_path, True ), env_workers="6" )
    assert ( out, rc ) == ( "-n 6", 0 )


def test_zero_workers_means_serial_and_does_not_need_xdist( tmp_path ):
    out, err, rc = _flags( _stub_box( tmp_path, False ), env_workers="0" )
    assert ( out, err, rc ) == ( "", "", 0 )


@pytest.mark.parametrize( "bad", [ "four", "-1", "4.5", "" ] )
def test_a_non_numeric_worker_count_is_refused( tmp_path, bad ):
    out, err, rc = _flags( _stub_box( tmp_path, True ), env_workers=bad )
    # An empty value falls back to the default, so only the other three are refusals.
    if bad == "": assert ( out, rc ) == ( "-n 4", 0 )
    else: assert ( out, rc ) == ( "", 3 ) and "LUPIN_UNIT_WORKERS must be a whole number" in err


@pytest.mark.parametrize( "args", [
    [ "--collect-only", "-q" ], [ "--co" ], [ "--pdb" ], [ "-n", "0" ], [ "-n2" ],
    [ "--numprocesses=3" ], [ "--dist", "loadfile" ], [ "-p", "no:xdist" ],
] )
def test_the_callers_own_choice_adds_no_flags( tmp_path, args ):
    out, err, rc = _flags( _stub_box( tmp_path, False ), args=args )
    assert ( out, err, rc ) == ( "", "", 0 )


def test_an_unrelated_p_option_does_not_opt_out( tmp_path ):
    out, _, rc = _flags( _stub_box( tmp_path, True ), args=[ "-p", "no:cacheprovider" ] )
    assert ( out, rc ) == ( "-n 4", 0 )


def test_a_missing_xdist_refuses_and_names_both_remedies( tmp_path ):
    out, err, rc = _flags( _stub_box( tmp_path, False ), args=[ "-k", "jwt" ] )
    assert ( out, rc ) == ( "", 3 )
    assert "pytest-xdist is not importable" in err and "LUPIN_UNIT_WORKERS=0" in err


def test_the_runner_hands_the_flags_to_the_pytest_line():
    text = open( _RUNNER ).read()
    assert 'UNIT_PARALLEL_FLAGS="$( unit_parallel_flags "$PYTEST" "$@" )" || exit $?' in text
    pytest_line = [ l for l in text.splitlines() if l.startswith( "run_pytest_with_diagnosis" ) ]
    assert len( pytest_line ) == 1 and "$UNIT_PARALLEL_FLAGS" in pytest_line[ 0 ]


def test_xdist_is_declared_in_both_dependency_files():
    for rel in ( "pyproject.toml", "requirements-test.txt" ):
        assert "pytest-xdist==3.8.0" in open( os.path.join( _PROJECT_ROOT, rel ) ).read(), rel


def test_an_xdist_worker_command_line_is_not_a_suite():
    assert not cc.looks_like_pytest( _XDIST_WORKER_CMDLINE )
    assert not cc.looks_like_a_direct_test_file_run( _XDIST_WORKER_CMDLINE )


def test_the_finder_does_not_report_an_xdist_worker():
    found = cc.find_foreign_pytest(
        process_table=lambda: [ ( 900, _XDIST_WORKER_CMDLINE ) ],
        ancestors=[ 1 ], comm_of=lambda pid: "python"
    )
    assert found == []


def test_a_real_xdist_run_sees_no_worker_as_a_peer( tmp_path ):
    """Run a real `-n 2` and check no worker counts as a peer."""
    pytest.importorskip( "xdist" )
    probe = tmp_path / "test_probe.py"
    probe.write_text(
        "from cosa.utils import coverage_contention as cc\n"
        "import os\n"
        "def test_a():\n"
        "    assert not [ c for _, c in cc.find_foreign_pytest() if 'exec(eval(sys.stdin.readline' in c ]\n"
        "def test_b():\n"
        "    assert os.environ.get( 'PYTEST_XDIST_WORKER' ) is not None\n"
    )
    env  = dict( os.environ, PYTHONPATH=os.path.join( _PROJECT_ROOT, "src" ) + os.pathsep + os.environ.get( "PYTHONPATH", "" ) )
    done = subprocess.run( [ sys.executable, "-m", "pytest", "-n", "2", "-p", "no:cacheprovider", "-q", str( probe ) ],
                           capture_output=True, text=True, env=env, cwd=str( tmp_path ), timeout=120 )
    assert done.returncode == 0, done.stdout[ -2000: ]


def _sandboxed_runner( tmp_path, has_xdist ):
    """
    A copy of the shipped runner and its lib directory over a stub venv.

    Ensures:
        - returns the runner path; the stub pytest records any real invocation in `ran.txt`
        - the stub python answers `import xdist` with exit 0 iff has_xdist
    """
    root = tmp_path / "root"
    ( root / "src/tests" ).mkdir( parents=True )
    shutil.copy( _RUNNER, root / "src/tests/run-unit-tests.sh" )
    shutil.copytree( os.path.join( _PROJECT_ROOT, "src/scripts/lib" ), root / "src/scripts/lib",
                     ignore=shutil.ignore_patterns( "__pycache__" ) )
    venv_bin = root / ".venv/bin"
    venv_bin.mkdir( parents=True )
    pytest_stub = venv_bin / "pytest"
    pytest_stub.write_text( '#!/bin/bash\n[ "$1" = "--version" ] && exit 0\necho "$@" > "%s/ran.txt"\nexit 0\n' % tmp_path )
    python_stub = venv_bin / "python"
    python_stub.write_text( "#!/bin/bash\nexit %d\n" % ( 0 if has_xdist else 1 ) )
    for stub in ( pytest_stub, python_stub ): stub.chmod( 0o755 )
    return str( root / "src/tests/run-unit-tests.sh" )


def _run_runner( runner, args=() ):
    env = { k: v for k, v in os.environ.items() if k not in ( "LUPIN_UNIT_WORKERS", "LUPIN_COVERAGE" ) }
    return subprocess.run( [ "bash", runner, *args ], capture_output=True, text=True, env=env, timeout=60 )


def test_exit_code_3_reaches_the_runners_caller_and_pytest_never_starts( tmp_path ):
    done = _run_runner( _sandboxed_runner( tmp_path, has_xdist=False ) )
    assert done.returncode == 3
    assert "pytest-xdist is not importable" in done.stderr
    assert not ( tmp_path / "ran.txt" ).exists()


def test_the_runner_passes_n_4_to_pytest_when_xdist_is_present( tmp_path ):
    done = _run_runner( _sandboxed_runner( tmp_path, has_xdist=True ) )
    assert done.returncode == 0, done.stderr
    assert "-n 4" in ( tmp_path / "ran.txt" ).read_text()


def test_the_runner_runs_serial_with_xdist_absent_when_workers_is_zero( tmp_path ):
    env_runner = _sandboxed_runner( tmp_path, has_xdist=False )
    env = { k: v for k, v in os.environ.items() if k != "LUPIN_COVERAGE" }
    env[ "LUPIN_UNIT_WORKERS" ] = "0"
    done = subprocess.run( [ "bash", env_runner ], capture_output=True, text=True, env=env, timeout=60 )
    assert done.returncode == 0, done.stderr
    assert "-n" not in ( tmp_path / "ran.txt" ).read_text().split()
