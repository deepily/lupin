"""
The decision function behind the thread-credited-coverage detector.

Row `87ae7234`. `exclusive_lines` is what turns an attribution map into a verdict,
so it is the part worth pinning: everything around it is subprocess plumbing whose
behaviour is measured end-to-end in the row's doc, not asserted here.

The detector is stable in WHAT it names and not in HOW MUCH — a polling thread may
reach one extra line in one run and not the next (measured: threads identical across
3 runs, line total 34/33/34). These tests therefore fix the semantics of the
reduction, never a count taken from a live run.
"""
import os
import sys

import pytest

sys.path.insert( 0, os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src", "scripts" ) )

from detect_thread_credited_coverage import exclusive_lines, TEST_THREAD


class TestExclusiveLines:

    def test_a_daemon_line_the_test_thread_never_ran_is_reported( self ):
        attribution = {
            TEST_THREAD        : { "/src/a.py": [ 1, 2, 3 ] },
            "session-id-watcher": { "/src/a.py": [ 3, 4, 5 ] },
        }

        assert exclusive_lines( attribution, set() ) == {
            "session-id-watcher": { "/src/a.py": [ 4, 5 ] }
        }, "only the lines the test thread never reached should survive"

    def test_a_thread_that_ran_nothing_new_does_not_appear_at_all( self ):
        """
        NEGATIVE CONTROL for the reduction itself. A background thread that merely
        re-ran lines the tests already cover credits nothing, and reporting it would
        train the reader to ignore the output.
        """
        attribution = {
            TEST_THREAD : { "/src/a.py": [ 1, 2, 3 ] },
            "harmless"  : { "/src/a.py": [ 1, 2 ] },
        }

        assert exclusive_lines( attribution, set() ) == {}

    def test_the_test_thread_is_never_reported_against_itself( self ):
        attribution = { TEST_THREAD: { "/src/a.py": [ 1, 2, 3 ] } }

        assert exclusive_lines( attribution, set() ) == {}

    def test_an_allow_listed_thread_is_exempt( self ):
        """A worker a test starts deliberately, and then asserts on, earns its lines."""
        attribution = {
            TEST_THREAD  : { "/src/a.py": [ 1 ] },
            "deliberate" : { "/src/a.py": [ 9 ] },
        }

        assert exclusive_lines( attribution, { "deliberate" } ) == {}
        assert exclusive_lines( attribution, set() ) == { "deliberate": { "/src/a.py": [ 9 ] } }

    def test_a_file_the_test_thread_never_touched_is_reported_whole( self ):
        """The test thread's set is per-FILE; an untouched file must not read as covered."""
        attribution = {
            TEST_THREAD        : { "/src/a.py": [ 1 ] },
            "session-id-watcher": { "/src/b.py": [ 7, 8 ] },
        }

        assert exclusive_lines( attribution, set() ) == {
            "session-id-watcher": { "/src/b.py": [ 7, 8 ] }
        }

    def test_the_same_line_number_in_a_different_file_does_not_excuse_it( self ):
        """
        The reduction is per-FILE. Comparing against the union of every file the test
        thread touched would let `a.py:7` silently excuse `b.py:7` — two unrelated
        lines that share a number. Caught this gap by mutation: the union form passed
        every other test here.
        """
        attribution = {
            TEST_THREAD         : { "/src/a.py": [ 7 ] },
            "session-id-watcher": { "/src/b.py": [ 7, 8 ] },
        }

        assert exclusive_lines( attribution, set() ) == {
            "session-id-watcher": { "/src/b.py": [ 7, 8 ] }
        }, "line 7 of a.py says nothing about line 7 of b.py"

    def test_the_reported_lines_are_sorted_and_deduplicated( self ):
        attribution = {
            TEST_THREAD        : { "/src/a.py": [] },
            "session-id-watcher": { "/src/a.py": [ 9, 4, 9, 4, 1 ] },
        }

        assert exclusive_lines( attribution, set() ) == {
            "session-id-watcher": { "/src/a.py": [ 1, 4, 9 ] }
        }
