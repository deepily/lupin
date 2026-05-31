"""
Unit tests for cosa.repo.run_git_loc_delta_global (cross-repo roll-up CLI).

The pandas aggregation, CSV I/O, and identity-stamping logic is exercised with
REAL pandas DataFrames and tempfile CSV fixtures (the data semantics must be
real to be meaningful). Only the matplotlib plotter (plot_summary) is mocked.

CROSS-REPO COVERAGE: --repos points at tempdir repos OUTSIDE the project tree;
main() resolves each via os.path.abspath and scans its io/git-loc-delta/.

Assertions harvested + strengthened from the module's 12-case quick_smoke_test
(now superseded by these pytest cases) plus the error/edge branches it could
not reach (stale-only repos, load failure, defensive filename fallbacks).
"""

import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr

import pandas as pd

import cosa.repo.run_git_loc_delta_global as g
from unittest.mock import patch, MagicMock


_V2_HEADER = "date,repo,branch,file_type,added,deleted,files_touched,commits\n"
_V1_HEADER = "date,file_type,added,deleted,files_touched,commits\n"


def _capture( fn, *args, **kwargs ):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout( out ), redirect_stderr( err ):
        rc = fn( *args, **kwargs )
    return rc, out.getvalue(), err.getvalue()


class _RepoFixtureMixin:
    """Builds tempdir 'repos' with io/git-loc-delta/ CSVs."""

    def _new_workdir( self ):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup( tmp.cleanup )
        return tmp.name

    def _make_repo( self, workdir, name, csv_basename, body, sidecar=None ):
        repo = os.path.join( workdir, name )
        csv_dir = os.path.join( repo, "io", "git-loc-delta" )
        os.makedirs( csv_dir, exist_ok=True )
        csv_path = os.path.join( csv_dir, csv_basename )
        with open( csv_path, "w" ) as f:
            f.write( body )
        if sidecar is not None:
            with open( csv_path + ".meta.json", "w" ) as f:
                json.dump( sidecar, f )
        return repo, csv_path


class TestParser( unittest.TestCase ):
    """create_parser() — required --repos + defaults."""

    def test_repos_required( self ):
        with self.assertRaises( SystemExit ):
            g.create_parser().parse_args( [] )

    def test_defaults( self ):
        args = g.create_parser().parse_args( [ "--repos", "/a", "/b" ] )
        self.assertEqual( args.repos, [ "/a", "/b" ] )
        self.assertEqual( args.output, "console" )
        self.assertTrue( args.prefer_branch_csv )


class TestFindCsvInRepo( _RepoFixtureMixin, unittest.TestCase ):
    """_find_csv_in_repo() — discovery, prefer-branch, stale."""

    def test_missing_dir_returns_none( self ):
        wd = self._new_workdir()
        bare = os.path.join( wd, "bare" )
        os.makedirs( bare )
        self.assertIsNone( g._find_csv_in_repo( bare, True, True ) )

    def test_no_csvs_returns_none( self ):
        wd = self._new_workdir()
        repo = os.path.join( wd, "r" )
        os.makedirs( os.path.join( repo, "io", "git-loc-delta" ) )
        self.assertIsNone( g._find_csv_in_repo( repo, True, True ) )

    def test_prefers_branch_over_date_csv( self ):
        wd = self._new_workdir()
        repo, branch_csv = self._make_repo( wd, "r", "r-wip-x-loc-delta.csv", _V2_HEADER )
        # Add a date-mode CSV alongside.
        date_csv = os.path.join( repo, "io", "git-loc-delta", "2026-05-21-loc-delta.csv" )
        with open( date_csv, "w" ) as f:
            f.write( _V2_HEADER )
        chosen = g._find_csv_in_repo( repo, True, True )
        self.assertEqual( os.path.basename( chosen ), "r-wip-x-loc-delta.csv" )

    def test_picks_most_recent_when_no_preference( self ):
        wd = self._new_workdir()
        repo, _ = self._make_repo( wd, "r", "2026-05-20-loc-delta.csv", _V2_HEADER )
        newer = os.path.join( repo, "io", "git-loc-delta", "2026-05-21-loc-delta.csv" )
        with open( newer, "w" ) as f:
            f.write( _V2_HEADER )
        os.utime( newer, ( 2_000_000_000, 2_000_000_000 ) )   # force clearly-newer mtime
        chosen = g._find_csv_in_repo( repo, False, False )
        self.assertEqual( os.path.basename( chosen ), "2026-05-21-loc-delta.csv" )

    def test_prefer_branch_but_only_date_csvs_keeps_them( self ):
        # prefer_branch=True yet every candidate is date-mode -> non_date_starting
        # is empty, so the full candidate list is retained (no crash).
        wd = self._new_workdir()
        repo, _ = self._make_repo( wd, "r", "2026-05-21-loc-delta.csv", _V2_HEADER )
        chosen = g._find_csv_in_repo( repo, True, False )
        self.assertEqual( os.path.basename( chosen ), "2026-05-21-loc-delta.csv" )


