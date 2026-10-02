"""
Row 4cbd4858 — the per-file wall-clock cap for the integration tier.

Two layers: the arithmetic (FileBudget, budget_minutes) against a fake clock, and the
ENFORCEMENT, which runs a real pytest in a subprocess over a throwaway directory whose conftest
imports the real hooks, because a cap that was only unit-tested as arithmetic has not been shown
to stop anything.

Venue: :7999 (unit; one ~10 s subprocess).
"""

import os
import subprocess
import sys
import textwrap

import pytest

import cosa.utils.util as cu
from tests.helpers import file_budget as fb


# ---- the setting ----------------------------------------------------------------------------
@pytest.mark.parametrize( "env, expected", [
    ( {},                                      15.0 ),
    ( { fb.SETTING_ENV: "" },                  15.0 ),
    ( { fb.SETTING_ENV: "  " },                15.0 ),
    ( { fb.SETTING_ENV: "30" },                30.0 ),
    ( { fb.SETTING_ENV: "0.5" },               0.5 ),
    ( { fb.SETTING_ENV: "0" },                 0.0 ),
] )
def test_budget_minutes_reads_the_one_named_setting( env, expected ):
    assert fb.budget_minutes( env ) == expected


@pytest.mark.parametrize( "bad", [ "fifteen", "-1", "nan" ] )
def test_a_bad_value_is_an_error_naming_the_variable_never_the_default( bad ):
    with pytest.raises( ValueError, match=fb.SETTING_ENV ):
        fb.budget_minutes( { fb.SETTING_ENV: bad } )


def test_the_process_environment_is_the_default_source( monkeypatch ):
    monkeypatch.setenv( fb.SETTING_ENV, "7" )
    assert fb.budget_minutes() == 7.0


# ---- the clocks -----------------------------------------------------------------------------
class _Clock:
    def __init__( self ): self.now = 100.0
    def __call__( self ): return self.now


def test_each_file_has_its_own_clock_that_starts_at_its_first_test():
    clock  = _Clock()
    budget = fb.FileBudget( 1.0, clock )
    assert budget.remaining( "a.py" ) == 60.0
    clock.now += 45
    assert budget.remaining( "a.py" ) == 15.0
    assert budget.remaining( "b.py" ) == 60.0, "a new file starts a fresh budget"
    clock.now += 20
    assert budget.remaining( "a.py" ) == -5.0 and budget.remaining( "b.py" ) == 40.0


def test_zero_disables_and_the_message_names_file_limit_and_setting():
    assert not fb.FileBudget( 0 ).enabled and fb.FileBudget( 15 ).enabled
    message = fb.FileBudget( 15 ).message( "x/test_y.py", "x/test_y.py::test_z" )
    assert "x/test_y.py exceeded 15 minutes" in message and fb.SETTING_ENV in message and "test_z" in message


def test_reported_is_per_file():
    budget = fb.FileBudget( 1 )
    budget.mark_reported( "a.py" )
    assert budget.reported( "a.py" ) and not budget.reported( "b.py" )


# ---- enforcement, end to end ----------------------------------------------------------------
def _run( tmp_path, minutes, files ):
    ( tmp_path / "conftest.py" ).write_text( textwrap.dedent( """
        from tests.helpers.file_budget import (
            pytest_runtest_makereport, pytest_runtest_protocol, pytest_runtest_setup )
    """ ) )
    ( tmp_path / "pytest.ini" ).write_text( "[pytest]\nmarkers =\n    timeout: x\n" )
    for name, body in files.items():
        ( tmp_path / name ).write_text( textwrap.dedent( body ) )
    environment = dict( os.environ, PYTHONPATH=os.path.join( cu.get_project_root(), "src" ),
                        **{ fb.SETTING_ENV: str( minutes ) } )
    return subprocess.run(
        [ sys.executable, "-m", "pytest", str( tmp_path ), "-q", "-p", "no:cacheprovider", "-rA",
          f"--junitxml={tmp_path / 'junit.xml'}" ],
        cwd=tmp_path, env=environment, capture_output=True, text=True, timeout=120 )


def test_a_file_that_overruns_is_stopped_named_and_the_run_carries_on( tmp_path ):
    result = _run( tmp_path, 0.05, {      # 3 seconds
        "test_slow.py": """
            import time
            def test_first():  pass
            def test_hangs():  time.sleep( 60 )
            def test_after():  pass
            def test_after2(): pass
        """,
        "test_other.py": """
            def test_fine(): pass
        """,
    } )
    out = result.stdout
    assert result.returncode == 1, out
    assert "test_slow.py exceeded 0.05 minutes" in out and "stopped in" in out and "test_hangs" in out
    assert "PASSED test_slow.py::test_first" in out
    assert "SKIPPED [2]" in out and "was not run" in out, out
    assert "PASSED test_other.py::test_fine" in out, "the next file must still run, on a fresh budget"
    assert "1 failed, 2 passed, 2 skipped" in out, out
    assert ( tmp_path / "junit.xml" ).exists(), "junit must still be written"
    assert "Timeout (>" not in out, "the failure carries the file's name, not pytest-timeout's wording"


def test_a_budget_that_runs_out_between_tests_fails_the_next_one( tmp_path ):
    result = _run( tmp_path, 0.05, {
        "test_many.py": """
            import time
            def test_a(): time.sleep( 2 )
            def test_b(): time.sleep( 2 )
            def test_c(): pass
            def test_d(): pass
        """,
    } )
    out = result.stdout
    assert "test_many.py exceeded 0.05 minutes" in out, out
    assert out.count( "FAILED" ) >= 1 and "1 failed" in out, out
    assert "was not run" in out


def test_a_test_with_its_own_smaller_timeout_keeps_it( tmp_path ):
    result = _run( tmp_path, 15, {
        "test_own.py": """
            import time, pytest
            @pytest.mark.timeout( 1 )
            def test_own_cap(): time.sleep( 30 )
        """,
    } )
    out = result.stdout
    assert "Timeout (>1.0s)" in out, "the test's own 1 s cap must fire, not be raised to the file's budget"
    assert "exceeded" not in out


def test_zero_means_no_cap( tmp_path ):
    result = _run( tmp_path, 0, {
        "test_free.py": """
            import time
            def test_a(): time.sleep( 1 )
            def test_b(): pass
        """,
    } )
    assert "2 passed" in result.stdout, result.stdout
