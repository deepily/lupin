"""
A wall-clock budget for each integration test FILE.

WHY (row 4cbd4858, 2026-10-02). `test_v2_eval_live` is one test that loops over 200 asks. Under
a monopoly hold every ask sat out a 120 s collect timeout, so the file would have run 6.7 hours
and held :8000 for all of it; the 09-24 run lost 3,424 s to the same file. pytest-timeout caps a
TEST, and nothing caps a FILE: a file of many slow tests, or one test with an inner loop and no
marker, has no ceiling at all.

WHAT IT DOES. The clock for a file starts at its first test. Each test is then given a timeout
equal to what is LEFT of the file's budget (or its own `@pytest.mark.timeout`, if that is
smaller), enforced by pytest-timeout. When the budget runs out:
    - the test that was running is stopped and reported as a failure naming the file:
      "<file> exceeded N minutes (stopped in <test>)"
    - if the budget ran out BETWEEN tests, the next test fails with the same message
    - every later test in that file is SKIPPED, with the reason naming the file, so the
      summary says exactly how many did not run
    - the next file starts with its own fresh budget, and the run ends normally with its
      summary and junit written

THE SETTING. LUPIN_TEST_INTEGRATION_FILE_TIMEOUT_MINUTES (the LUPIN_TEST_ prefix is what the
suite job's env allowlist forwards, so a scheduled submission can tune it). Default 15. 0 turns
the cap off. Anything that is not a non-negative number is an ERROR, never a silent default.

WHY 15. Measured 2026-10-02 from the last two full integration junits (09-24 and 10-01 EDT):
the longest file that is meant to run is test_job_queue_progressive_disclosure at 278-279 s;
next is test_swe_team_pipeline at 160 s; test_v2_eval_live passed in 196-285 s on 08-16..08-26.
15 minutes is about 3x the slowest legitimate file, and cuts the 3,424 s hang to 15 minutes.

LIMITS. The cap rides on pytest-timeout's signal method, so it interrupts a test blocked in
Python or in an interruptible system call; it cannot stop a test stuck in a C call that never
returns to the interpreter. A thread the test started is not killed with it.
"""

import os
import time
from typing import Callable, Dict, Optional

import pytest


SETTING_ENV     = "LUPIN_TEST_INTEGRATION_FILE_TIMEOUT_MINUTES"
DEFAULT_MINUTES = 15.0


def budget_minutes( environ: Optional[ Dict[ str, str ] ] = None ) -> float:
    """
    Read the setting.

    Requires:
        - environ is None (the process environment) or a mapping

    Ensures:
        - returns DEFAULT_MINUTES when the variable is unset or blank
        - returns the number of minutes otherwise; 0 means no cap

    Raises:
        - ValueError naming the variable when its value is not a non-negative number
    """
    environ = os.environ if environ is None else environ
    raw     = environ.get( SETTING_ENV, "" ).strip()
    if raw == "": return DEFAULT_MINUTES
    try:
        minutes = float( raw )
    except ValueError:
        raise ValueError( f"{SETTING_ENV}={raw!r} is not a number of minutes" ) from None
    if minutes < 0 or minutes != minutes:
        raise ValueError( f"{SETTING_ENV}={raw!r} must be a non-negative number of minutes (0 = no cap)" )
    return minutes


class FileBudget:
    """
    Per-file clocks.

    Requires:
        - minutes >= 0 (0 disables); clock is a monotonic seconds source
    """

    def __init__( self, minutes: float, clock: Callable[ [], float ] = time.monotonic ):
        self.minutes   = minutes
        self.limit     = minutes * 60.0
        self.clock     = clock
        self._started  = {}      # file -> clock reading at its first test
        self._reported = set()   # files whose one named failure has been issued

    @property
    def enabled( self ) -> bool:
        return self.limit > 0

    def remaining( self, file: str ) -> float:
        """Seconds left for `file`; its clock starts on the first call."""
        started = self._started.setdefault( file, self.clock() )
        return self.limit - ( self.clock() - started )

    def reported( self, file: str ) -> bool:
        return file in self._reported

    def mark_reported( self, file: str ) -> None:
        self._reported.add( file )

    def message( self, file: str, where: str ) -> str:
        return ( f"{file} exceeded {self.minutes:g} minutes ({SETTING_ENV}); stopped in {where}. "
                 f"Tests after it in this file were not run." )


def own_timeout( item ) -> Optional[ float ]:
    """The seconds a test's own `@pytest.mark.timeout` asks for, or None."""
    marker = item.get_closest_marker( "timeout" )
    if marker is None: return None
    value = marker.args[ 0 ] if marker.args else marker.kwargs.get( "timeout" )
    return None if value is None else float( value )


# ---- the hooks: import these into the integration conftest ------------------------------------
BUDGET = FileBudget( budget_minutes() )


def _file_of( item ) -> str:
    """The test's file as pytest names it (relative to the rootdir), so a message reads the same everywhere."""
    return item.nodeid.split( "::", 1 )[ 0 ]


@pytest.hookimpl( hookwrapper=True, tryfirst=True )
def pytest_runtest_protocol( item, nextitem ):
    """Arm this test's timeout with what is left of its file's budget, BEFORE pytest-timeout reads it."""
    item._file_budget_capped = False
    if BUDGET.enabled:
        left = BUDGET.remaining( _file_of( item ) )
        own  = own_timeout( item )
        if own is None or left < own:
            keep   = item.get_closest_marker( "timeout" )
            kwargs = dict( keep.kwargs ) if keep is not None else {}
            kwargs.pop( "timeout", None )
            item.add_marker( pytest.mark.timeout( max( left, 1.0 ), **kwargs ), append=False )
            item._file_budget_capped = True
    yield


@pytest.hookimpl( tryfirst=True )
def pytest_runtest_setup( item ):
    """Fail the first test to start after the budget is gone; skip the rest of the file."""
    if not BUDGET.enabled: return
    file = _file_of( item )
    if BUDGET.remaining( file ) > 0: return
    if BUDGET.reported( file ):
        pytest.skip( f"{file} exceeded {BUDGET.minutes:g} minutes; this test was not run" )
    BUDGET.mark_reported( file )
    pytest.fail( BUDGET.message( file, f"the gap before {item.nodeid}" ), pytrace=False )


@pytest.hookimpl( hookwrapper=True )
def pytest_runtest_makereport( item, call ):
    """Rename pytest-timeout's failure when the file's budget, not the test's own cap, was what fired."""
    outcome = yield
    report  = outcome.get_result()
    if not ( report.failed and call.excinfo is not None and BUDGET.enabled ): return
    if not getattr( item, "_file_budget_capped", False ): return
    if not call.excinfo.exconly().startswith( "Failed: Timeout" ): return
    BUDGET.mark_reported( _file_of( item ) )
    report.longrepr = BUDGET.message( _file_of( item ), item.nodeid )
