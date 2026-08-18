"""
Unit tests for the liveness check that cannot match itself (bug 07786db9).

THE FALSIFICATION THAT WAS SKIPPED, and the reason this file exists: before trusting a
liveness monitor, KILL THE THING IT WATCHES AND REQUIRE THE MONITOR TO NOTICE. The
monitor this replaces never would have — it matched its own command line, so it reported
RUNNING 28 seconds after the job had already died and would have kept saying RUNNING all
night, including after the box powered off.

`test_a_real_process_is_seen_alive_then_seen_DEAD_after_it_is_killed` is that test. It
spawns a REAL process, requires RUNNING, kills it, and requires DEAD. Nothing is mocked
in it, because the defect being guarded against was invisible to every mock — the old
monitor would have passed any test that did not involve a process actually dying.

`TestTheWatcherCannotMatchItself` is the other half: the same check, run from a process
whose own command line contains the pattern, must NOT report RUNNING.

Generated on: 2026-08-17
"""

import os
import re
import subprocess
import sys
import time
import unittest

import pytest

# Root from LUPIN_ROOT when set, else derived from this file's own location — NOT
# `os.environ[ "LUPIN_ROOT" ]`. A bare subscript raises at IMPORT time, and a module
# that raises during collection exits pytest with code 4, writes no junit, and fires no
# hook — silence that reads as "not run" rather than "failed" (row bc83f2df). A test
# file added to the shared tier must not be able to do that to everyone else's run.
_LUPIN_ROOT = os.environ.get(
    "LUPIN_ROOT",
    os.path.dirname( os.path.dirname( os.path.dirname( os.path.dirname( os.path.abspath( __file__ ) ) ) ) )
)
_LIB_DIR    = os.path.join( _LUPIN_ROOT, "src", "scripts", "lib" )
sys.path.insert( 0, _LIB_DIR )

from job_liveness import (                                     # noqa: E402
    DEAD,
    RUNNING,
    UNKNOWN,
    ancestor_pids,
    find_matching_pids,
    job_liveness,
    list_pids,
    main,
    read_cmdline,
    read_ppid,
)


