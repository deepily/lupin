"""
Tests for the Python choice in reuse-vector-refresh.sh.

The wrapper must run the job with the first Python that can import it, and refuse when none can.
Each fake Python is a shell script: it fails the import probe (-c) or passes it, and logs a real run.
"""
import os
import subprocess
from pathlib import Path

SCRIPT = Path( os.environ.get( "LUPIN_ROOT", os.getcwd() ) ) / "src" / "scripts" / "reuse-vector-refresh.sh"


def fake_python( path, imports_ok ):
    path.parent.mkdir( parents=True, exist_ok=True )
    path.write_text( f'#!/bin/bash\nif [ "$1" = "-c" ]; then exit {0 if imports_ok else 1}; fi\necho "RAN {path.parent.parent.name}"\n' )
    path.chmod( 0o755 )
    return path


def run_wrapper( tmp_path, explicit=None, venv=None, mcp=None, system=None ):
    root, home, bindir = tmp_path / "root", tmp_path / "home", tmp_path / "bin"
    for d in ( root, home, bindir ): d.mkdir()
    if venv is not None: fake_python( root / "venv-root" / "bin" / "python", venv ); ( root / ".venv" ).symlink_to( root / "venv-root" )
    if mcp is not None: fake_python( home / ".venv-lupin-mcp" / "bin" / "python", mcp )
    if system is not None: fake_python( bindir / "python3", system ); ( bindir.parent / "bin" ).mkdir( exist_ok=True )
    env = { "PATH": f"{bindir}:/usr/bin:/bin", "HOME": str( home ), "LUPIN_ROOT": str( root ), "REUSE_VECTOR_REFRESH_PATH": f"{bindir}:/usr/bin:/bin" }
    if explicit is not None: env[ "REUSE_VECTOR_REFRESH_PYTHON" ] = str( explicit )
    return subprocess.run( [ "bash", str( SCRIPT ), "--status" ], capture_output=True, text=True, env=env )


def test_a_venv_that_cannot_import_the_job_is_skipped_for_the_next_python_that_can( tmp_path ):
    done = run_wrapper( tmp_path, venv=False, mcp=True )
    assert done.returncode == 0 and "RAN .venv-lupin-mcp" in done.stdout
    assert ".venv/bin/python cannot import cosa.repo.symindex.vector_refresh" in done.stderr


def test_the_first_python_that_can_import_the_job_wins_and_later_ones_are_never_tried( tmp_path ):
    done = run_wrapper( tmp_path, venv=True, mcp=True )
    assert "RAN venv-root" in done.stdout and "cannot import" not in done.stderr


def test_an_explicit_python_that_can_import_is_used_first( tmp_path ):
    explicit = fake_python( tmp_path / "mine" / "bin" / "python", True )
    done = run_wrapper( tmp_path, explicit=explicit, venv=True )
    assert "RAN mine" in done.stdout


def test_the_system_python3_is_the_last_candidate( tmp_path ):
    done = run_wrapper( tmp_path, venv=False, mcp=False, system=True )
    assert done.returncode == 0 and "RAN " in done.stdout and done.stdout.count( "RAN" ) == 1


def test_no_python_that_can_import_the_job_is_a_refusal_naming_what_was_tried_and_the_fix( tmp_path ):
    done = run_wrapper( tmp_path, venv=False, mcp=False, system=False )
    assert done.returncode == 1 and done.stdout == ""
    assert "no Python can import cosa.repo.symindex.vector_refresh" in done.stderr and "Set REUSE_VECTOR_REFRESH_PYTHON" in done.stderr


def test_a_host_with_no_python_at_all_is_the_same_refusal( tmp_path ):
    done = run_wrapper( tmp_path )
    assert done.returncode == 1 and "no Python can import" in done.stderr