class TestFilenameHelpers( unittest.TestCase ):
    """_repo_from_filename / _branch_from_filename heuristics."""

    def test_repo_from_branch_wip_filename( self ):
        self.assertEqual(
            g._repo_from_filename( "/x/io/git-loc-delta/gamma-wip-legacy-loc-delta.csv" ), "gamma"
        )

    def test_repo_from_branch_plain_filename( self ):
        self.assertEqual(
            g._repo_from_filename( "/x/io/git-loc-delta/myrepo-feature-loc-delta.csv" ), "myrepo"
        )

    def test_repo_from_date_mode_uses_parent_dir( self ):
        self.assertEqual(
            g._repo_from_filename( "/root/lupin/io/git-loc-delta/2026-05-21-loc-delta.csv" ), "lupin"
        )

    def test_repo_from_date_mode_defensive_unknown( self ):
        self.assertEqual( g._repo_from_filename( "/2026-05-21-loc-delta.csv" ), "unknown" )

    def test_branch_from_wip_filename( self ):
        self.assertEqual(
            g._branch_from_filename( "/x/gamma-wip-legacy-loc-delta.csv" ), "wip-legacy"
        )

    def test_branch_from_date_mode_empty( self ):
        self.assertEqual( g._branch_from_filename( "/x/2026-05-21-loc-delta.csv" ), "" )

    def test_branch_from_plain_filename_empty( self ):
        self.assertEqual( g._branch_from_filename( "/x/myrepo-feature-loc-delta.csv" ), "" )


class TestLoadCsvWithIdentity( _RepoFixtureMixin, unittest.TestCase ):
    """_load_csv_with_identity() — v2, v1-sidecar, v1-filename, sidecar-parse-fail."""

    def test_v2_csv_with_sidecar( self ):
        wd = self._new_workdir()
        body = _V2_HEADER + "2026-05-20,alpha,wip-test,python,100,10,2,1\n"
        _, csv = self._make_repo(
            wd, "alpha", "alpha-wip-test-loc-delta.csv", body,
            sidecar={ "repo": "alpha", "branch": "wip-test" },
        )
        df = g._load_csv_with_identity( csv, True )
        self.assertEqual(
            list( df.columns ),
            [ "date", "repo", "branch", "file_type", "added", "deleted", "files_touched", "commits" ],
        )
        self.assertTrue( ( df[ "repo" ] == "alpha" ).all() )

    def test_v1_csv_identity_from_sidecar( self ):
        wd = self._new_workdir()
        body = _V1_HEADER + "2026-05-21,javascript,75,7,1,1\n"
        _, csv = self._make_repo(
            wd, "gamma", "gamma-wip-legacy-loc-delta.csv", body,
            sidecar={ "repo": "gamma-side", "branch": "wip-side" },
        )
        df = g._load_csv_with_identity( csv, True )
        self.assertEqual( df[ "repo" ].iloc[ 0 ], "gamma-side" )
        self.assertEqual( df[ "branch" ].iloc[ 0 ], "wip-side" )

    def test_v1_csv_identity_from_filename( self ):
        wd = self._new_workdir()
        body = _V1_HEADER + "2026-05-21,javascript,75,7,1,1\n"
        _, csv = self._make_repo( wd, "gamma", "gamma-wip-legacy-loc-delta.csv", body )
        df = g._load_csv_with_identity( csv, True )
        self.assertEqual( df[ "repo" ].iloc[ 0 ], "gamma" )
        self.assertEqual( df[ "branch" ].iloc[ 0 ], "wip-legacy" )

    def test_corrupt_sidecar_falls_back_to_filename( self ):
        wd = self._new_workdir()
        body = _V1_HEADER + "2026-05-21,javascript,75,7,1,1\n"
        _, csv = self._make_repo( wd, "gamma", "gamma-wip-legacy-loc-delta.csv", body )
        with open( csv + ".meta.json", "w" ) as f:
            f.write( "{ not valid json" )
        df = g._load_csv_with_identity( csv, True )   # parse failure logged, filename used
        self.assertEqual( df[ "repo" ].iloc[ 0 ], "gamma" )


