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


from detect_thread_credited_coverage import (
    bucket_findings, call_time_lines, make_scope_classifier, verdict_exit_code
)


class TestCallTimeLines:
    """
    Section 3 of `src/rnd/v0.2.0/2026.08.26-thread-attribution-needs-a-scope-bucket.md`.

    The classifier decides whether a reported line is a FINDING or a declaration the
    tracer happened to see on a worker thread. Its one dangerous mistake is crediting
    a `def` line to the body it introduces: a def executes at import, so counting it
    as call-time invents a finding that never happened. Every case below is a source
    string with its line numbers fixed by construction, never a live measurement.
    """

    def test_a_def_line_and_its_decorator_are_not_part_of_the_body( self ):
        """
        THE REQUIREMENT THIS FILE EXISTS FOR. Classifying by the function's own
        `lineno..end_lineno` span - rather than by `node.body` - sweeps the `def` and
        its decorators into call-time. Both run at import.
        """
        source = (
            "import os\n"            # 1
            "\n"                     # 2
            "CONSTANT = 1\n"         # 3
            "\n"                     # 4
            "@decorate\n"            # 5
            "def f( a ):\n"          # 6
            "    x = a + 1\n"        # 7
            "    return x\n"         # 8
        )

        assert call_time_lines( source ) == { 7, 8 }, \
            "only the body statements execute when f is called"

    def test_a_module_scope_class_body_is_not_call_time( self ):
        source = (
            "class C:\n"             # 1
            "    field = 2\n"        # 2
            "    other = 3\n"        # 3
        )

        assert call_time_lines( source ) == set()

    def test_the_same_class_body_inside_a_function_is_call_time( self ):
        """The discriminator is the enclosing scope, not the statement's own kind."""
        source = (
            "class Top:\n"           # 1
            "    a = 1\n"            # 2
            "\n"                     # 3
            "def make():\n"          # 4
            "    class Inner:\n"     # 5
            "        b = 2\n"        # 6
            "    return Inner\n"     # 7
        )

        assert call_time_lines( source ) == { 5, 6, 7 }

    def test_a_nested_def_and_its_decorator_do_run_at_the_outer_calls_time( self ):
        """
        The mirror of the first test. An inner `def` is a STATEMENT IN THE OUTER BODY,
        so it executes when `outer` is called - it must be counted, and dropping every
        def line unconditionally would lose it.
        """
        source = (
            "def outer():\n"         # 1
            "    @deco\n"            # 2
            "    def inner():\n"     # 3
            "        return 1\n"     # 4
            "    return inner\n"     # 5
        )

        assert call_time_lines( source ) == { 2, 3, 4, 5 }

    def test_a_multi_line_statement_in_a_body_counts_whole( self ):
        source = (
            "def f():\n"             # 1
            "    d = {\n"            # 2
            "        'k': 1,\n"      # 3
            "    }\n"                # 4
            "    return d\n"         # 5
        )

        assert call_time_lines( source ) == { 2, 3, 4, 5 }

    def test_an_async_function_body_is_call_time_too( self ):
        source = (
            "async def f():\n"       # 1
            "    return 1\n"         # 2
        )

        assert call_time_lines( source ) == { 2 }

    def test_source_that_does_not_parse_raises( self ):
        with pytest.raises( SyntaxError ):
            call_time_lines( "def f(:\n" )


class TestScopeClassifier:

    def test_a_file_that_cannot_be_read_is_treated_as_call_time( self, tmp_path ):
        """
        An unclassifiable file must NOT vanish from the verdict. The tool may fail to
        parse it; it may not decide on that basis that there is nothing to see.
        """
        is_call_time = make_scope_classifier()

        assert is_call_time( str( tmp_path / "gone.py" ), 12 ) is True

    def test_a_real_file_is_classified_by_its_bodies( self, tmp_path ):
        path = tmp_path / "m.py"
        path.write_text( "X = 1\ndef f():\n    return 2\n" )
        is_call_time = make_scope_classifier()

        assert is_call_time( str( path ), 1 ) is False, "X = 1 runs at import"
        assert is_call_time( str( path ), 2 ) is False, "the def line runs at import"
        assert is_call_time( str( path ), 3 ) is True,  "the return runs when f is called"

    def test_the_file_is_parsed_once_and_reused( self, tmp_path ):
        """
        The cache is the whole reason a per-run AST parse is affordable. Rewriting the
        file between two calls must not change the answer.
        """
        path = tmp_path / "m.py"
        path.write_text( "def f():\n    return 2\n" )
        is_call_time = make_scope_classifier()

        assert is_call_time( str( path ), 2 ) is True
        path.write_text( "A = 1\nB = 2\n" )
        assert is_call_time( str( path ), 2 ) is True, "the second answer came from the cache"


