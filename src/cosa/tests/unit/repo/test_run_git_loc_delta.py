"""
Unit tests for cosa.repo.run_git_loc_delta (CLI entry point).

The analyzer, CSV writer, formatters, and plotter are imported into the module
namespace and fully mocked, so tests touch no real git repo, filesystem
artifacts, or matplotlib. The git-subprocess seam (_resolve_target_root) is
mocked too.

CROSS-REPO COVERAGE (load-bearing): every path-resolving surface is exercised
with a --repo-path that points OUTSIDE the project tree — the resolution-bug
class that a same-tree-only suite would miss.

Pure helpers (parser, mode/name/path resolution) are tested directly; main()
is driven with argv lists and asserted on exit code + captured stdout/stderr.
"""

import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from unittest.mock import patch, MagicMock

import cosa.repo.run_git_loc_delta as rgld
from cosa.repo.git_loc_delta.exceptions import (
    DateRangeError, GitCommandError, GitLocDeltaError,
)


# A path that is unambiguously OUTSIDE the lupin project tree.
_EXTERNAL_REPO = "/tmp/__sam_external_repo__"

# Analyzer result contract consumed by main() / _emit_plot().
def _result( daily=None ):
    return {
        "daily":     daily if daily is not None else { "2026-05-01": {}, "2026-05-02": {} },
        "summary":   { "insertions": 10, "deletions": 4 },
        "since":     "2026-05-01",
        "until":     "2026-05-02",
        "branch":    "wip",
        "rev_range": "main..wip",
        "repo_path": _EXTERNAL_REPO,
        "by_type":   { ".py": { "insertions": 10, "deletions": 4 } },
    }


def _capture( fn, *args, **kwargs ):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout( out ), redirect_stderr( err ):
        rc = fn( *args, **kwargs )
    return rc, out.getvalue(), err.getvalue()


class TestParser( unittest.TestCase ):
    """create_parser() + _resolve_mode()."""

    def test_defaults( self ):
        args = rgld.create_parser().parse_args( [] )
        self.assertEqual( args.repo_path, "." )
        self.assertEqual( args.output, "console" )
        self.assertEqual( args.base, "main" )

    def test_mutually_exclusive_modes_rejected( self ):
        with self.assertRaises( SystemExit ):
            rgld.create_parser().parse_args( [ "--today", "--since", "2026-05-01" ] )

    def test_resolve_mode_branch( self ):
        args = rgld.create_parser().parse_args( [ "--branch", "feature" ] )
        self.assertEqual( rgld._resolve_mode( args ), "branch" )

    def test_resolve_mode_explicit( self ):
        args = rgld.create_parser().parse_args( [ "--since", "2026-05-01" ] )
        self.assertEqual( rgld._resolve_mode( args ), "explicit" )

    def test_resolve_mode_today_default( self ):
        args = rgld.create_parser().parse_args( [] )
        self.assertEqual( rgld._resolve_mode( args ), "today" )


class TestResolveTargetRoot( unittest.TestCase ):
    """_resolve_target_root() — git toplevel resolution + fallbacks, incl. cross-repo."""

    def test_external_repo_path_resolves_to_git_toplevel( self ):
        # CROSS-REPO: --repo-path points outside the tree; git reports its own toplevel.
        fake = MagicMock( returncode=0, stdout=_EXTERNAL_REPO + "\n" )
        with patch( "cosa.repo.run_git_loc_delta.subprocess.run", return_value=fake ) as run:
            resolved = rgld._resolve_target_root( _EXTERNAL_REPO )
        self.assertEqual( resolved, _EXTERNAL_REPO )
        # The git call must run with cwd set to the external abspath, not the project.
        self.assertEqual( run.call_args.kwargs[ "cwd" ], os.path.abspath( _EXTERNAL_REPO ) )

    def test_non_git_path_falls_back_to_abspath( self ):
        fake = MagicMock( returncode=128, stdout="" )
        with patch( "cosa.repo.run_git_loc_delta.subprocess.run", return_value=fake ):
            resolved = rgld._resolve_target_root( _EXTERNAL_REPO )
        self.assertEqual( resolved, os.path.abspath( _EXTERNAL_REPO ) )

    def test_subprocess_exception_falls_back_to_abspath( self ):
        with patch( "cosa.repo.run_git_loc_delta.subprocess.run", side_effect=OSError( "no git" ) ):
            resolved = rgld._resolve_target_root( "relative/sub" )
        self.assertEqual( resolved, os.path.abspath( "relative/sub" ) )

    def test_empty_toplevel_falls_back_to_abspath( self ):
        fake = MagicMock( returncode=0, stdout="   \n" )
        with patch( "cosa.repo.run_git_loc_delta.subprocess.run", return_value=fake ):
            resolved = rgld._resolve_target_root( _EXTERNAL_REPO )
        self.assertEqual( resolved, os.path.abspath( _EXTERNAL_REPO ) )


