"""
Unit tests for cosa.repo.run_branch_analyzer (CLI entry point).

The BranchChangeAnalyzer subpackage is mocked (Cheech owns + already covers
branch_analyzer/*). Tests drive main() by patching sys.argv (main reads argv
directly) and assert exit codes + captured stdout/stderr.

PROD BUG RESOLVED (2026-05-31): run_branch_analyzer originally referenced
`Path( args.save_output )` at line ~209 without importing pathlib.Path, so
--save-output raised NameError → generic handler → exit 1. The campaign surfaced
this via an armed tripwire; `from pathlib import Path` now lands the fix and the
two save_output tests below assert the real contract (write + verbose confirm).
"""

import io
import sys
import unittest
from contextlib import redirect_stdout, redirect_stderr
from unittest.mock import patch, MagicMock

import cosa.repo.run_branch_analyzer as rba
from cosa.repo.branch_analyzer import BranchAnalyzerError


def _run_main( argv ):
    """Patch sys.argv to ['prog', *argv], run main(), capture (rc, out, err)."""
    out, err = io.StringIO(), io.StringIO()
    with patch.object( sys, "argv", [ "branch_analyzer" ] + argv ):
        with redirect_stdout( out ), redirect_stderr( err ):
            rc = rba.main()
    return rc, out.getvalue(), err.getvalue()


def _fake_analyzer():
    """A BranchChangeAnalyzer stand-in with the attributes main() touches."""
    an = MagicMock()
    an.base_branch = "main"
    an.head_branch = "wip-x"
    an.config = { "output": { "default_format": "console" } }
    an.analyze.return_value = { "stat": 1 }
    an.format_results.return_value = "FORMATTED OUTPUT"
    return an


class TestParser( unittest.TestCase ):
    """create_parser() — defaults + choice validation."""

    def test_defaults( self ):
        args = rba.create_parser().parse_args( [] )
        self.assertEqual( args.repo_path, "." )
        self.assertIsNone( args.base )
        self.assertIsNone( args.output )

    def test_invalid_output_choice_rejected( self ):
        with self.assertRaises( SystemExit ):
            rba.create_parser().parse_args( [ "--output", "xml" ] )


class TestMain( unittest.TestCase ):
    """main() — output paths, format resolution, verbose/debug, error mapping."""

    def setUp( self ):
        self.analyzer = _fake_analyzer()
        self._patcher = patch(
            "cosa.repo.run_branch_analyzer.BranchChangeAnalyzer", return_value=self.analyzer
        )
        self.mock_cls = self._patcher.start()
        self.addCleanup( self._patcher.stop )

    def test_console_output_to_stdout( self ):
        rc, out, err = _run_main( [] )
        self.assertEqual( rc, 0 )
        self.assertIn( "FORMATTED OUTPUT", out )

    def test_explicit_output_format_passed_through( self ):
        rc, out, err = _run_main( [ "--output", "json" ] )
        self.assertEqual( rc, 0 )
        self.assertEqual( self.analyzer.format_results.call_args.kwargs[ "format" ], "json" )

    def test_default_format_resolved_from_config( self ):
        self.analyzer.config = { "output": { "default_format": "markdown" } }
        rc, out, err = _run_main( [] )
        self.assertEqual( rc, 0 )
        self.assertEqual( self.analyzer.format_results.call_args.kwargs[ "format" ], "markdown" )

    def test_cross_repo_path_flows_to_analyzer( self ):
        # CROSS-REPO: an OUTSIDE-tree --repo-path is handed verbatim to the analyzer.
        rc, out, err = _run_main( [ "--repo-path", "/tmp/__external_repo__" ] )
        self.assertEqual( rc, 0 )
        self.assertEqual( self.mock_cls.call_args.kwargs[ "repo_path" ], "/tmp/__external_repo__" )

    def test_verbose_emits_progress_to_stderr( self ):
        rc, out, err = _run_main( [ "--verbose" ] )
        self.assertEqual( rc, 0 )
        self.assertIn( "Initializing", err )
        self.assertIn( "Analyzing", err )

    def test_debug_emits_progress_to_stderr( self ):
        rc, out, err = _run_main( [ "--debug" ] )
        self.assertEqual( rc, 0 )
        self.assertIn( "Formatting as", err )

    def test_known_error_returns_one( self ):
        self.analyzer.analyze.side_effect = BranchAnalyzerError( "bad branch" )
        rc, out, err = _run_main( [] )
        self.assertEqual( rc, 1 )
        self.assertIn( "Error:", err )

    def test_known_error_with_debug_prints_context( self ):
        e = BranchAnalyzerError( "bad branch" )
        e.context = { "detail": "x" }
        self.analyzer.analyze.side_effect = e
        rc, out, err = _run_main( [ "--debug" ] )
        self.assertEqual( rc, 1 )
        self.assertIn( "Context:", err )

    def test_keyboard_interrupt_returns_130( self ):
        self.analyzer.analyze.side_effect = KeyboardInterrupt()
        rc, out, err = _run_main( [] )
        self.assertEqual( rc, 130 )
        self.assertIn( "Interrupted by user", err )

    def test_unexpected_error_returns_one( self ):
        self.analyzer.analyze.side_effect = RuntimeError( "boom" )
        rc, out, err = _run_main( [] )
        self.assertEqual( rc, 1 )
        self.assertIn( "Unexpected error:", err )

    def test_unexpected_error_with_debug_prints_traceback( self ):
        self.analyzer.analyze.side_effect = RuntimeError( "boom" )
        rc, out, err = _run_main( [ "--debug" ] )
        self.assertEqual( rc, 1 )
        self.assertIn( "Traceback", err )

    def test_save_output_writes_file_and_returns_zero( self ):
        # --save-output writes the formatted output to disk and returns 0.
        # Covers the save_output branch entry (line 207 True → 209-210) and the
        # verbose-OFF path of the confirm guard (line 212 False).
        import os, tempfile
        dest = os.path.join( tempfile.mkdtemp(), "report.txt" )
        rc, out, err = _run_main( [ "--save-output", dest ] )
        self.assertEqual( rc, 0 )
        with open( dest ) as f:
            self.assertEqual( f.read(), "FORMATTED OUTPUT" )

    def test_save_output_verbose_confirms_to_stderr( self ):
        # With --verbose, the save path emits a "saved" confirmation to stderr.
        # Covers the verbose-ON path of the confirm guard (line 212 True → 213).
        import os, tempfile
        dest = os.path.join( tempfile.mkdtemp(), "report.txt" )
        rc, out, err = _run_main( [ "--save-output", dest, "--verbose" ] )
        self.assertEqual( rc, 0 )
        self.assertIn( "Output saved to", err )


if __name__ == "__main__":
    unittest.main()
