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
        """The script must invoke `python3 -m pytest`, not `python3` directly
        (otherwise fixtures / markers / parametrize won't work)."""
        with open( script_path, "r" ) as f:
            content = f.read()
        # The exec line must call pytest
        assert "python3 -m pytest" in content or "pytest" in content.split( "exec " )[ -1 ]
        # Must NOT be a plain python3 invocation like smoke_direct
        # (guard against accidental copy-paste regression)
        exec_lines = [ l for l in content.splitlines() if l.strip().startswith( "exec " ) ]
        assert any( "pytest" in l for l in exec_lines ), \
            f"No `exec ... pytest ...` line found in {script_path}"