class TestAggregation( unittest.TestCase ):
    """_build_aggregated_daily + _build_summary."""

    def _df( self ):
        return pd.DataFrame( [
            { "date": "2026-05-20", "repo": "alpha", "branch": "w", "file_type": "py", "added": 100, "deleted": 10, "files_touched": 2, "commits": 1 },
            { "date": "2026-05-21", "repo": "alpha", "branch": "w", "file_type": "py", "added": 200, "deleted": 20, "files_touched": 3, "commits": 2 },
            { "date": "2026-05-21", "repo": "beta",  "branch": "w", "file_type": "ts", "added": 300, "deleted": 30, "files_touched": 4, "commits": 3 },
        ] )

    def test_aggregated_daily_groups_by_date_and_repo( self ):
        daily = g._build_aggregated_daily( self._df() )
        self.assertEqual( set( daily.keys() ), { "2026-05-20", "2026-05-21" } )
        self.assertEqual( len( daily[ "2026-05-21" ][ "by_repo" ] ), 2 )
        # by_repo sorted by added desc -> beta (300) before alpha (200)
        self.assertEqual( daily[ "2026-05-21" ][ "by_repo" ][ 0 ][ "repo" ], "beta" )

    def test_summary_totals( self ):
        s = g._build_summary( self._df() )
        self.assertEqual( s[ "total_added" ], 600 )
        self.assertEqual( s[ "total_deleted" ], 60 )
        self.assertEqual( s[ "net" ], 540 )
        self.assertEqual( s[ "total_days" ], 2 )
        self.assertEqual( s[ "repos" ], [ "alpha", "beta" ] )

    def test_summary_empty_df_zeros( self ):
        s = g._build_summary( pd.DataFrame() )
        self.assertEqual( s[ "total_added" ], 0 )
        self.assertEqual( s[ "repos" ], [] )


class TestFormatters( unittest.TestCase ):
    """_format_console / _format_json."""

    def _daily_summary( self ):
        df = pd.DataFrame( [
            { "date": "2026-05-21", "repo": "alpha", "branch": "w", "file_type": "py", "added": 200, "deleted": 20, "files_touched": 3, "commits": 2 },
            { "date": "2026-05-22", "repo": "beta",  "branch": "w", "file_type": "ts", "added": 300, "deleted": 30, "files_touched": 4, "commits": 3 },
        ] )
        return g._build_aggregated_daily( df ), g._build_summary( df )

    def test_console_no_data( self ):
        self.assertIn( "No data in range", g._format_console( {}, { "repos": [] }, None, None ) )

    def test_console_with_data( self ):
        daily, summary = self._daily_summary()
        text = g._format_console( daily, summary, None, None )
        self.assertIn( "Cross-Repo Daily LoC Delta", text )
        self.assertIn( "alpha", text )
        self.assertIn( "beta", text )

    def test_json_shape( self ):
        daily, summary = self._daily_summary()
        parsed = json.loads( g._format_json( daily, summary, "2026-05-21", "2026-05-22" ) )
        self.assertEqual( parsed[ "since" ], "2026-05-21" )
        self.assertIn( "summary", parsed )
        self.assertEqual( len( parsed[ "days" ] ), 2 )
        self.assertIn( "by_repo", parsed[ "days" ][ 0 ] )