class TestBucketFindings:

    ATTRIBUTION = {
        TEST_THREAD  : { "/src/a.py": [ 1 ] },
        "worker"     : { "/src/a.py": [ 4, 9 ] },
        "deliberate" : { "/src/a.py": [ 7 ] },
    }

    @staticmethod
    def _only_line_4( fn, line ):
        return line == 4

    def test_a_workers_lines_split_into_call_time_and_module_scope( self ):
        buckets = bucket_findings( self.ATTRIBUTION, set(), self._only_line_4 )

        assert buckets[ "call_time"    ][ "worker" ] == { "/src/a.py": [ 4 ] }
        assert buckets[ "module_scope" ][ "worker" ] == { "/src/a.py": [ 9 ] }
        assert buckets[ "allowed" ] == {}, "nothing was allow-listed in this call"

    def test_an_allow_listed_thread_lands_whole_in_allowed_and_is_never_classified( self ):
        """
        An exemption must be VISIBLE. Dropping the thread entirely - the old behaviour -
        makes an allow-listed scope read identically to a clean one.
        """
        buckets = bucket_findings( self.ATTRIBUTION, { "deliberate" }, self._only_line_4 )

        assert buckets[ "allowed" ] == { "deliberate": { "/src/a.py": [ 7 ] } }
        assert "deliberate" not in buckets[ "call_time"    ]
        assert "deliberate" not in buckets[ "module_scope" ]

    def test_the_test_thread_is_in_no_bucket( self ):
        buckets = bucket_findings( self.ATTRIBUTION, set(), self._only_line_4 )

        for name in ( "call_time", "module_scope", "allowed" ):
            assert TEST_THREAD not in buckets[ name ]

    def test_a_file_with_only_declarations_leaves_call_time_empty( self ):
        attribution = {
            TEST_THREAD : { "/src/a.py": [ 1 ] },
            "worker"    : { "/src/a.py": [ 8, 9 ] },
        }

        buckets = bucket_findings( attribution, set(), lambda fn, line: False )

        assert buckets[ "call_time"    ] == {}
        assert buckets[ "module_scope" ] == { "worker": { "/src/a.py": [ 8, 9 ] } }

    def test_all_three_bucket_keys_always_exist( self ):
        buckets = bucket_findings( {}, set(), self._only_line_4 )

        assert buckets == { "call_time": {}, "module_scope": {}, "allowed": {} }


class TestVerdictExitCode:
    """
    Requirement 3c. Keying the exit code on anything but `call_time` leaves the change
    cosmetic - the tool would still fail on 2,085 declarations.
    """

    def test_call_time_findings_fail_the_check( self ):
        buckets = { "call_time": { "worker": { "/src/a.py": [ 4 ] } },
                    "module_scope": {}, "allowed": {} }

        assert verdict_exit_code( buckets ) == 1

    def test_module_scope_declarations_alone_pass( self ):
        buckets = { "call_time": {},
                    "module_scope": { "worker": { "/src/a.py": [ 9 ] } }, "allowed": {} }

        assert verdict_exit_code( buckets ) == 0

    def test_an_allow_listed_thread_alone_passes( self ):
        buckets = { "call_time": {}, "module_scope": {},
                    "allowed": { "deliberate": { "/src/a.py": [ 7 ] } } }

        assert verdict_exit_code( buckets ) == 0

    def test_everything_empty_passes( self ):
        assert verdict_exit_code( { "call_time": {}, "module_scope": {}, "allowed": {} } ) == 0
