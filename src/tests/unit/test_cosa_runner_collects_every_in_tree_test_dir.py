"""
The cosa wrapper collects every tracked test directory under src/cosa.

Seven files with about 286 tests sat under src/cosa/agents/*/tests/. No runner named them, so
they could never go red at the merge gate. The guard takes its population from git, not from the
wrapper, so a new per-agent test directory that the wrapper leaves out fails here.
"""
import re
import subprocess

import cosa.utils.util as cu

ROOT    = cu.get_project_root()
WRAPPER = f"{ROOT}/src/tests/run-cosa-tests.sh"
CORE    = "src/cosa/tests/"

KNOWN_PER_AGENT_FILES = 7


def _tracked_test_files_outside_the_core_tree():
    """Tracked `test_*.py` files under a `tests` folder in src/cosa, outside src/cosa/tests/."""
    listed = subprocess.run( [ "git", "-C", ROOT, "ls-files", "--", "src/cosa" ], capture_output=True, text=True, check=True ).stdout.split()
    return sorted(
        path for path in listed
        if re.search( r"(^|/)tests/", path ) and re.search( r"(^|/)test_[^/]*\.py$", path ) and not path.startswith( CORE )
    )


def _dirs_the_wrapper_names():
    """The `src/...` paths on the line that runs pytest, as the wrapper's own text spells them."""
    text   = open( WRAPPER, encoding="utf-8" ).read()
    quoted = re.search( r'^CORE_DIRS="([^"]*)"', text, re.M )
    assert quoted, "the wrapper no longer names its test directories in CORE_DIRS"
    return quoted.group( 1 ).split()


def test_the_guard_finds_the_known_per_agent_files():
    """The loop below means nothing over an empty population."""
    files = _tracked_test_files_outside_the_core_tree()
    assert len( files ) >= KNOWN_PER_AGENT_FILES, files
    assert any( "podcast_generator/tests/" in f for f in files ) and any( "prediction_engine/tests/" in f for f in files )


def test_every_tracked_test_file_outside_the_core_tree_sits_under_a_directory_the_wrapper_names():
    """Kills the mutant that drops a per-agent directory from the wrapper."""
    named   = _dirs_the_wrapper_names()
    missing = [ f for f in _tracked_test_files_outside_the_core_tree() if not any( f.startswith( d ) for d in named ) ]
    assert missing == [], f"collected by no runner: {missing}"


def test_the_wrapper_still_runs_the_core_tree_and_passes_the_named_dirs_to_pytest():
    text = open( WRAPPER, encoding="utf-8" ).read()
    assert CORE in _dirs_the_wrapper_names()
    assert re.search( r'^run_pytest_with_diagnosis "\$PYTEST" \$CORE_DIRS \$COV_FLAGS "\$@"', text, re.M )


def test_the_production_modules_that_only_look_like_tests_are_not_in_the_population():
    """swe_team/test_runner.py and the test_suite modules are production code."""
    files = " ".join( _tracked_test_files_outside_the_core_tree() )
    for production in ( "swe_team/test_runner.py", "rest/routers/test_suite.py", "rest/test_suite_completion_watchdog.py" ):
        assert production not in files
