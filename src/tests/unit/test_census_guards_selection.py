"""
The census runner's selection: a test_every_* guard runs wherever it lives.

The runner picks whole files by name.
A test_every_* function in an ordinarily named file was never run as census.
It went red on a commit and no census run noticed.
The runner now also picks each test_every_* function of every other tracked unit file, by node id.
These tests drive its --list mode on the tracked tree, which prints the selection and runs nothing.
"""

import os
import subprocess

import pytest

import cosa.utils.util as cu

PROJECT_ROOT = cu.get_project_root()
RUNNER       = os.path.join( PROJECT_ROOT, "src", "tests", "run-census-guards.sh" )
GUARD_DEF    = r"^\s*(async )?def test_every_"

# A real guard in a file whose name does not match the name rule: bug a197b338's own example.
EXAMPLE      = "src/tests/unit/test_symindex_search_scope.py::test_every_read_symbols_call_in_src_is_an_allowed_one"
# A file the name rule picks, so the runner keeps running it whole.
BY_NAME      = "src/tests/unit/test_reuse_needset_census.py"


def listing():
    """Return the lines the runner selects; a runner that ignores --list fails in 30 seconds."""
    try:
        done = subprocess.run( [ "bash", RUNNER, "--list" ], capture_output=True, text=True, timeout=30, cwd=PROJECT_ROOT )
    except subprocess.TimeoutExpired:
        pytest.fail( "the runner did not stop at --list" )
    assert done.returncode == 0, done.stdout + done.stderr
    return done.stdout.splitlines()


def test_a_test_every_guard_in_an_ordinarily_named_file_is_selected():
    assert EXAMPLE in listing()


def test_no_tracked_unit_file_that_holds_a_test_every_function_is_left_out():
    held = subprocess.run( [ "git", "grep", "-l", "-E", GUARD_DEF, "--", "src/tests/unit/*.py" ], capture_output=True, text=True, timeout=60, cwd=PROJECT_ROOT )
    files = held.stdout.split()
    lines = listing()
    assert held.returncode == 0 and files, held.stderr
    left_out = [ f for f in files if not any( line == f or line.startswith( f + "::" ) for line in lines ) ]
    assert left_out == []


def test_a_file_picked_by_name_is_still_run_whole():
    lines = listing()
    assert BY_NAME in lines
    assert not any( line.startswith( BY_NAME + "::" ) for line in lines )
