"""
The measure-xdist-coverage-arms script: usage line, refusal without a venv, compare path.

The guard test only checks that the script sources the shared resolver. These tests run a copy of it in a small tree.
So dropping the `|| exit $?` after the resolver call turns a test red. So does changing the interpreter compare uses.
"""
import os
import pathlib
import shutil
import subprocess

import pytest

import cosa.utils.util as cu

REPO     = pathlib.Path( cu.get_project_root() )
SCRIPT   = "src/scripts/measure-xdist-coverage-arms.sh"
RESOLVER = "src/scripts/lib/resolve-venv-pytest.sh"


def make_tree( tmp_path, with_venv ):
    """Copy the script and resolver into a tree, with a stub venv python."""
    for rel in ( SCRIPT, RESOLVER ):
        ( tmp_path / rel ).parent.mkdir( parents=True, exist_ok=True )
        shutil.copy( REPO / rel, tmp_path / rel )
    if with_venv:
        stub = tmp_path / ".venv" / "bin" / "python3"
        stub.parent.mkdir( parents=True )
        stub.write_text( '#!/bin/bash\n[ "$1" = "--version" ] && exit 0\necho "stub-python $*" > "$STUB_OUT"\n', encoding="utf-8" )
        stub.chmod( 0o755 )
    return tmp_path


def run( tree, *args ):
    """Run the copied script and return the finished process."""
    return subprocess.run( [ "bash", str( tree / SCRIPT ), *args ], capture_output=True, text=True, env={ **os.environ, "STUB_OUT": str( tree / "stub.out" ) } )


def test_a_tree_with_no_venv_python_is_refused_with_exit_3_and_the_resolver_message( tmp_path ):
    if os.path.exists( "/opt/venv/bin/python3" ): pytest.skip( "this host has the in-container venv, so the refusal cannot be reached" )
    done = run( make_tree( tmp_path, False ), "compare", "a", "b" )
    assert done.returncode == 3 and "no runnable venv python found" in done.stderr


def test_compare_runs_the_python_the_resolver_found_with_the_two_data_files( tmp_path ):
    tree = make_tree( tmp_path, True )
    done = run( tree, "compare", "data-a", "data-b" )
    assert done.returncode == 0 and ( tree / "stub.out" ).read_text( encoding="utf-8" ).strip() == "stub-python - data-a data-b"


def test_no_arguments_print_the_usage_line_and_exit_2( tmp_path ):
    done = run( make_tree( tmp_path, True ) )
    assert done.returncode == 2 and "usage: see the header" in done.stderr