class TestResolveRepoNameAndPaths( unittest.TestCase ):
    """_resolve_repo_name / _default_csv_path / _default_plot_path — pure."""

    def test_repo_name_override_wins( self ):
        self.assertEqual( rgld._resolve_repo_name( "cosa", "/x/lupin" ), "cosa" )

    def test_repo_name_from_basename( self ):
        self.assertEqual( rgld._resolve_repo_name( None, "/x/lupin" ), "lupin" )

    def test_repo_name_defensive_default( self ):
        self.assertEqual( rgld._resolve_repo_name( None, "/" ), "repo" )

    def test_csv_path_branch_mode_slugifies( self ):
        p = rgld._default_csv_path( "branch", "/root", "cosa", "feature/x" )
        self.assertTrue( p.endswith( "io/git-loc-delta/cosa-feature-x-loc-delta.csv" ) )

    def test_csv_path_today_mode_datestamped( self ):
        p = rgld._default_csv_path( "today", "/root", "cosa", None )
        self.assertIn( "io/git-loc-delta/", p )
        self.assertTrue( p.endswith( "-loc-delta.csv" ) )

    def test_plot_path_branch_mode( self ):
        p = rgld._default_plot_path( "branch", "/root", "cosa", "feature/x", None, None )
        self.assertTrue( p.endswith( "io/git-delta-analysis/cosa-feature-x-plot.png" ) )

    def test_plot_path_explicit_mode( self ):
        p = rgld._default_plot_path( "explicit", "/root", "cosa", None, "2026-05-01", "2026-05-10" )
        self.assertTrue( p.endswith( "io/git-delta-analysis/2026-05-01_to_2026-05-10-plot.png" ) )

    def test_plot_path_explicit_mode_defaults( self ):
        p = rgld._default_plot_path( "explicit", "/root", "cosa", None, None, None )
        self.assertIn( "start_to_", p )


class TestEmitPlot( unittest.TestCase ):
    """_emit_plot() — today skip, insufficient-data skip, success, failure."""

    def _args( self, **kw ):
        defaults = dict( plot_output=None, debug=False )
        defaults.update( kw )
        return MagicMock( **defaults )

    def test_today_mode_warns_and_returns_zero( self ):
        rc, out, err = _capture( rgld._emit_plot, self._args(), _result(), "today", "/root", "cosa" )
        self.assertEqual( rc, 0 )
        self.assertIn( "no effect in --today", err )

    def test_insufficient_days_warns_and_returns_zero( self ):
        rc, out, err = _capture(
            rgld._emit_plot, self._args(), _result( daily={ "2026-05-01": {} } ), "branch", "/root", "cosa"
        )
        self.assertEqual( rc, 0 )
        self.assertIn( "need at least 2 dates", err )

    def test_success_invokes_plotter( self ):
        with patch( "cosa.repo.run_git_loc_delta.plot_summary" ) as plot:
            rc, out, err = _capture(
                rgld._emit_plot, self._args(), _result(), "branch", "/root", "cosa"
            )
        self.assertEqual( rc, 0 )
        plot.assert_called_once()
        self.assertIn( "Plot written to", out )

    def test_plotter_failure_returns_one( self ):
        with patch( "cosa.repo.run_git_loc_delta.plot_summary", side_effect=RuntimeError( "mpl boom" ) ):
            rc, out, err = _capture(
                rgld._emit_plot, self._args( debug=True ), _result(), "branch", "/root", "cosa"
            )
        self.assertEqual( rc, 1 )
        self.assertIn( "Plot generation failed", err )

    def test_plotter_failure_no_debug_skips_traceback( self ):
        with patch( "cosa.repo.run_git_loc_delta.plot_summary", side_effect=RuntimeError( "boom" ) ):
            rc, out, err = _capture(
                rgld._emit_plot, self._args( debug=False ), _result(), "branch", "/root", "cosa"
            )
        self.assertEqual( rc, 1 )


