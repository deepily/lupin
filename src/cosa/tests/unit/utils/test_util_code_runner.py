"""
Unit tests for cosa.utils.util_code_runner.

Two surfaces:
  1. Pure list-transform helpers (import assembly, appendage de-duplication,
     repeated-line pruning, consecutive-blank collapsing) — tested directly.
  2. assemble_and_run_solution() — the subprocess-executing orchestrator.
     The EXECUTION BOUNDARY (subprocess.run), the filesystem (os.makedirs /
     chdir / getcwd / write), the ConfigurationManager, and the optional
     BugInjector are ALL mocked so no arbitrary or networked code ever runs.

Assertions harvested and strengthened from the module's quick_smoke_test()
(now superseded — that block validated only presence/shape; these validate
behaviour, branches, and error handling).
"""

import os
import subprocess
import unittest
from unittest.mock import patch, MagicMock

import cosa.utils.util_code_runner as ucr
from cosa.utils.util_code_runner import (
    initialize_code_response_dict,
    _ensure_proper_appendages,
    _append_post_function_code,
    _remove_all_but_the_1st_of_repeated_lines,
    _get_imports,
    _remove_consecutive_empty_strings,
    assemble_and_run_solution,
)


class _FakeResult:
    """Stand-in for subprocess.CompletedProcess returned by the mocked run()."""

    def __init__( self, returncode=0, stdout="", stderr="" ):
        self.returncode = returncode
        self.stdout     = stdout
        self.stderr     = stderr


class TestPureHelpers( unittest.TestCase ):
    """
    Pure, side-effect-free list transforms.

    Ensures:
        - default response dict carries the unsuccessful sentinel
        - import preamble branches on path_to_df
        - appendage / pruning / blank-collapsing logic is order-preserving
    """

    def test_initialize_code_response_dict_defaults( self ):
        """Default dict signals an un-run state: return_code -1, placeholder output."""
        result = initialize_code_response_dict()
        self.assertEqual( result[ "return_code" ], -1 )
        self.assertEqual( result[ "output" ], "No code run yet" )

    def test_get_imports_without_dataframe( self ):
        """No dataframe path => minimal datetime/pytz preamble only."""
        imports = _get_imports( None )
        self.assertEqual( imports, [ "import datetime", "import pytz" ] )

    def test_get_imports_with_dataframe_adds_pandas( self ):
        """A dataframe path => pandas + util imports, strictly longer than the basic set."""
        basic = _get_imports( None )
        df    = _get_imports( "/some/path.csv" )
        self.assertGreater( len( df ), len( basic ) )
        self.assertIn( "import pandas as pd", df )
        self.assertIn( "import lib.utils.util_pandas as dup", df )

    def test_ensure_proper_appendages_dedups_and_appends_last( self ):
        """Appended lines matching existing (space/case-normalized) lines move to the end, once."""
        code            = [ "x = 1", "Result = test()" ]
        always_appended = [ "result = test()", "print( result )" ]
        out = _ensure_proper_appendages( code, always_appended )
        # The pre-existing 'Result = test()' is dropped from its slot and the
        # appended canonical pair lands at the tail.
        self.assertEqual( out, [ "x = 1", "result = test()", "print( result )" ] )

    def test_ensure_proper_appendages_no_overlap_preserves_all( self ):
        """With no normalized collisions, every original line is kept then appendages added."""
        code            = [ "a = 1", "b = 2" ]
        always_appended = [ "print( a )" ]
        out = _ensure_proper_appendages( code, always_appended )
        self.assertEqual( out, [ "a = 1", "b = 2", "print( a )" ] )

    def test_remove_all_but_first_repeated_line( self ):
        """Only the first line starting with the search string survives; order preserved."""
        lines = [ "import os", "x = 1", "import os", "y = 2", "import os" ]
        out = _remove_all_but_the_1st_of_repeated_lines( lines, "import os" )
        self.assertEqual( out, [ "import os", "x = 1", "y = 2" ] )

    def test_remove_all_but_first_no_match_is_unchanged( self ):
        """No matching prefix => list returned unchanged (empty match_indices branch)."""
        lines = [ "a", "b", "c" ]
        out = _remove_all_but_the_1st_of_repeated_lines( list( lines ), "zzz" )
        self.assertEqual( out, lines )

    def test_remove_consecutive_empty_strings_collapses_runs( self ):
        """Runs of blanks collapse to a single blank; non-blanks and singletons preserved."""
        strings = [ "", "", "a", "", "b", "", "" ]
        out = _remove_consecutive_empty_strings( strings )
        self.assertEqual( out, [ "", "a", "", "b", "" ] )

    def test_remove_consecutive_empty_strings_leading_blank_kept( self ):
        """A single leading blank (i == 0 branch) is retained."""
        out = _remove_consecutive_empty_strings( [ "", "a" ] )
        self.assertEqual( out, [ "", "a" ] )


