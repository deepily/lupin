"""
Unit tests for cosa.repo.run_directory_analyzer (CLI entry point).

The DirectoryAnalyzer subpackage is mocked (Cheech owns directory_analyzer/).
main() reads sys.argv directly, so tests patch it. Unlike its sister
run_branch_analyzer, this module correctly imports pathlib.Path, so the
--save-output success path IS reachable and asserted here.

CROSS-REPO COVERAGE: --path pointing OUTSIDE the project tree is handed
verbatim to the analyzer.
"""

import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from unittest.mock import patch, MagicMock

import cosa.repo.run_directory_analyzer as rda
from cosa.repo.directory_analyzer import DirectoryAnalyzerError


def _run_main( argv ):
    out, err = io.StringIO(), io.StringIO()
    with patch.object( sys, "argv", [ "directory_analyzer" ] + argv ):
        with redirect_stdout( out ), redirect_stderr( err ):
            rc = rda.main()
    return rc, out.getvalue(), err.getvalue()


def _fake_analyzer():
    an = MagicMock()
    an.analyze.return_value = { "stat": 1 }
    an.format_results.return_value = "FORMATTED OUTPUT"
    return an


class TestParser( unittest.TestCase ):
    """create_parser() — defaults + choice validation."""

    def test_defaults( self ):
        args = rda.create_parser().parse_args( [] )
        self.assertEqual( args.path, "." )
        self.assertEqual( args.output, "console" )

    def test_invalid_output_choice_rejected( self ):
        with self.assertRaises( SystemExit ):
            rda.create_parser().parse_args( [ "--output", "xml" ] )


class TestMain( unittest.TestCase ):
    """main() — output paths, save-output, verbose/debug, error mapping."""

    def setUp( self ):
        self.analyzer = _fake_analyzer()
        self._patcher = patch(
            "cosa.repo.run_directory_analyzer.DirectoryAnalyzer", return_value=self.analyzer
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

    def test_cross_repo_path_flows_to_analyzer( self ):
        # CROSS-REPO: an OUTSIDE-tree --path is handed verbatim to analyze().
        rc, out, err = _run_main( [ "--path", "/tmp/__external_dir__" ] )
        self.assertEqual( rc, 0 )
        self.assertEqual( self.analyzer.analyze.call_args.args[ 0 ], "/tmp/__external_dir__" )

    def test_save_output_writes_file( self ):
        dest = os.path.join( tempfile.mkdtemp(), "report.txt" )
        self.addCleanup( lambda: os.path.exists( dest ) and os.unlink( dest ) )
        rc, out, err = _run_main( [ "--save-output", dest ] )
        self.assertEqual( rc, 0 )
        with open( dest ) as f:
            self.assertEqual( f.read(), "FORMATTED OUTPUT" )

    def test_save_output_verbose_confirms_on_stderr( self ):
        dest = os.path.join( tempfile.mkdtemp(), "report.txt" )
        self.addCleanup( lambda: os.path.exists( dest ) and os.unlink( dest ) )
        rc, out, err = _run_main( [ "--save-output", dest, "--verbose" ] )
        self.assertEqual( rc, 0 )
        self.assertIn( "Output saved to", err )

    def test_verbose_emits_progress( self ):
        rc, out, err = _run_main( [ "--verbose" ] )
        self.assertEqual( rc, 0 )
        self.assertIn( "Initializing", err )
        self.assertIn( "Analyzing", err )

    def test_debug_emits_formatting_progress( self ):
        rc, out, err = _run_main( [ "--debug" ] )
        self.assertEqual( rc, 0 )
        self.assertIn( "Formatting as", err )

    def test_known_error_returns_one( self ):
        self.analyzer.analyze.side_effect = DirectoryAnalyzerError( "bad dir" )
        rc, out, err = _run_main( [] )
        self.assertEqual( rc, 1 )
        self.assertIn( "Error:", err )

    def test_known_error_with_debug_prints_context( self ):
        e = DirectoryAnalyzerError( "bad dir" )
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


if __name__ == "__main__":
    unittest.main()