class TestMain( unittest.TestCase ):
    """main() — output modes, error mapping, plot wiring, cross-repo path flow."""

    def setUp( self ):
        # Neutralise the git-subprocess root resolution for main() tests.
        self._root_patcher = patch(
            "cosa.repo.run_git_loc_delta._resolve_target_root", return_value=_EXTERNAL_REPO
        )
        self._root_patcher.start()
        self.addCleanup( self._root_patcher.stop )

        # Analyzer instance whose analyze() returns the canned result.
        self.analyzer = MagicMock()
        self.analyzer.analyze.return_value = _result()
        self._an_patcher = patch(
            "cosa.repo.run_git_loc_delta.GitLogLocDeltaAnalyzer", return_value=self.analyzer
        )
        self.mock_analyzer_cls = self._an_patcher.start()
        self.addCleanup( self._an_patcher.stop )

    def test_console_output( self ):
        with patch( "cosa.repo.run_git_loc_delta.format_console", return_value="CONSOLE TEXT" ):
            rc, out, err = _capture( rgld.main, [ "--repo-path", _EXTERNAL_REPO ] )
        self.assertEqual( rc, 0 )
        self.assertIn( "CONSOLE TEXT", out )

    def test_console_output_saved_to_file( self ):
        dest = tempfile.NamedTemporaryFile( suffix=".txt", delete=False ).name
        self.addCleanup( lambda: os.path.exists( dest ) and os.unlink( dest ) )
        with patch( "cosa.repo.run_git_loc_delta.format_console", return_value="SAVED" ):
            rc, out, err = _capture(
                rgld.main, [ "--repo-path", _EXTERNAL_REPO, "--save-output", dest, "-v" ]
            )
        self.assertEqual( rc, 0 )
        with open( dest ) as f:
            self.assertEqual( f.read(), "SAVED" )

    def test_json_output( self ):
        with patch( "cosa.repo.run_git_loc_delta.format_json", return_value='{"ok": true}' ):
            rc, out, err = _capture( rgld.main, [ "--output", "json", "--repo-path", _EXTERNAL_REPO ] )
        self.assertEqual( rc, 0 )
        self.assertIn( '{"ok": true}', out )

    def test_json_output_saved_to_file( self ):
        dest = tempfile.NamedTemporaryFile( suffix=".json", delete=False ).name
        self.addCleanup( lambda: os.path.exists( dest ) and os.unlink( dest ) )
        with patch( "cosa.repo.run_git_loc_delta.format_json", return_value='{"x":1}' ):
            rc, out, err = _capture(
                rgld.main, [ "--output", "json", "--save-output", dest, "-v" ]
            )
        self.assertEqual( rc, 0 )
        with open( dest ) as f:
            self.assertEqual( f.read(), '{"x":1}' )

    def test_csv_output_default_path( self ):
        with patch( "cosa.repo.run_git_loc_delta.write_csv", return_value=3 ) as wc, \
             patch( "cosa.repo.run_git_loc_delta.write_sidecar", return_value="/p/side.meta.json" ):
            rc, out, err = _capture(
                rgld.main, [ "--output", "csv", "--repo-path", _EXTERNAL_REPO, "-v" ]
            )
        self.assertEqual( rc, 0 )
        self.assertIn( "Wrote 3 rows", out )
        wc.assert_called_once()

    def test_branch_current_sentinel_passes_none_branch( self ):
        with patch( "cosa.repo.run_git_loc_delta.format_console", return_value="x" ):
            rc, out, err = _capture( rgld.main, [ "--branch", "--repo-path", _EXTERNAL_REPO ] )
        self.assertEqual( rc, 0 )
        # __CURRENT__ sentinel -> analyzer receives branch=None.
        self.assertIsNone( self.mock_analyzer_cls.call_args.kwargs[ "branch" ] )

    def test_cross_repo_path_flows_to_analyzer( self ):
        # CROSS-REPO: the external --repo-path is handed verbatim to the analyzer.
        with patch( "cosa.repo.run_git_loc_delta.format_console", return_value="x" ):
            rc, out, err = _capture( rgld.main, [ "--repo-path", _EXTERNAL_REPO ] )
        self.assertEqual( rc, 0 )
        self.assertEqual( self.mock_analyzer_cls.call_args.kwargs[ "repo_path" ], _EXTERNAL_REPO )

    def test_empty_range_date_error_returns_zero( self ):
        self.analyzer.analyze.side_effect = DateRangeError( "Empty rev-range for branch", branch="wip" )
        rc, out, err = _capture( rgld.main, [ "--branch", "wip", "--repo-path", _EXTERNAL_REPO ] )
        self.assertEqual( rc, 0 )
        self.assertIn( "No commits in range", out )

    def test_other_date_error_returns_one( self ):
        self.analyzer.analyze.side_effect = DateRangeError( "since > until" )
        rc, out, err = _capture(
            rgld.main, [ "--since", "2026-05-10", "--until", "2026-05-01", "--repo-path", _EXTERNAL_REPO, "--debug" ]
        )
        self.assertEqual( rc, 1 )
        self.assertIn( "Error:", err )

    def test_other_date_error_no_debug_returns_one( self ):
        self.analyzer.analyze.side_effect = DateRangeError( "since > until" )
        rc, out, err = _capture(
            rgld.main, [ "--since", "2026-05-10", "--until", "2026-05-01", "--repo-path", _EXTERNAL_REPO ]
        )
        self.assertEqual( rc, 1 )

    def test_git_command_error_returns_one( self ):
        self.analyzer.analyze.side_effect = GitCommandError( "git exploded" )
        rc, out, err = _capture( rgld.main, [ "--repo-path", _EXTERNAL_REPO, "--debug" ] )
        self.assertEqual( rc, 1 )
        self.assertIn( "Git error:", err )

    def test_git_command_error_no_debug_returns_one( self ):
        self.analyzer.analyze.side_effect = GitCommandError( "boom" )
        rc, out, err = _capture( rgld.main, [ "--repo-path", _EXTERNAL_REPO ] )
        self.assertEqual( rc, 1 )

    def test_generic_loc_delta_error_returns_one( self ):
        self.analyzer.analyze.side_effect = GitLocDeltaError( "something" )
        rc, out, err = _capture( rgld.main, [ "--repo-path", _EXTERNAL_REPO ] )
        self.assertEqual( rc, 1 )
        self.assertIn( "Error:", err )

    def test_generic_loc_delta_error_with_debug_returns_one( self ):
        self.analyzer.analyze.side_effect = GitLocDeltaError( "deep" )
        rc, out, err = _capture( rgld.main, [ "--repo-path", _EXTERNAL_REPO, "--debug" ] )
        self.assertEqual( rc, 1 )

    def test_unknown_output_value_returns_one( self ):
        # Defensive else-branch: argparse normally blocks this, so we inject an
        # args namespace with an out-of-contract --output to prove the guard returns 1.
        import argparse
        ns = argparse.Namespace(
            repo_path=_EXTERNAL_REPO, repo_name=None, today=False, since=None,
            branch=None, until=None, base="main", include_merges=False, author=None,
            output="bogus", save_output=None, plot=False, plot_output=None,
            verbose=False, debug=False,
        )
        fake_parser = MagicMock()
        fake_parser.parse_args.return_value = ns
        with patch( "cosa.repo.run_git_loc_delta.create_parser", return_value=fake_parser ):
            rc, out, err = _capture( rgld.main, [] )
        self.assertEqual( rc, 1 )
        self.assertIn( "Unknown --output", err )

    def test_plot_failure_propagates_exit_code( self ):
        with patch( "cosa.repo.run_git_loc_delta.format_console", return_value="x" ), \
             patch( "cosa.repo.run_git_loc_delta._emit_plot", return_value=1 ):
            rc, out, err = _capture(
                rgld.main, [ "--branch", "wip", "--plot", "--repo-path", _EXTERNAL_REPO ]
            )
        self.assertEqual( rc, 1 )

    def test_plot_success_keeps_zero( self ):
        with patch( "cosa.repo.run_git_loc_delta.format_console", return_value="x" ), \
             patch( "cosa.repo.run_git_loc_delta._emit_plot", return_value=0 ) as ep:
            rc, out, err = _capture(
                rgld.main, [ "--branch", "wip", "--plot", "--repo-path", _EXTERNAL_REPO ]
            )
        self.assertEqual( rc, 0 )
        ep.assert_called_once()


if __name__ == "__main__":
    unittest.main()