class TestAppendPostFunctionCode( unittest.TestCase ):
    """
    _append_post_function_code() return-type and dataframe branches.

    Ensures:
        - dataframe return type emits the XML print line
        - non-dataframe return type emits the plain print line
        - a dataframe path prepends the read_csv + cast lines
        - dotted return types are reduced to their final segment
    """

    def test_string_return_type_appends_plain_print( self ):
        out = _append_post_function_code( [ "def f(): return 1" ], "string", "solution = f()" )
        self.assertIn( "solution = f()", out )
        self.assertIn( "print( solution )", out )
        self.assertNotIn( "print( solution.to_xml( index=False ) )", out )

    def test_dataframe_return_type_appends_xml_print( self ):
        out = _append_post_function_code( [ "def f(): return df" ], "dataframe", "solution = f()" )
        self.assertIn( "print( solution.to_xml( index=False ) )", out )

    def test_dotted_return_type_reduced_to_last_segment( self ):
        """'pandas.core.frame.DataFrame' must be treated as 'dataframe'."""
        out = _append_post_function_code( [ "x = 1" ], "pandas.core.frame.DataFrame", "solution = f()" )
        self.assertIn( "print( solution.to_xml( index=False ) )", out )

    def test_path_to_df_prepends_read_and_cast( self ):
        out = _append_post_function_code(
            [ "x = 1" ], "string", "solution = f()", path_to_df="/data/events.csv"
        )
        joined = "\n".join( out )
        self.assertIn( "pd.read_csv( du.get_project_root() + '/data/events.csv' )", joined )
        self.assertIn( "dup.cast_to_datetime( df, debug=debug )", joined )


