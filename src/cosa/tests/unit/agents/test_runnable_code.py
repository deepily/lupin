"""
Unit tests for cosa.agents.runnable_code.RunnableCode.

Exercises the code-execution base class against its CURRENT production contract:

- __init__                — default attribute wiring (flags + empty response slots)
- print_code              — banner + numbered listing, with and without a custom end
- is_code_runnable        — True when code present; False (+message) when empty or unset
- run_code                — delegates to util_code_runner, splits success vs failure into
                            answer/error, and emits the debug+verbose output trace
- code_ran_to_completion  — True only when return_code == 0 (unset / non-zero → False)
- get_code_and_metadata   — returns the stored execution dict

Zero external dependencies — util_code_runner.assemble_and_run_solution is mocked at
the boundary; the du print helpers run for real (stdout is captured + asserted, the
agents standard). No code is actually executed.

Created 2026-05-31 (CoSA coverage campaign, agents lane — Tiffany 💍). New file.
"""

import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from cosa.agents.runnable_code import RunnableCode


class TestRunnableCode( unittest.TestCase ):
    """
    Comprehensive unit tests for RunnableCode.

    Ensures:
        - Construction yields the documented empty/None default state
        - print_code / is_code_runnable / run_code / completion / metadata accessors
          all behave per contract across their success and failure branches
    """

    def test_init_defaults( self ):
        """
        Test the constructor establishes the documented default state.

        Ensures:
            - debug/verbose stored
            - All response/answer/error slots start as None
        """
        rc = RunnableCode( debug=True, verbose=True )

        self.assertTrue( rc.debug )
        self.assertTrue( rc.verbose )
        self.assertIsNone( rc.prompt_response )
        self.assertIsNone( rc.prompt_response_dict )
        self.assertIsNone( rc.code_response_dict )
        self.assertIsNone( rc.answer )
        self.assertIsNone( rc.error )

    def test_print_code_without_end( self ):
        """
        Test print_code emits a banner + the numbered code listing (no custom end).

        Ensures:
            - The code lines appear in stdout
            - The no-end branch is taken
        """
        rc = RunnableCode()
        rc.prompt_response_dict = { "code": [ "def f():", "    return 1" ] }

        buf = io.StringIO()
        with redirect_stdout( buf ):
            rc.print_code( "My Code" )
        out = buf.getvalue()

        self.assertIn( "def f():", out )
        self.assertIn( "return 1", out )

    def test_print_code_with_custom_end( self ):
        """
        Test print_code honors a custom end string.

        Ensures:
            - The end-not-None branch is taken (no error; listing still emitted)
        """
        rc = RunnableCode()
        rc.prompt_response_dict = { "code": [ "x = 1" ] }

        buf = io.StringIO()
        with redirect_stdout( buf ):
            rc.print_code( end="\n\n" )
        out = buf.getvalue()

        self.assertIn( "x = 1", out )

    def test_is_code_runnable_true( self ):
        """
        Test is_code_runnable returns True when code is present.

        Ensures:
            - A non-empty code list yields True
        """
        rc = RunnableCode()
        rc.prompt_response_dict = { "code": [ "print( 1 )" ] }

        self.assertTrue( rc.is_code_runnable() )

    def test_is_code_runnable_false_empty_code( self ):
        """
        Test is_code_runnable returns False (with message) for an empty code list.

        Ensures:
            - Empty code → False and the "No code to run" notice is printed
        """
        rc = RunnableCode()
        rc.prompt_response_dict = { "code": [] }

        buf = io.StringIO()
        with redirect_stdout( buf ):
            result = rc.is_code_runnable()

        self.assertFalse( result )
        self.assertIn( "No code to run", buf.getvalue() )

    def test_is_code_runnable_false_when_unset( self ):
        """
        Test is_code_runnable returns False when the response dict is unset.

        Ensures:
            - prompt_response_dict is None short-circuits to False (no KeyError)
        """
        rc = RunnableCode()
        rc.prompt_response_dict = None

        buf = io.StringIO()
        with redirect_stdout( buf ):
            self.assertFalse( rc.is_code_runnable() )

    def test_run_code_success_sets_answer( self ):
        """
        Test run_code records the answer on a zero return code.

        Ensures:
            - util_code_runner is delegated to with code + example
            - return_code 0 → answer set, error cleared
            - The execution dict is returned
        """
        rc = RunnableCode()
        rc.prompt_response_dict = {
            "code"    : [ "solution = 42" ],
            "example" : "solution = 42",
            "returns" : "int",
        }

        fake_result = { "return_code": 0, "output": "42" }
        with patch( "cosa.agents.runnable_code.ucr.assemble_and_run_solution",
                    return_value=fake_result ) as mock_run:
            result = rc.run_code( path_to_df="/tmp/df.csv" )

        self.assertEqual( result, fake_result )
        self.assertEqual( rc.answer, "42" )
        self.assertIsNone( rc.error )
        mock_run.assert_called_once()

    def test_run_code_failure_sets_error( self ):
        """
        Test run_code records the error on a non-zero return code.

        Ensures:
            - return_code != 0 → error set, answer cleared
            - The 'returns' default ('string') is used when the key is absent
        """
        rc = RunnableCode()
        rc.prompt_response_dict = {
            "code"    : [ "boom()" ],
            "example" : "solution = boom()",
        }   # no 'returns' key → exercises the .get default

        fake_result = { "return_code": 1, "output": "Traceback: boom" }
        with patch( "cosa.agents.runnable_code.ucr.assemble_and_run_solution",
                    return_value=fake_result ):
            rc.run_code()

        self.assertEqual( rc.error, "Traceback: boom" )
        self.assertIsNone( rc.answer )

    def test_run_code_debug_verbose_traces_stdout( self ):
        """
        Test run_code emits the run banner + per-line output trace under debug+verbose.

        Ensures (capturing stdout — agents standard):
            - Each output line is echoed when debug and verbose are set
        """
        rc = RunnableCode( debug=True, verbose=True )
        rc.prompt_response_dict = {
            "code"    : [ "x = 1" ],
            "example" : "solution = x",
            "returns" : "int",
        }

        fake_result = { "return_code": 0, "output": "line-a\nline-b" }
        buf = io.StringIO()
        with patch( "cosa.agents.runnable_code.ucr.assemble_and_run_solution",
                    return_value=fake_result ):
            with redirect_stdout( buf ):
                rc.run_code()
        out = buf.getvalue()

        self.assertIn( "line-a", out )
        self.assertIn( "line-b", out )

    def test_code_ran_to_completion_true( self ):
        """
        Test code_ran_to_completion returns True for a zero return code.

        Ensures:
            - return_code 0 → True
        """
        rc = RunnableCode()
        rc.code_response_dict = { "return_code": 0, "output": "ok" }

        self.assertTrue( rc.code_ran_to_completion() )

    def test_code_ran_to_completion_false_nonzero( self ):
        """
        Test code_ran_to_completion returns False for a non-zero return code.

        Ensures:
            - return_code != 0 → False
        """
        rc = RunnableCode()
        rc.code_response_dict = { "return_code": 2, "output": "err" }

        self.assertFalse( rc.code_ran_to_completion() )

    def test_code_ran_to_completion_false_when_unset( self ):
        """
        Test code_ran_to_completion returns False before any run.

        Ensures:
            - An unset code_response_dict short-circuits to False
        """
        rc = RunnableCode()

        self.assertFalse( rc.code_ran_to_completion() )

    def test_get_code_and_metadata_returns_dict( self ):
        """
        Test get_code_and_metadata returns the stored execution dict.

        Ensures:
            - The exact code_response_dict reference is returned
        """
        rc = RunnableCode()
        payload = { "return_code": 0, "output": "ok", "code": [ "x=1" ] }
        rc.code_response_dict = payload

        self.assertIs( rc.get_code_and_metadata(), payload )


if __name__ == "__main__":
    unittest.main()
