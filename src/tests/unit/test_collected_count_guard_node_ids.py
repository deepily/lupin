"""
The collected-count guard skips on a node id, as its docstring says.

A run that names a test by node id asked for a subset, like -k.
The census runner now names test_every_* functions by node id.
Two files carry this guard.
Without the skip it counted one collected test against all the file declares, and failed.
Each case runs a scratch test file in a fresh pytest, so the session the guard reads is a real one.
"""

import os
import subprocess
import sys

import cosa.utils.util as cu

SRC    = os.path.join( cu.get_project_root(), "src" )
GUARD  = "test_every_declared_test_is_collected"
CLEAN  = (
    "from tests.collected_count_guard import assert_every_declared_test_is_collected\n\n\n"
    "def test_one():\n    pass\n\n\n"
    f"def {GUARD}( request ):\n    assert_every_declared_test_is_collected( request, __file__ )\n"
)
# A test dedented out of its class lands inside the function above it: declared, never collected.
ORPHAN = CLEAN + "\n\ndef test_outer():\n    def test_dedented():\n        pass\n"


def pytest_run( tmp_path, source, *args ):
    """Write source as a scratch test file and run pytest on it, with the repo's src on the path."""
    ( tmp_path / "test_scratch.py" ).write_text( source, encoding="utf-8" )
    env = dict( os.environ, PYTHONPATH=SRC, PYTHONDONTWRITEBYTECODE="1" )
    return subprocess.run( [ sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--no-cov", *args ], cwd=tmp_path, env=env, capture_output=True, text=True, timeout=120 )


def test_a_run_that_names_the_guard_by_node_id_skips_it_though_the_file_declares_more( tmp_path ):
    done = pytest_run( tmp_path, CLEAN, f"test_scratch.py::{GUARD}" )
    assert done.returncode == 0 and "1 skipped" in done.stdout, done.stdout + done.stderr


def test_a_whole_file_run_still_fails_when_the_file_declares_a_test_pytest_does_not_collect( tmp_path ):
    done = pytest_run( tmp_path, ORPHAN, "test_scratch.py" )
    assert done.returncode == 1 and "test_dedented" in done.stdout, done.stdout + done.stderr


def test_a_whole_file_run_of_a_clean_file_passes_the_guard( tmp_path ):
    done = pytest_run( tmp_path, CLEAN, "test_scratch.py" )
    assert done.returncode == 0 and "2 passed" in done.stdout, done.stdout + done.stderr


def test_a_k_filtered_run_still_skips_the_guard( tmp_path ):
    done = pytest_run( tmp_path, CLEAN, "test_scratch.py", "-k", GUARD )
    assert done.returncode == 0 and "1 skipped" in done.stdout, done.stdout + done.stderr