class TestDefaultPath( unittest.TestCase ):
    """_default_path() — csv vs png under io/loc-delta-global/."""

    def test_csv_path( self ):
        p = g._default_path( "/cwd", "csv", "2026-05-01", "2026-05-10" )
        self.assertTrue( p.endswith( "io/loc-delta-global/global-2026-05-01_to_2026-05-10-loc-delta.csv" ) )

    def test_png_path_with_defaults( self ):
        p = g._default_path( "/cwd", "png", None, None )
        self.assertIn( "io/loc-delta-global/global-start_to_", p )
        self.assertTrue( p.endswith( "-plot.png" ) )


class TestMain( _RepoFixtureMixin, unittest.TestCase ):
    """main() — end-to-end across OUTSIDE-tree repos, plot_summary mocked."""

    def _two_active_repos( self, wd ):
        a_body = (
            _V2_HEADER
            + "2026-05-20,alpha,wip,python,100,10,2,1\n"
            + "2026-05-21,alpha,wip,python,200,20,3,2\n"
        )
        repo_a, _ = self._make_repo(
            wd, "alpha", "alpha-wip-loc-delta.csv", a_body,
            sidecar={ "repo": "alpha", "branch": "wip" },
        )
        b_body = _V2_HEADER + "2026-05-21,beta,wip,typescript,300,30,4,3\n"
        repo_b, _ = self._make_repo(
            wd, "beta", "beta-wip-loc-delta.csv", b_body,
            sidecar={ "repo": "beta", "branch": "wip" },
        )
        return repo_a, repo_b

    def test_json_end_to_end_cross_repo( self ):
        wd = self._new_workdir()
        repo_a, repo_b = self._two_active_repos( wd )
        dest = os.path.join( wd, "out.json" )
        rc, out, err = _capture(
            g.main,
            [ "--repos", repo_a, repo_b, "--since", "2026-05-20", "--until", "2026-05-21",
              "--output", "json", "--save-output", dest, "-v" ],
        )
        self.assertEqual( rc, 0 )
        with open( dest ) as f:
            parsed = json.load( f )
        self.assertEqual( sorted( parsed[ "repos" ] ), [ "alpha", "beta" ] )
        self.assertEqual( parsed[ "summary" ][ "net" ], ( 100 + 200 + 300 ) - ( 10 + 20 + 30 ) )

    def test_console_to_stdout( self ):
        wd = self._new_workdir()
        repo_a, repo_b = self._two_active_repos( wd )
        rc, out, err = _capture(
            g.main,
            [ "--repos", repo_a, repo_b, "--since", "2026-05-20", "--until", "2026-05-21" ],
        )
        self.assertEqual( rc, 0 )
        self.assertIn( "Cross-Repo Daily LoC Delta", out )

    def test_csv_output_writes_file( self ):
        wd = self._new_workdir()
        repo_a, repo_b = self._two_active_repos( wd )
        dest = os.path.join( wd, "sub", "out.csv" )   # parent dir auto-created
        rc, out, err = _capture(
            g.main,
            [ "--repos", repo_a, repo_b, "--since", "2026-05-20", "--until", "2026-05-21",
              "--output", "csv", "--save-output", dest ],
        )
        self.assertEqual( rc, 0 )
        self.assertIn( "Wrote", out )
        self.assertTrue( os.path.isfile( dest ) )

    def test_today_default_applied( self ):
        wd = self._new_workdir()
        repo_a, repo_b = self._two_active_repos( wd )
        dest = os.path.join( wd, "today.json" )
        rc, out, err = _capture(
            g.main, [ "--repos", repo_a, repo_b, "--output", "json", "--save-output", dest, "-v" ]
        )
        self.assertEqual( rc, 0 )
        from datetime import date as _d
        today = _d.today().isoformat()
        with open( dest ) as f:
            parsed = json.load( f )
        self.assertEqual( parsed[ "since" ], today )
        self.assertEqual( parsed[ "until" ], today )

    def test_stale_repo_warns_but_succeeds( self ):
        wd = self._new_workdir()
        repo_a, _ = self._two_active_repos( wd )
        stale = os.path.join( wd, "delta" )
        os.makedirs( stale )                          # no io/git-loc-delta/
        dest = os.path.join( wd, "stale.json" )
        rc, out, err = _capture(
            g.main,
            [ "--repos", repo_a, stale, "--since", "2026-05-20", "--until", "2026-05-21",
              "--output", "json", "--save-output", dest ],
        )
        self.assertEqual( rc, 0 )
        self.assertIn( "Warning: no CSV found", err )
        with open( dest ) as f:
            self.assertEqual( json.load( f )[ "repos" ], [ "alpha" ] )

    def test_since_only_filters_lower_bound( self ):
        wd = self._new_workdir()
        repo_a, repo_b = self._two_active_repos( wd )
        dest = os.path.join( wd, "since.json" )
        rc, out, err = _capture(
            g.main,
            [ "--repos", repo_a, repo_b, "--since", "2026-05-21",
              "--output", "json", "--save-output", dest ],
        )
        self.assertEqual( rc, 0 )
        with open( dest ) as f:
            parsed = json.load( f )
        # Only the 2026-05-21 day survives the lower-bound filter.
        self.assertEqual( [ d[ "date" ] for d in parsed[ "days" ] ], [ "2026-05-21" ] )

    def test_until_only_filters_upper_bound( self ):
        wd = self._new_workdir()
        repo_a, repo_b = self._two_active_repos( wd )
        dest = os.path.join( wd, "until.json" )
        rc, out, err = _capture(
            g.main,
            [ "--repos", repo_a, repo_b, "--until", "2026-05-20",
              "--output", "json", "--save-output", dest ],
        )
        self.assertEqual( rc, 0 )
        with open( dest ) as f:
            parsed = json.load( f )
        self.assertEqual( [ d[ "date" ] for d in parsed[ "days" ] ], [ "2026-05-20" ] )

    def test_console_stale_section_appended( self ):
        wd = self._new_workdir()
        repo_a, _ = self._two_active_repos( wd )
        stale = os.path.join( wd, "delta" )
        os.makedirs( stale )
        rc, out, err = _capture(
            g.main,
            [ "--repos", repo_a, stale, "--since", "2026-05-20", "--until", "2026-05-21" ],
        )
        self.assertEqual( rc, 0 )
        self.assertIn( "Stale repos (no CSV found)", out )

    def test_console_save_output_to_file( self ):
        wd = self._new_workdir()
        repo_a, repo_b = self._two_active_repos( wd )
        dest = os.path.join( wd, "console.txt" )
        rc, out, err = _capture(
            g.main,
            [ "--repos", repo_a, repo_b, "--since", "2026-05-20", "--until", "2026-05-21",
              "--save-output", dest ],
        )
        self.assertEqual( rc, 0 )
        with open( dest ) as f:
            self.assertIn( "Cross-Repo Daily LoC Delta", f.read() )

    def test_json_to_stdout( self ):
        wd = self._new_workdir()
        repo_a, repo_b = self._two_active_repos( wd )
        rc, out, err = _capture(
            g.main,
            [ "--repos", repo_a, repo_b, "--since", "2026-05-20", "--until", "2026-05-21",
              "--output", "json" ],
        )
        self.assertEqual( rc, 0 )
        self.assertEqual( json.loads( out )[ "summary" ][ "net" ], 540 )

    def test_csv_to_existing_parent_dir( self ):
        wd = self._new_workdir()
        repo_a, repo_b = self._two_active_repos( wd )
        dest = os.path.join( wd, "out.csv" )   # parent (wd) already exists -> skip makedirs
        rc, out, err = _capture(
            g.main,
            [ "--repos", repo_a, repo_b, "--since", "2026-05-20", "--until", "2026-05-21",
              "--output", "csv", "--save-output", dest ],
        )
        self.assertEqual( rc, 0 )
        self.assertTrue( os.path.isfile( dest ) )

    def test_all_stale_returns_error( self ):
        wd = self._new_workdir()
        stale = os.path.join( wd, "empty" )
        os.makedirs( stale )
        rc, out, err = _capture( g.main, [ "--repos", stale ] )
        self.assertEqual( rc, g.EXIT_ERROR )
        self.assertIn( "no CSVs found", err )

    def test_load_failure_returns_error( self ):
        wd = self._new_workdir()
        # CSV missing the canonical columns -> column reorder raises -> EXIT_ERROR.
        bad_body = "date,added\n2026-05-21,5\n"
        repo, _ = self._make_repo( wd, "bad", "bad-wip-loc-delta.csv", bad_body )
        rc, out, err = _capture( g.main, [ "--repos", repo, "--debug" ] )
        self.assertEqual( rc, g.EXIT_ERROR )
        self.assertIn( "Failed to load", err )

    def test_load_failure_no_debug_returns_error( self ):
        wd = self._new_workdir()
        bad_body = "date,added\n2026-05-21,5\n"
        repo, _ = self._make_repo( wd, "bad", "bad-wip-loc-delta.csv", bad_body )
        rc, out, err = _capture( g.main, [ "--repos", repo ] )
        self.assertEqual( rc, g.EXIT_ERROR )

    def test_plot_success( self ):
        wd = self._new_workdir()
        repo_a, repo_b = self._two_active_repos( wd )
        with patch( "cosa.repo.run_git_loc_delta_global.plot_summary" ) as plot:
            rc, out, err = _capture(
                g.main,
                [ "--repos", repo_a, repo_b, "--since", "2026-05-20", "--until", "2026-05-21", "--plot" ],
            )
        self.assertEqual( rc, 0 )
        plot.assert_called_once()
        self.assertIn( "Plot written to", out )

    def test_plot_insufficient_days_skips( self ):
        wd = self._new_workdir()
        repo_b_body = _V2_HEADER + "2026-05-21,beta,wip,ts,300,30,4,3\n"
        repo_b, _ = self._make_repo(
            wd, "beta", "beta-wip-loc-delta.csv", repo_b_body,
            sidecar={ "repo": "beta", "branch": "wip" },
        )
        with patch( "cosa.repo.run_git_loc_delta_global.plot_summary" ) as plot:
            rc, out, err = _capture(
                g.main,
                [ "--repos", repo_b, "--since", "2026-05-21", "--until", "2026-05-21", "--plot" ],
            )
        self.assertEqual( rc, 0 )
        plot.assert_not_called()
        self.assertIn( "need", err )

    def test_plot_failure_returns_error( self ):
        wd = self._new_workdir()
        repo_a, repo_b = self._two_active_repos( wd )
        with patch(
            "cosa.repo.run_git_loc_delta_global.plot_summary",
            side_effect=RuntimeError( "mpl boom" ),
        ):
            rc, out, err = _capture(
                g.main,
                [ "--repos", repo_a, repo_b, "--since", "2026-05-20", "--until", "2026-05-21",
                  "--plot", "--debug" ],
            )
        self.assertEqual( rc, g.EXIT_ERROR )
        self.assertIn( "Plot generation failed", err )

    def test_plot_failure_no_debug_returns_error( self ):
        wd = self._new_workdir()
        repo_a, repo_b = self._two_active_repos( wd )
        with patch(
            "cosa.repo.run_git_loc_delta_global.plot_summary",
            side_effect=RuntimeError( "boom" ),
        ):
            rc, out, err = _capture(
                g.main,
                [ "--repos", repo_a, repo_b, "--since", "2026-05-20", "--until", "2026-05-21", "--plot" ],
            )
        self.assertEqual( rc, g.EXIT_ERROR )

    def test_out_of_contract_output_falls_through_to_exit_ok( self ):
        # The output if/elif chain has no `else`; an out-of-contract --output
        # (argparse normally blocks it) falls through to the plot check and
        # returns OK with no emission. Injected namespace documents that path.
        import argparse
        wd = self._new_workdir()
        repo_a, repo_b = self._two_active_repos( wd )
        ns = argparse.Namespace(
            repos=[ repo_a, repo_b ], since="2026-05-20", until="2026-05-21",
            prefer_branch_csv=True, output="bogus", save_output=None,
            plot=False, plot_output=None, verbose=False, debug=False,
        )
        fake_parser = MagicMock()
        fake_parser.parse_args.return_value = ns
        with patch( "cosa.repo.run_git_loc_delta_global.create_parser", return_value=fake_parser ):
            rc, out, err = _capture( g.main, [] )
        self.assertEqual( rc, g.EXIT_OK )
        self.assertEqual( out, "" )


if __name__ == "__main__":
    unittest.main()