class TestAssembleAndRunSolution( unittest.TestCase ):
    """
    Orchestrator behaviour with the execution boundary + filesystem mocked.

    Ensures:
        - successful (rc 0) runs surface stripped stdout
        - empty stdout maps to the 'No results returned' sentinel
        - non-zero return codes surface an ERROR-prefixed stderr
        - a missing config var falls back to the hardcoded execution path
        - timeouts honour return_none_on_timeout (return None vs. re-raise)
        - inject_bugs routes through the BugInjector
        - no real subprocess, directory creation, or chdir occurs
    """

    def setUp( self ):
        # Patch the entire side-effecting surface for every test in this class.
        self._patchers = []

        def _start( target, **kw ):
            p = patch( target, **kw )
            self._patchers.append( p )
            return p.start()

        # Execution boundary + filesystem — fully neutralised.
        self.mock_run     = _start( "cosa.utils.util_code_runner.run" )
        _start( "cosa.utils.util_code_runner.os.makedirs" )
        _start( "cosa.utils.util_code_runner.os.chdir" )
        _start( "cosa.utils.util_code_runner.os.getcwd", return_value="/orig/wd" )

        # du helpers used by the orchestrator (banners/list/stack-trace silenced;
        # project root + file write neutralised).
        _start( "cosa.utils.util_code_runner.du.get_project_root", return_value="/fake/root" )
        _start( "cosa.utils.util_code_runner.du.write_lines_to_file" )
        _start( "cosa.utils.util_code_runner.du.print_banner" )
        _start( "cosa.utils.util_code_runner.du.print_list" )
        _start( "cosa.utils.util_code_runner.du.print_stack_trace" )

        # ConfigurationManager resolves the code-execution path by default.
        cfg_instance = MagicMock()
        cfg_instance.get.return_value = "/io/code_execution.py"
        self.mock_cfg = _start(
            "cosa.config.configuration_manager.ConfigurationManager",
            return_value=cfg_instance,
        )

    def tearDown( self ):
        for p in self._patchers:
            p.stop()

    def test_successful_run_returns_stripped_stdout( self ):
        self.mock_run.return_value = _FakeResult( returncode=0, stdout="  hello world  \n" )
        out = assemble_and_run_solution( [ "x = 1" ], "solution = 1" )
        self.assertEqual( out[ "return_code" ], 0 )
        self.assertEqual( out[ "output" ], "hello world" )
        self.assertTrue( self.mock_run.called )

    def test_empty_stdout_maps_to_sentinel( self ):
        self.mock_run.return_value = _FakeResult( returncode=0, stdout="   \n" )
        out = assemble_and_run_solution( [ "x = 1" ], "solution = 1" )
        self.assertEqual( out[ "output" ], "No results returned" )

    def test_nonzero_return_code_surfaces_stderr( self ):
        self.mock_run.return_value = _FakeResult( returncode=1, stderr="boom traceback" )
        out = assemble_and_run_solution( [ "x = 1" ], "solution = 1" )
        self.assertEqual( out[ "return_code" ], 1 )
        self.assertIn( "ERROR executing code:", out[ "output" ] )
        self.assertIn( "boom traceback", out[ "output" ] )

    def test_config_value_error_uses_fallback_path( self ):
        """A ValueError from ConfigurationManager falls back to the hardcoded path, still runs."""
        self.mock_cfg.side_effect = ValueError( "no env var" )
        self.mock_run.return_value = _FakeResult( returncode=0, stdout="ok" )
        out = assemble_and_run_solution( [ "x = 1" ], "solution = 1" )
        self.assertEqual( out[ "output" ], "ok" )
        self.assertTrue( self.mock_run.called )

    def test_timeout_returns_none_when_flag_set( self ):
        self.mock_run.side_effect = subprocess.TimeoutExpired( cmd="python3", timeout=60 )
        out = assemble_and_run_solution(
            [ "x = 1" ], "solution = 1", return_none_on_timeout=True
        )
        self.assertIsNone( out[ "output" ] )
        self.assertEqual( out[ "return_code" ], -1 )

    def test_timeout_reraises_when_flag_clear( self ):
        self.mock_run.side_effect = subprocess.TimeoutExpired( cmd="python3", timeout=60 )
        with self.assertRaises( subprocess.TimeoutExpired ):
            assemble_and_run_solution(
                [ "x = 1" ], "solution = 1", return_none_on_timeout=False
            )

    def test_inject_bugs_routes_through_bug_injector( self ):
        """inject_bugs=True replaces solution_code via the BugInjector before execution."""
        injector_instance = MagicMock()
        injector_instance.run_prompt.return_value = { "code": [ "buggy = 1" ] }
        self.mock_run.return_value = _FakeResult( returncode=0, stdout="done" )
        with patch(
            "cosa.agents.bug_injector.BugInjector", return_value=injector_instance
        ) as mock_injector:
            out = assemble_and_run_solution(
                [ "x = 1" ], "solution = 1", inject_bugs=True
            )
        mock_injector.assert_called_once()
        injector_instance.run_prompt.assert_called_once()
        self.assertEqual( out[ "output" ], "done" )

    def test_debug_verbose_path_executes_cleanly( self ):
        """debug+verbose exercises the banner/list branches without altering the result."""
        self.mock_run.return_value = _FakeResult( returncode=0, stdout="v" )
        out = assemble_and_run_solution(
            [ "x = 1" ], "solution = 1", debug=True, verbose=True
        )
        self.assertEqual( out[ "output" ], "v" )

    def test_legacy_in_module_harness_runs_with_dataframe_path( self ):
        """
        The in-module test_assemble_and_run_solution() harness (a harvest target)
        drives the orchestrator with a dataframe path — exercising the
        path_to_df != None branch (pandas preamble + read_csv/cast appendages)
        that the other cases, defaulting path_to_df=None, do not reach.

        The csv is never actually read: the real read happens inside the
        subprocess, which is mocked, so this stays hermetic.
        """
        self.mock_run.return_value = _FakeResult( returncode=0, stdout="rows" )
        ucr.test_assemble_and_run_solution( debug=False, verbose=False )
        self.assertTrue( self.mock_run.called )
        # The assembled script handed to write_lines_to_file must carry the
        # pandas preamble that the dataframe path injects.
        write_mock = ucr.du.write_lines_to_file
        self.assertTrue( write_mock.called )
        assembled = write_mock.call_args[ 0 ][ 1 ]
        self.assertIn( "import pandas as pd", assembled )