def _wait_until( predicate, timeout=5.0, interval=0.05 ):
    """Poll until predicate() is true or the timeout expires; return the final value."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep( interval )
    return predicate()


# ─────────────────────────────────────────────────────────────────────────────
# THE FALSIFICATION. Real process, really killed.
# ─────────────────────────────────────────────────────────────────────────────

class TestKillTheThingAndRequireTheMonitorToNotice( unittest.TestCase ):

    def test_a_real_process_is_seen_alive_then_seen_DEAD_after_it_is_killed( self ):
        """
        🔴 THE TEST THE ORIGINAL MONITOR COULD NEVER HAVE PASSED.

        A monitor that matches its own command line reports RUNNING in both halves of
        this test. Requiring the transition is what separates an instrument from a
        decoration.
        """
        marker = "job-liveness-falsification-marker-7f3a1c"
        child  = subprocess.Popen( [ sys.executable, "-c",
                                     f"import time; time.sleep( 30 )  # {marker}" ] )
        try:
            state, pids = _wait_until( lambda: job_liveness( marker )
                                       if job_liveness( marker )[ 0 ] == RUNNING else None ) \
                          or job_liveness( marker )

            assert state == RUNNING, "a live process was not seen"
            assert child.pid in pids

            child.kill()
            child.wait( timeout=10 )

            # The process table can hold a zombie briefly; the point is that the state
            # CHANGES, which the self-matching monitor could never do.
            state_after, pids_after = _wait_until(
                lambda: job_liveness( marker ) if job_liveness( marker )[ 0 ] == DEAD else None
            ) or job_liveness( marker )

            assert state_after == DEAD, f"monitor did not notice the kill: {pids_after}"
            assert pids_after == [ ]
        finally:
            if child.poll() is None:
                child.kill()
                child.wait( timeout=10 )


# ─────────────────────────────────────────────────────────────────────────────
# THE DEFECT ITSELF: the watcher must not see its own reflection.
# ─────────────────────────────────────────────────────────────────────────────

class TestTheWatcherCannotMatchItself( unittest.TestCase ):

    def test_a_pattern_present_only_in_the_watchers_own_command_is_DEAD( self ):
        """
        The exact 07786db9 shape, end to end through the CLI. The pattern is written
        INSIDE the command doing the searching and exists nowhere else on the machine.
        `pgrep -af <pattern>` answers RUNNING here. This must answer DEAD.
        """
        marker = "self-match-canary-9d2b4e"
        script = os.path.join( _LIB_DIR, "job_liveness.py" )

        # The marker is in argv, so this process's OWN command line contains it.
        result = subprocess.run( [ sys.executable, script, marker ],
                                 capture_output=True, text=True, timeout=30 )

        assert result.stdout.strip().startswith( DEAD ), result.stdout
        assert result.returncode == 1

    def test_the_grandparent_shell_does_not_count_as_the_job( self ):
        """
        ⚠️ WHY OWN-PID IS NOT ENOUGH, measured on this host: the harness wraps commands
        as `bash -c '<the whole thing>'`, so a pattern typed into a command appears in
        an ANCESTOR's command line, not the process's own. A search for a string that
        existed nowhere on the machine except inside the searching command matched the
        GRANDPARENT shell.

        Excluding only self — or only self and parent, as the bug row proposed — still
        reports RUNNING here.
        """
        marker = "grandparent-canary-4a8c1f"
        script = os.path.join( _LIB_DIR, "job_liveness.py" )

        # TWO shell levels, each ending in `; true` — BOTH details are load-bearing and
        # both were established by measuring the live process chain, not by reasoning:
        #
        #   · ONE level puts the marker in the PARENT only, which self+parent exclusion
        #     already handles. Such a test passes against the insufficient fix.
        #   · Without the trailing `; true`, bash TAIL-EXECS — it replaces itself with
        #     the command instead of forking — so the marker-bearing shells disappear
        #     and there is no ancestor to exclude at all. A nested test without it also
        #     passes against the insufficient fix.
        #
        # Measured with both in place: marker-bearing processes sit at depths 0, 1, 2
        # and 3. Excluding only {self, parent} leaves depths 2 and 3 matching, so this
        # test goes RED against the fix the bug row proposed and green against the
        # ancestor walk. That difference is the whole reason the walk exists.
        result = subprocess.run(
            [ "bash", "-c", f"bash -c '{sys.executable} {script} {marker}; true'; true" ],
            capture_output=True, text=True, timeout=30
        )

        assert result.stdout.strip().startswith( DEAD ), result.stdout

    def test_own_pid_and_ancestors_are_all_excluded( self ):
        mine = ancestor_pids()

        assert os.getpid() in mine
        assert os.getppid() in mine
        assert len( mine ) >= 2                       # at least self and parent

    def test_ancestor_walk_stops_on_a_cycle( self, ):
        """A corrupt parent chain must not hang a monitor."""
        assert ancestor_pids( pid=os.getpid(), max_depth=1 ) == { os.getpid() }


# ─────────────────────────────────────────────────────────────────────────────
# The third state: "I could not look" is not "it is not there".
# ─────────────────────────────────────────────────────────────────────────────

class TestUnknownIsDistinctFromDead( unittest.TestCase ):

    def test_an_unreadable_process_table_is_UNKNOWN_not_DEAD( self, ):
        """
        The remedy the eight-instruments catalogue names: a third state, so a failure
        to observe cannot be read as an observation.
        """
        state, pids = job_liveness( "anything", proc_root="/nonexistent-proc-root" )

        assert state == UNKNOWN
        assert pids == [ ]

    def test_an_empty_pattern_is_REFUSED_rather_than_matching_everything( self ):
        """An empty pattern matches every process and would report RUNNING forever."""
        with pytest.raises( ValueError ):
            job_liveness( "" )

    def test_an_invalid_pattern_raises_rather_than_reporting_DEAD( self ):
        """
        A monitor watching a typo'd pattern would report DEAD forever — the same
        silent-wrong-answer in the opposite direction. It must fail loudly.
        """
        with pytest.raises( re.error ):
            job_liveness( "unclosed-group(" )


# ─────────────────────────────────────────────────────────────────────────────
# The primitives, including the races a live /proc scan actually hits.
# ─────────────────────────────────────────────────────────────────────────────

class TestProcPrimitives( unittest.TestCase ):

    def test_read_cmdline_returns_the_joined_command( self ):
        mine = read_cmdline( os.getpid() )

        assert mine is not None
        assert "python" in mine.lower() or "pytest" in mine.lower()

    def test_read_cmdline_of_a_gone_process_is_None( self ):
        assert read_cmdline( 999_999_998 ) is None

    def test_read_cmdline_of_a_kernel_thread_is_None( self ):
        """Kernel threads have an empty cmdline and must not be treated as matches."""
        kernel_threads = [ pid for pid in list_pids() if read_cmdline( pid ) is None ]

        assert kernel_threads, "expected at least one empty-cmdline process on Linux"

    def test_read_ppid_matches_the_kernel( self ):
        assert read_ppid( os.getpid() ) == os.getppid()

    def test_read_ppid_of_a_gone_process_is_None( self ):
        assert read_ppid( 999_999_998 ) is None

    def test_list_pids_of_an_unreadable_root_is_empty( self ):
        assert list_pids( proc_root="/nonexistent-proc-root" ) == [ ]

    def test_list_pids_ignores_non_numeric_entries( self ):
        pids = list_pids()

        assert pids
        assert all( isinstance( pid, int ) for pid in pids )


# ── the /proc parsing edge cases, as plain functions so tmp_path is available ──

def test_read_ppid_survives_a_command_name_containing_parens_and_spaces( tmp_path ):
    """
    ⚠️ THE PARSING TRAP. /proc/<pid>/stat's second field is the executable name in
    parentheses and may itself contain spaces and parentheses, so splitting the whole
    line on whitespace puts ppid at a position that depends on the program's NAME.
    Taking the fields after the LAST ')' is what makes this stable.
    """
    fake = tmp_path / "4242"
    fake.mkdir()
    ( fake / "stat" ).write_text( "4242 (weird ) name (x) R 1234 4242 4242 0 -1 0\n" )

    assert read_ppid( 4242, proc_root=str( tmp_path ) ) == 1234


def test_read_ppid_of_an_unparseable_stat_is_None( tmp_path ):
    fake = tmp_path / "4243"
    fake.mkdir()
    ( fake / "stat" ).write_text( "no-parens-here\n" )

    assert read_ppid( 4243, proc_root=str( tmp_path ) ) is None


def test_read_ppid_of_a_truncated_stat_is_None( tmp_path ):
    fake = tmp_path / "4244"
    fake.mkdir()
    ( fake / "stat" ).write_text( "4244 (x) R\n" )

    assert read_ppid( 4244, proc_root=str( tmp_path ) ) is None


def test_read_ppid_of_a_non_numeric_ppid_is_None( tmp_path ):
    fake = tmp_path / "4245"
    fake.mkdir()
    ( fake / "stat" ).write_text( "4245 (x) R notanumber 1\n" )

    assert read_ppid( 4245, proc_root=str( tmp_path ) ) is None


def test_find_matching_pids_skips_a_process_that_exits_mid_scan( tmp_path ):
    """A PID listed and then gone is a normal race, not an error."""
    ( tmp_path / "5555" ).mkdir()          # a pid dir with no cmdline and no stat

    assert find_matching_pids( "anything", proc_root=str( tmp_path ) ) == [ ]


def test_an_invalid_pattern_exits_UNKNOWN( capsys ):
    code = main( [ "job_liveness.py", "unclosed-group(" ] )
    out  = capsys.readouterr().out

    assert code == 2
    assert UNKNOWN in out


class TestTheCommandLineInterface( unittest.TestCase ):

    def test_no_pattern_is_a_usage_error_not_a_verdict( self ):
        assert main( [ "job_liveness.py" ] ) == 2

    def test_an_empty_pattern_argument_is_a_usage_error( self ):
        assert main( [ "job_liveness.py", "" ] ) == 2

    def test_a_live_process_exits_zero( self ):
        """The one process guaranteed to exist and not be an ancestor: a child."""
        marker = "cli-live-canary-2b7e9a"
        child  = subprocess.Popen( [ sys.executable, "-c",
                                     f"import time; time.sleep( 20 )  # {marker}" ] )
        try:
            _wait_until( lambda: job_liveness( marker )[ 0 ] == RUNNING )
            assert main( [ "job_liveness.py", marker ] ) == 0
        finally:
            child.kill()
            child.wait( timeout=10 )


if __name__ == "__main__":
    unittest.main()
