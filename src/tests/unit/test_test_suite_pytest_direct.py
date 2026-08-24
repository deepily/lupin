"""
Unit tests for the `pytest_direct` test suite type.

Session 9056c113 doc 16 follow-up — enables scheduling an arbitrary pytest
file via the notifications UI test-suite submit card. Parallel to the
existing `smoke_direct` type (which runs `python3 <file>`), this new type
runs `pytest <file>` so files with fixtures / markers / parametrize
decorators work.
"""

import os
import stat

import pytest


class TestPytestDirectRegistration:
    """pytest_direct is registered in test_suite/job.py alongside smoke_direct."""

    def test_pytest_direct_in_suite_scripts( self ):
        from cosa.agents.test_suite.job import SUITE_SCRIPTS
        assert "pytest_direct" in SUITE_SCRIPTS
        assert SUITE_SCRIPTS[ "pytest_direct" ] == "src/tests/run-pytest-direct.sh"

    def test_pytest_direct_has_timeout( self ):
        from cosa.agents.test_suite.job import SUITE_TIMEOUTS_SECONDS
        assert "pytest_direct" in SUITE_TIMEOUTS_SECONDS
        # Matches smoke_direct (both are file-driven with similar budgets)
        assert SUITE_TIMEOUTS_SECONDS[ "pytest_direct" ] == SUITE_TIMEOUTS_SECONDS[ "smoke_direct" ]

    def test_file_driven_test_types_constant_exists( self ):
        """Backend exposes FILE_DRIVEN_TEST_TYPES as the single source of truth."""
        from cosa.agents.test_suite.job import FILE_DRIVEN_TEST_TYPES
        assert isinstance( FILE_DRIVEN_TEST_TYPES, frozenset )
        assert "smoke_direct" in FILE_DRIVEN_TEST_TYPES
        assert "pytest_direct" in FILE_DRIVEN_TEST_TYPES

    def test_file_driven_types_are_subset_of_suite_scripts( self ):
        """Every file-driven type must have a corresponding shell script registered."""
        from cosa.agents.test_suite.job import FILE_DRIVEN_TEST_TYPES, SUITE_SCRIPTS
        for t in FILE_DRIVEN_TEST_TYPES:
            assert t in SUITE_SCRIPTS, f"File-driven type {t!r} missing from SUITE_SCRIPTS"


class TestPytestDirectScript:
    """The shell script exists, is executable, and delegates to pytest."""

    @pytest.fixture
    def script_path( self ):
        import cosa.utils.util as cu
        return cu.get_project_root() + "/src/tests/run-pytest-direct.sh"

    def test_script_exists( self, script_path ):
        assert os.path.exists( script_path ), f"Script missing at {script_path}"

    def test_script_is_executable( self, script_path ):
        mode = os.stat( script_path ).st_mode
        # Owner, group, and world execute bits
        assert mode & stat.S_IXUSR, "Script is not owner-executable"
        assert mode & stat.S_IXGRP, "Script is not group-executable"

    def test_script_delegates_to_pytest( self, script_path ):
        """The script must run the caller's arguments THROUGH PYTEST, not through a plain
        `python3 file.py` (which silently skips fixtures, markers and parametrize).

        ⚠️ THIS TEST USED TO ASSERT ON `exec` ITSELF, and that made it a test of the
        delivery mechanism rather than of the delegation. Row 73c6819d had to DROP the
        exec: `exec` replaces the shell, so nothing is left to read pytest's exit code —
        and on a conftest collection error that code is the only signal there is. The
        proposition worth keeping is "pytest gets the caller's arguments", so that is what
        is asserted now; the copy-paste guard against a bare `python3 file.py` stays.

        ⚠️ AND IT USED TO ASSERT THE SPELLING `-m pytest` SPECIFICALLY, which made it fail
        for the wrong reason on 2026-08-24 (row fc74c1d4). That row stopped this script
        running pytest through a bare `python3` — a bare python3 is whatever is on PATH, and
        an under-provisioned one under-collects while the reduced count gets reported as the
        whole suite (row c98bce3f). The script now calls `"$PYTEST"`, resolved by
        src/scripts/lib/resolve-venv-pytest.sh to a real .venv/bin/pytest binary, so fixtures,
        markers and parametrize all work exactly as before — the property this test cares
        about is intact and only the spelling changed. So both forms are accepted: an
        `-m pytest` module invocation, or a resolved pytest binary.
        """
        with open( script_path, "r" ) as f:
            content = f.read()
        invocations = [ l.strip() for l in content.splitlines()
                        if "pytest" in l and "$@" in l and not l.strip().startswith( "#" ) ]

        assert invocations, f"No line passing \"$@\" to pytest found in {script_path}"
        assert any( ( "-m pytest" in l ) or ( "$PYTEST" in l ) for l in invocations ), (
            f"{script_path} must run the caller's arguments through pytest — either as "
            f"`<python> -m pytest` or as a resolved `\"$PYTEST\"` binary — and not as a plain "
            f"`python3 file.py` the way run-smoke-direct.sh does; fixtures, markers and "
            f"parametrize do not work that way. Lines seen: {invocations}"
        )