if __name__ == "__main__":
    unittest.main()


class TestPerInvocationCodeFile( unittest.TestCase ):
    """
    Row 7b9094d8 — the shared-path race, and the process-global chdir beside it.

    The defect was NOT a crash. Every agent that generated code wrote ONE configured path
    (/io/code.py) and then executed it, while `cj flow max concurrent agentic jobs` is 3 in
    both Development and Production. The interleaving that matters is write(A) -> write(B) ->
    exec(A): job A executes job B's code and returns it as its own answer, with no job id, no
    checksum and no lock to notice. A confident wrong answer attributed to the wrong question.

    Ensures:
        - each invocation writes and executes a DISTINCT path
        - the parent process's working directory is never mutated
        - the child still runs with /io as its cwd
        - the per-invocation file is removed on success, on a swallowed timeout, and on a
          re-raised one
    """

    def setUp( self ):
        self._patchers = []

        def _start( target, **kw ):
            p = patch( target, **kw )
            self._patchers.append( p )
            return p.start()

        self.mock_run     = _start( "cosa.utils.util_code_runner.run" )
        self.mock_chdir   = _start( "cosa.utils.util_code_runner.os.chdir" )
        self.mock_remove  = _start( "cosa.utils.util_code_runner.os.remove" )
        _start( "cosa.utils.util_code_runner.os.makedirs" )
        _start( "cosa.utils.util_code_runner.os.getcwd", return_value="/orig/wd" )

        _start( "cosa.utils.util_code_runner.du.get_project_root", return_value="/fake/root" )
        self.mock_write   = _start( "cosa.utils.util_code_runner.du.write_lines_to_file" )
        _start( "cosa.utils.util_code_runner.du.print_banner" )
        _start( "cosa.utils.util_code_runner.du.print_list" )
        _start( "cosa.utils.util_code_runner.du.print_stack_trace" )

        cfg_instance = MagicMock()
        cfg_instance.get.return_value = "/io/code.py"
        _start( "cosa.config.configuration_manager.ConfigurationManager", return_value=cfg_instance )

    def tearDown( self ):
        for p in self._patchers:
            p.stop()

    def _written_path( self ):
        """The path handed to write_lines_to_file on the most recent call."""
        return self.mock_write.call_args[ 0 ][ 0 ]

    def _executed_path( self ):
        """The script path in the argv handed to run() on the most recent call."""
        return self.mock_run.call_args[ 0 ][ 0 ][ 1 ]

    def test_two_invocations_write_two_different_paths( self ):
        """THE RACE. Two runs must not share a filename."""
        self.mock_run.return_value = _FakeResult( returncode=0, stdout="a" )
        assemble_and_run_solution( [ "x = 1" ], "solution = 1" )
        first = self._written_path()

        assemble_and_run_solution( [ "x = 2" ], "solution = 2" )
        second = self._written_path()

        self.assertNotEqual( first, second, "two invocations shared one code file — the race is back" )

    def test_the_file_written_is_the_file_executed( self ):
        """Uniqueness is worthless if the run still executes the old shared name."""
        self.mock_run.return_value = _FakeResult( returncode=0, stdout="a" )
        assemble_and_run_solution( [ "x = 1" ], "solution = 1" )
        self.assertEqual( self._written_path(), self._executed_path() )

    def test_the_unique_path_keeps_the_configured_directory_and_stem( self ):
        """The config key must keep meaning something — dir and stem survive."""
        self.mock_run.return_value = _FakeResult( returncode=0, stdout="a" )
        assemble_and_run_solution( [ "x = 1" ], "solution = 1" )
        written = self._written_path()
        self.assertTrue( written.startswith( "/fake/root/io/code-" ), written )
        self.assertTrue( written.endswith( ".py" ), written )

    def test_the_parent_working_directory_is_never_changed( self ):
        """os.chdir from a worker thread moves every OTHER thread's relative paths."""
        self.mock_run.return_value = _FakeResult( returncode=0, stdout="a" )
        assemble_and_run_solution( [ "x = 1" ], "solution = 1" )
        self.mock_chdir.assert_not_called()

    def test_the_child_still_runs_in_io( self ):
        """Generated code kept its working directory — it moved to the child, not away."""
        self.mock_run.return_value = _FakeResult( returncode=0, stdout="a" )
        assemble_and_run_solution( [ "x = 1" ], "solution = 1" )
        self.assertEqual( self.mock_run.call_args[ 1 ][ "cwd" ], "/fake/root/io" )

    def test_the_file_is_removed_after_a_successful_run( self ):
        """Unique names without cleanup turn /io into an unbounded pile."""
        self.mock_run.return_value = _FakeResult( returncode=0, stdout="a" )
        assemble_and_run_solution( [ "x = 1" ], "solution = 1" )
        self.mock_remove.assert_called_once_with( self._written_path() )

    def test_a_swallowed_timeout_still_removes_the_file( self ):
        self.mock_run.side_effect = subprocess.TimeoutExpired( cmd="python3", timeout=60 )
        out = assemble_and_run_solution( [ "x = 1" ], "solution = 1", return_none_on_timeout=True )
        self.assertIsNone( out[ "output" ] )
        self.mock_remove.assert_called_once_with( self._written_path() )

    def test_a_reraised_timeout_removes_the_file_and_leaves_the_cwd_alone( self ):
        """The old code's `raise` branch never restored the cwd — the server stayed in /io."""
        self.mock_run.side_effect = subprocess.TimeoutExpired( cmd="python3", timeout=60 )
        with self.assertRaises( subprocess.TimeoutExpired ):
            assemble_and_run_solution( [ "x = 1" ], "solution = 1", return_none_on_timeout=False )
        self.mock_remove.assert_called_once_with( self._written_path() )
        self.mock_chdir.assert_not_called()

    def test_cleanup_failure_never_masks_the_answer( self ):
        """A failed unlink must not replace the result the user is waiting for."""
        self.mock_run.return_value = _FakeResult( returncode=0, stdout="hello" )
        self.mock_remove.side_effect = OSError( "permission denied" )
        out = assemble_and_run_solution( [ "x = 1" ], "solution = 1" )
        self.assertEqual( out[ "output" ], "hello" )



class TestConcurrentInvocationsDoNotCrossAnswers( unittest.TestCase ):
    """
    Row 7b9094d8 — the race REPRODUCED, then shown closed.

    Everything above this class mocks the execution boundary and calls the runner twice in a
    row. That proves two calls pick two names; it does NOT reproduce the defect, because the
    defect needs two calls to be INSIDE the function at the same time. The row was filed on a
    reading of the code plus the INI ( `cj flow max concurrent agentic jobs` is 3 in both
    Development and Production ), and a reading is not a measurement.

    So this class runs two invocations CONCURRENTLY, with REAL python3 subprocesses, and asks
    the only question that matters to a user: did each caller get its own answer back?

    The interleave is FORCED rather than hoped for. Both threads block on a barrier immediately
    after writing their program and before either executes, which pins the ordering to exactly
    write(A) -> write(B) -> exec(A) -> exec(B) — the one interleaving that makes the shared-path
    bug produce a wrong answer instead of a crash. Without the barrier the race is real but
    rare, and a test that fails one run in fifty is a test nobody believes.

    Against the shared-path implementation this is a genuine RED: thread A executes thread B's
    program and returns "JOB-B" as its own answer, with return_code 0 and nothing anywhere
    saying the answer belongs to another question.

    Ensures:
        - two concurrent invocations each receive the output of their OWN program
        - the two invocations wrote two distinct files
        - neither leaves its per-invocation file behind

    Venue: :7999-eligible. Spawns two short-lived python3 subprocesses whose whole program is
    a print; all filesystem writes land in a TemporaryDirectory that is removed afterward.
    """

    def _run_two_jobs_concurrently( self ):
        """
        Run two invocations at once and return ( answers, written_paths, leftover_files ).

        Requires:
            - python3 is on PATH and can import datetime and pytz ( the runner's preamble )

        Ensures:
            - both threads are inside assemble_and_run_solution simultaneously, with both
              writes completed before either execution starts
            - returns each thread's answer keyed by job name, every path handed to the
              writer, and whatever is left in the fake io directory afterwards
            - the process working directory is restored before the temp tree is removed

        That last clause is not tidiness. The pre-fix implementation chdir'd the WHOLE process
        into its io directory and did not restore it on every path, so a run under it left the
        interpreter parked inside a directory this helper is about to delete — and the NEXT
        test in the file then died in os.getcwd() with a message about a missing directory
        instead of about a crossed answer. A control whose failure names the wrong defect is a
        control a reader will misdiagnose, so the restore happens here where it cannot mask
        anything: the chdir behaviour itself is asserted separately, on the return value.
        """
        import tempfile
        import threading

        answers       = {}
        written_paths = []
        paths_lock    = threading.Lock()
        both_written  = threading.Barrier( 2, timeout=30 )
        cwd_before    = os.getcwd()

        with tempfile.TemporaryDirectory() as fake_root:
            io_dir = os.path.join( fake_root, "io" )
            os.makedirs( io_dir, exist_ok=True )

            real_write = ucr.du.write_lines_to_file

            def write_then_wait_for_the_other_thread( path, lines, *args, **kwargs ):
                """Write for real, then hold until BOTH threads have written."""
                result = real_write( path, lines, *args, **kwargs )
                with paths_lock:
                    written_paths.append( path )
                both_written.wait()
                return result

            cfg_instance = MagicMock()
            cfg_instance.get.return_value = "/io/code.py"

            def one_job( name ):
                """Record the answer, or the failure — never leave the key simply absent."""
                try:
                    answers[ name ] = assemble_and_run_solution(
                        [ "def answer():", f"    return '{name}'" ],
                        "solution = answer()",
                    )[ "output" ]
                except BaseException as e:                              # noqa: BLE001 — a thread that
                    answers[ name ] = f"RAISED {type( e ).__name__}: {e}"  # dies must say so in the
                                                                        # assertion, not as a KeyError

            with patch( "cosa.utils.util_code_runner.du.get_project_root", return_value=fake_root ), \
                 patch( "cosa.utils.util_code_runner.du.write_lines_to_file", side_effect=write_then_wait_for_the_other_thread ), \
                 patch( "cosa.config.configuration_manager.ConfigurationManager", return_value=cfg_instance ):

                threads = [ threading.Thread( target=one_job, args=( name, ) ) for name in ( "JOB-A", "JOB-B" ) ]
                for t in threads: t.start()
                for t in threads: t.join( timeout=60 )
                for t in threads:
                    self.assertFalse( t.is_alive(), "a job never finished — the barrier or a subprocess hung" )

            leftovers = os.listdir( io_dir )
            os.chdir( cwd_before )

        return answers, written_paths, leftovers

    def test_each_concurrent_job_gets_its_own_answer( self ):
        """
        Ensures:
            - neither job receives the other job's output

        THE ROW'S ACTUAL HARM. The shared-path version returns "JOB-B" to the caller who asked
        for "JOB-A" — a confident wrong answer attributed to the wrong question, with a zero
        return code and no error anywhere.
        """
        answers, _, _ = self._run_two_jobs_concurrently()

        self.assertEqual(
            answers[ "JOB-A" ], "JOB-A",
            f"JOB-A was handed [{answers[ 'JOB-A' ]}] — another job's answer to another job's question"
        )
        self.assertEqual(
            answers[ "JOB-B" ], "JOB-B",
            f"JOB-B was handed [{answers[ 'JOB-B' ]}] — another job's answer to another job's question"
        )

    def test_concurrent_jobs_write_two_distinct_files( self ):
        """
        Ensures:
            - the two simultaneous invocations did not share one filename

        The mechanism behind the assertion above, stated separately so a failure says WHICH of
        the two broke: the naming, or the answer routing.
        """
        _, written_paths, _ = self._run_two_jobs_concurrently()

        self.assertEqual( len( written_paths ), 2, written_paths )
        self.assertNotEqual(
            written_paths[ 0 ], written_paths[ 1 ],
            f"both concurrent jobs wrote [{written_paths[ 0 ]}] — the race is back"
        )

    def test_concurrent_jobs_leave_no_files_behind( self ):
        """
        Ensures:
            - per-invocation naming does not turn the io directory into an unbounded pile

        Uniqueness without cleanup trades a correctness bug for a disk-fill one, so the cleanup
        is asserted under the same concurrency as the naming rather than only in isolation.
        """
        _, _, leftovers = self._run_two_jobs_concurrently()

        self.assertEqual( leftovers, [], f"per-invocation files were left behind: {leftovers}" )
