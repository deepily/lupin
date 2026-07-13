"""
Unit tests for `cosa.repo.run_git_loc_delta_global`.

REWRITTEN 2026-07-13 (Mr. Radio 🦉) alongside the module, closing bugs `bbff93a3`
(under-report) + `37a8beeb` (commit double-count).

**Why these fixtures are real git repos, not synthesized CSVs.** The suite this
replaces built CSV fixtures and asserted the aggregator concatenated them correctly.
It passed, every time, while the tool under-reported a live repo by 36% — because a
tool that never touched git was tested by a suite that never touched git either. The
CSV was an exactly-correct answer to the wrong question, and the tests only ever
re-asked the wrong question.

So: every fixture here is a real `git init` + real commits, and the assertions are
against git's own answer. A test that cannot see the bug is not a test.

Regression anchors:
    - `TestMainOnlyRepo`    → bbff93a3. Work committed straight to `main`, no WIP
                              branch. The old CSV-reading path scored this ZERO.
    - `TestCommitDedup`     → 37a8beeb. One commit touching .py + .md counts ONCE.
    - `TestCoverageWarning` → the guard that would have caught both.
"""

import argparse
import io
import json
import os
import subprocess
import tempfile
import unittest
from contextlib    import redirect_stdout, redirect_stderr
from unittest.mock import patch, MagicMock

import pandas as pd

import cosa.repo.run_git_loc_delta_global as g
from cosa.repo.git_loc_delta.exceptions import GitLocDeltaError


# ─────────────────────────────────────────────────────────────────────────────
# Real-git fixtures
# ─────────────────────────────────────────────────────────────────────────────

class _GitRepoFixtureMixin:
    """Builds REAL git repositories in a tempdir. See module docstring for why."""

    def setUp( self ):
        self.workdir = tempfile.mkdtemp( prefix="loc_delta_global_test_" )
        self.addCleanup( self._cleanup )

    def _cleanup( self ):
        import shutil
        shutil.rmtree( self.workdir, ignore_errors=True )

    def _git( self, repo, *cmd, date="2026-07-10T12:00:00" ):
        env = {
            **os.environ,
            "GIT_AUTHOR_DATE":    date,
            "GIT_COMMITTER_DATE": date,
        }
        subprocess.run( [ "git", *cmd ], cwd=repo, check=True, capture_output=True, env=env )

    def init_repo( self, name ):
        repo = os.path.join( self.workdir, name )
        os.makedirs( repo )
        self._git( repo, "init", "-q", "-b", "main" )
        self._git( repo, "config", "user.email", "test@local" )
        self._git( repo, "config", "user.name",  "Test" )
        return repo

    def commit( self, repo, files, message="commit", date="2026-07-10T12:00:00" ):
        for rel, content in files.items():
            full = os.path.join( repo, rel )
            os.makedirs( os.path.dirname( full ), exist_ok=True )
            with open( full, "w" ) as f:
                f.write( content )
        self._git( repo, "add", "-A", date=date )
        self._git( repo, "commit", "-q", "-m", message, date=date )

    def commit_binary( self, repo, rel, message="binary", date="2026-07-10T12:00:00" ):
        """A binary-only commit — numstat emits `-  -`, so it yields ZERO counted rows."""
        full = os.path.join( repo, rel )
        os.makedirs( os.path.dirname( full ), exist_ok=True )
        with open( full, "wb" ) as f:
            f.write( bytes( range( 256 ) ) * 4 )
        self._git( repo, "add", "-A", date=date )
        self._git( repo, "commit", "-q", "-m", message, date=date )

    def plain_dir( self, name ):
        d = os.path.join( self.workdir, name )
        os.makedirs( d )
        return d

    def not_a_repo( self ):
        return self.plain_dir( "not_a_repo" )

    def lines( self, prefix, n ):
        return "\n".join( f"{prefix}{i}" for i in range( n ) ) + "\n"


def _analyze( repos, since="2026-07-09", until="2026-07-12", all_branches=True,
              include_merges=False, verbose=False, debug=False ):
    return g._analyze_repos(
        repo_paths     = repos,
        since          = since,
        until          = until,
        all_branches   = all_branches,
        include_merges = include_merges,
        verbose        = verbose,
        debug          = debug,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Regression: bbff93a3 — work on `main` must be counted
# ─────────────────────────────────────────────────────────────────────────────

class TestMainOnlyRepo( _GitRepoFixtureMixin, unittest.TestCase ):
    """
    bbff93a3. Work that landed on `main` sits on the BASELINE side of `main..<branch>`
    and was structurally uncountable. The old tool scored such a repo ZERO.
    """

    def test_main_only_work_is_counted( self ):
        repo = self.init_repo( "main_only" )
        self.commit( repo, { "src/a.py": self.lines( "x", 10 ) }, "straight to main" )

        df, commits, cov, empty, skipped = _analyze( [ repo ] )
        summary = g._build_summary( df, commits )

        self.assertEqual( summary[ "total_added"   ], 10 )
        self.assertEqual( summary[ "total_commits" ], 1  )
        self.assertEqual( empty, [] )

    def test_main_side_and_branch_side_both_counted( self ):
        repo = self.init_repo( "branched" )
        self.commit( repo, { "src/b.py": self.lines( "base", 5 ) }, "landed on main" )
        self._git( repo, "checkout", "-q", "-b", "wip-feature" )
        self.commit( repo, { "src/c.py": self.lines( "feat", 7 ) }, "on the wip branch" )

        df, commits, cov, empty, skipped = _analyze( [ repo ] )
        summary = g._build_summary( df, commits )

        self.assertEqual( summary[ "total_added"   ], 12 )   # 5 on main + 7 on branch
        self.assertEqual( summary[ "total_commits" ], 2  )

    def test_sibling_branch_work_counted_under_all_branches( self ):
        """A branch that does NOT descend from HEAD is still work done in the window."""
        repo = self.init_repo( "siblings" )
        self.commit( repo, { "src/base.py": self.lines( "b", 3 ) }, "base" )
        self._git( repo, "checkout", "-q", "-b", "lane-a" )
        self.commit( repo, { "src/a.py": self.lines( "a", 4 ) }, "lane a" )
        self._git( repo, "checkout", "-q", "main" )
        self._git( repo, "checkout", "-q", "-b", "lane-b" )
        self.commit( repo, { "src/b.py": self.lines( "b", 6 ) }, "lane b" )

        # HEAD is lane-b → sees base + lane-b only (3 + 6).
        df_head, commits_head, *_ = _analyze( [ repo ], all_branches=False )
        self.assertEqual( g._build_summary( df_head, commits_head )[ "total_added" ], 9 )

        # --branches → sees base + lane-a + lane-b (3 + 4 + 6), each commit exactly ONCE.
        df_all, commits_all, *_ = _analyze( [ repo ], all_branches=True )
        summary = g._build_summary( df_all, commits_all )
        self.assertEqual( summary[ "total_added"   ], 13 )
        self.assertEqual( summary[ "total_commits" ], 3  )


# ─────────────────────────────────────────────────────────────────────────────
# Regression: 37a8beeb — a commit is not decomposable by file type
# ─────────────────────────────────────────────────────────────────────────────

class TestCommitDedup( _GitRepoFixtureMixin, unittest.TestCase ):
    """
    37a8beeb. The per-(date, file_type) commit buckets OVERLAP: a commit touching a
    .py and a .md appears in both. Summing them double-counts.
    """

    def test_one_commit_two_file_types_counts_once( self ):
        repo = self.init_repo( "multitype" )
        self.commit( repo, {
            "src/d.py":  self.lines( "py", 3 ),
            "docs/e.md": self.lines( "md", 4 ),
        }, "one commit, two file types" )

        df, commits, cov, empty, skipped = _analyze( [ repo ] )
        summary = g._build_summary( df, commits )

        self.assertEqual( len( df ), 2, "expected one row per file type" )
        self.assertEqual( summary[ "total_commits" ], 1, "DOUBLE-COUNT REGRESSION (37a8beeb)" )

        # The naive sum — the exact expression that shipped the bug — IS 2. Pinned here
        # so nobody 'simplifies' the aggregation back into it.
        self.assertEqual( int( df[ "repo_date_commits" ].sum() ), 2 )

    def test_by_file_type_exposes_no_commits_key( self ):
        """Offering a per-file-type commit count is what invited the bug. Don't offer it."""
        repo = self.init_repo( "multitype" )
        self.commit( repo, { "a.py": "x\n", "b.md": "y\n" }, "two types" )

        df, commits, *_ = _analyze( [ repo ] )
        daily = g._build_aggregated_daily( df, commits )

        for row in daily[ "2026-07-10" ][ "by_file_type" ]:
            self.assertNotIn( "commits", row )

    def test_commits_summed_only_across_safe_axes( self ):
        repo_a = self.init_repo( "a" )
        self.commit( repo_a, { "a.py":  "1\n" }, "a1", date="2026-07-10T09:00:00" )
        self.commit( repo_a, { "a2.py": "2\n" }, "a2", date="2026-07-11T09:00:00" )
        repo_b = self.init_repo( "b" )
        self.commit( repo_b, { "b.py": "1\n", "b.md": "2\n" }, "b1", date="2026-07-10T09:00:00" )

        df, commits, *_ = _analyze( [ repo_a, repo_b ] )
        summary = g._build_summary( df, commits )
        daily   = g._build_aggregated_daily( df, commits )

        self.assertEqual( summary[ "total_commits" ], 3 )          # 2 in a, 1 in b
        self.assertEqual( daily[ "2026-07-10" ][ "commits" ], 2 )  # a1 + b1 (b1 counted ONCE)
        self.assertEqual( daily[ "2026-07-11" ][ "commits" ], 1 )  # a2


# ─────────────────────────────────────────────────────────────────────────────
# The coverage guard
# ─────────────────────────────────────────────────────────────────────────────

class TestCoverageWarning( _GitRepoFixtureMixin, unittest.TestCase ):

    def test_binary_only_commit_triggers_coverage_warning( self ):
        """
        A binary-only commit yields zero countable rows — benign, but the operator must
        SEE it rather than infer it. This is the exact shape the guard fires on in
        production (PNG visual-baseline rebaselines).
        """
        repo = self.init_repo( "with_binary" )
        self.commit( repo, { "a.py": self.lines( "x", 3 ) }, "text" )
        self.commit_binary( repo, "img/logo.png", "binary only" )

        err = io.StringIO()
        with redirect_stderr( err ):
            df, commits, cov, empty, skipped = _analyze( [ repo ] )

        self.assertEqual( len( cov ), 1 )
        self.assertFalse( cov[ 0 ][ "reconciled" ] )
        self.assertEqual( cov[ 0 ][ "expected" ], 2 )
        self.assertEqual( cov[ 0 ][ "counted"  ], 1 )
        self.assertIn( "COVERAGE MISMATCH", err.getvalue() )

    def test_clean_repo_reconciles( self ):
        repo = self.init_repo( "clean" )
        self.commit( repo, { "a.py": self.lines( "x", 3 ) }, "text" )

        df, commits, cov, empty, skipped = _analyze( [ repo ] )
        self.assertTrue( cov[ 0 ][ "reconciled" ] )


# ─────────────────────────────────────────────────────────────────────────────
# _analyze_repos edges
# ─────────────────────────────────────────────────────────────────────────────

class TestAnalyzeRepos( _GitRepoFixtureMixin, unittest.TestCase ):

    def test_non_git_path_skipped_not_fatal( self ):
        repo  = self.init_repo( "real" )
        self.commit( repo, { "a.py": self.lines( "x", 4 ) }, "work" )
        plain = self.not_a_repo()

        err = io.StringIO()
        with redirect_stderr( err ):
            df, commits, cov, empty, skipped = _analyze( [ repo, plain ] )

        self.assertEqual( skipped, [ plain ] )
        self.assertIn( "not a git repository", err.getvalue() )
        self.assertEqual( g._build_summary( df, commits )[ "total_added" ], 4 )

    def test_empty_window_reports_empty_repo( self ):
        repo = self.init_repo( "empty_window" )
        self.commit( repo, { "a.py": "x\n" }, "work" )

        df, commits, cov, empty, skipped = _analyze( [ repo ], since="2099-01-01", until="2099-01-02" )

        self.assertTrue( df.empty )
        self.assertEqual( empty, [ "empty_window" ] )
        self.assertEqual( g._build_summary( df, commits )[ "total_commits" ], 0 )

    def test_verbose_emits_progress( self ):
        repo = self.init_repo( "verbose" )
        self.commit( repo, { "a.py": self.lines( "x", 2 ) }, "work" )

        err = io.StringIO()
        with redirect_stderr( err ):
            _analyze( [ repo ], verbose=True )

        out = err.getvalue()
        self.assertIn( "[analyze] verbose:", out )
        self.assertIn( "--branches", out )

    def test_verbose_reports_empty_window( self ):
        repo = self.init_repo( "verbose_empty" )
        self.commit( repo, { "a.py": "x\n" }, "work" )

        err = io.StringIO()
        with redirect_stderr( err ):
            _analyze( [ repo ], since="2099-01-01", until="2099-01-02", verbose=True )

        self.assertIn( "no commits in window", err.getvalue() )

    def test_head_only_mode_labelled_in_verbose( self ):
        repo = self.init_repo( "head_only" )
        self.commit( repo, { "a.py": self.lines( "x", 3 ) }, "work" )

        err = io.StringIO()
        with redirect_stderr( err ):
            _analyze( [ repo ], all_branches=False, verbose=True )

        self.assertIn( "(HEAD only)", err.getvalue() )

    def test_no_window_uses_today_mode( self ):
        """since=None and until=None → mode='today', never 'branch'."""
        repo = self.init_repo( "today_mode" )
        self.commit( repo, { "a.py": "x\n" }, "work" )

        df, commits, cov, empty, skipped = _analyze( [ repo ], since=None, until=None )
        self.assertEqual( skipped, [] )

    def test_include_merges_adds_no_loc_but_guard_flags_the_merge( self ):
        """
        A subtlety worth pinning. `git log --numstat` emits a merge commit's HEADER but
        NO file rows (numstat is silent on merges without -m/--cc), so a merge contributes
        zero counted rows and never enters the SHA set — LoC and commit totals are
        IDENTICAL with and without --include-merges.

        But `git rev-list` DOES count the merge. So the coverage guard correctly reports
        it as uncounted — the same benign-but-visible shape as a binary-only commit. This
        is the guard doing its job, not a defect.
        """
        repo = self.init_repo( "merges" )
        self.commit( repo, { "a.py": self.lines( "a", 3 ) }, "base" )
        self._git( repo, "checkout", "-q", "-b", "feature" )
        self.commit( repo, { "b.py": self.lines( "b", 3 ) }, "feature" )
        self._git( repo, "checkout", "-q", "main" )
        self.commit( repo, { "c.py": self.lines( "c", 3 ) }, "main moves" )
        self._git( repo, "merge", "-q", "--no-ff", "feature", "-m", "merge feature" )

        err = io.StringIO()
        with redirect_stderr( err ):
            df_no,  commits_no,  cov_no,  *_ = _analyze( [ repo ], include_merges=False )
            df_yes, commits_yes, cov_yes, *_ = _analyze( [ repo ], include_merges=True )

        s_no  = g._build_summary( df_no,  commits_no  )
        s_yes = g._build_summary( df_yes, commits_yes )

        # The merge carries no numstat rows → totals are unchanged.
        self.assertEqual( s_yes[ "total_added"   ], s_no[ "total_added"   ] )
        self.assertEqual( s_yes[ "total_commits" ], s_no[ "total_commits" ] )

        # Without merges: git and we agree exactly.
        self.assertTrue( cov_no[ 0 ][ "reconciled" ] )

        # With merges: git counts the merge, we cannot → the guard says so, out loud.
        self.assertFalse( cov_yes[ 0 ][ "reconciled" ] )
        self.assertEqual( cov_yes[ 0 ][ "expected" ] - cov_yes[ 0 ][ "counted" ], 1 )
        self.assertIn( "COVERAGE MISMATCH", err.getvalue() )

    def test_debug_flag_threaded( self ):
        repo = self.init_repo( "dbg" )
        self.commit( repo, { "a.py": "x\n" }, "work" )
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout( out ), redirect_stderr( err ):
            _analyze( [ repo ], debug=True )
        self.assertIn( "GitLogLocDeltaAnalyzer", out.getvalue() )

    def test_is_git_repo( self ):
        repo = self.init_repo( "r" )
        self.assertTrue(  g._is_git_repo( repo ) )
        self.assertFalse( g._is_git_repo( self.not_a_repo() ) )


class TestFreshRepoWithNoCommits( _GitRepoFixtureMixin, unittest.TestCase ):
    """
    A `git init` with ZERO commits is a legitimate roster entry — the roll-up's whole
    subject is fresh repos. `git log` on one exits 128, which used to escape as a raw
    traceback and kill the ENTIRE roll-up (all other repos included) on the --head-only
    path. Found in review of this very rewrite.
    """

    def test_empty_repo_reported_not_fatal_all_branches( self ):
        empty = self.init_repo( "brand_new" )   # git init, no commits
        df, commits, cov, empty_repos, skipped = _analyze( [ empty ] )
        self.assertEqual( empty_repos, [ "brand_new" ] )
        self.assertTrue( df.empty )

    def test_empty_repo_reported_not_fatal_head_only( self ):
        """The path that actually crashed: --head-only on a zero-commit repo."""
        empty = self.init_repo( "brand_new" )
        df, commits, cov, empty_repos, skipped = _analyze( [ empty ], all_branches=False )
        self.assertEqual( empty_repos, [ "brand_new" ] )

    def test_empty_repo_does_not_take_down_its_neighbours( self ):
        """The severity: one fresh repo used to abort the whole fleet's roll-up."""
        empty = self.init_repo( "brand_new" )
        real  = self.init_repo( "real" )
        self.commit( real, { "a.py": self.lines( "x", 7 ) }, "work" )

        df, commits, cov, empty_repos, skipped = _analyze( [ empty, real ], all_branches=False )
        self.assertEqual( g._build_summary( df, commits )[ "total_added" ], 7 )
        self.assertEqual( empty_repos, [ "brand_new" ] )

    def test_has_any_commits( self ):
        empty = self.init_repo( "e" )
        full  = self.init_repo( "f" )
        self.commit( full, { "a.py": "x\n" }, "c" )
        self.assertFalse( g._has_any_commits( empty ) )
        self.assertTrue(  g._has_any_commits( full  ) )


class TestDuplicateRepoBasenames( _GitRepoFixtureMixin, unittest.TestCase ):
    """
    Repo identity keys the commit-count map. Two roster entries sharing a basename
    (`google/foo` and `other/foo` — the roster IS globbed across grouping dirs) collided
    on (repo_name, date): the second silently OVERWROTE the first's commit count.

    A SILENT UNDERCOUNT — the exact failure class this module was rewritten to kill.
    Caught reviewing the rewrite: two repos named `lupin` reported 1 commit, not 2.
    """

    def _dup_repos( self ):
        a = self.init_repo( os.path.join( "groupA", "samename" ) )
        b = self.init_repo( os.path.join( "groupB", "samename" ) )
        self.commit( a, { "a.py": self.lines( "a", 4 ) }, "in A" )
        self.commit( b, { "b.py": self.lines( "b", 6 ) }, "in B" )
        return a, b

    def init_repo( self, name ):
        repo = os.path.join( self.workdir, name )
        os.makedirs( repo, exist_ok=True )
        self._git( repo, "init", "-q", "-b", "main" )
        self._git( repo, "config", "user.email", "test@local" )
        self._git( repo, "config", "user.name",  "Test" )
        return repo

    def test_colliding_basenames_do_not_lose_commits( self ):
        a, b = self._dup_repos()
        df, commits, cov, empty, skipped = _analyze( [ a, b ] )
        summary = g._build_summary( df, commits )

        self.assertEqual( summary[ "total_commits" ], 2, "SILENT UNDERCOUNT: a commit was overwritten" )
        self.assertEqual( summary[ "total_added"   ], 10 )

    def test_colliding_basenames_are_qualified_by_parent( self ):
        a, b = self._dup_repos()
        df, commits, *_ = _analyze( [ a, b ] )
        self.assertEqual(
            sorted( g._build_summary( df, commits )[ "repos" ] ),
            [ "groupA/samename", "groupB/samename" ],
        )

    def test_unique_basenames_stay_bare( self ):
        """No gratuitous qualification when there is no collision."""
        names = g._resolve_repo_names( [ "/x/lupin", "/y/cosa" ] )
        self.assertEqual( names, { "/x/lupin": "lupin", "/y/cosa": "cosa" } )

    def test_trailing_separator_tolerated( self ):
        names = g._resolve_repo_names( [ "/x/lupin/" ] )
        self.assertEqual( names, { "/x/lupin/": "lupin" } )


# ─────────────────────────────────────────────────────────────────────────────
# Aggregation + formatters + paths
# ─────────────────────────────────────────────────────────────────────────────

class TestAggregation( unittest.TestCase ):

    def _frame( self ):
        df = pd.DataFrame([
            { "date": "2026-07-10", "repo": "alpha", "file_type": "python",   "added": 100, "deleted": 10, "files_touched": 2, "repo_date_commits": 1 },
            { "date": "2026-07-10", "repo": "alpha", "file_type": "markdown", "added":  50, "deleted":  5, "files_touched": 1, "repo_date_commits": 1 },
            { "date": "2026-07-10", "repo": "beta",  "file_type": "python",   "added":  20, "deleted":  2, "files_touched": 1, "repo_date_commits": 2 },
            { "date": "2026-07-11", "repo": "alpha", "file_type": "python",   "added": 200, "deleted": 20, "files_touched": 3, "repo_date_commits": 3 },
        ], columns=g.CSV_COLUMNS )
        commits = {
            ( "alpha", "2026-07-10" ): 1,
            ( "beta",  "2026-07-10" ): 2,
            ( "alpha", "2026-07-11" ): 3,
        }
        return df, commits

    def test_aggregated_daily( self ):
        df, commits = self._frame()
        daily = g._build_aggregated_daily( df, commits )

        self.assertEqual( set( daily ), { "2026-07-10", "2026-07-11" } )
        self.assertEqual( daily[ "2026-07-10" ][ "added"   ], 170 )
        # 1 (alpha) + 2 (beta) = 3 — NOT the row sum (1+1+2 = 4).
        self.assertEqual( daily[ "2026-07-10" ][ "commits" ], 3 )
        self.assertEqual( len( daily[ "2026-07-10" ][ "by_repo" ] ), 2 )
        self.assertEqual( daily[ "2026-07-10" ][ "by_repo"      ][ 0 ][ "repo"      ], "alpha"  )
        self.assertEqual( daily[ "2026-07-10" ][ "by_file_type" ][ 0 ][ "file_type" ], "python" )

    def test_aggregated_daily_missing_commit_key_defaults_zero( self ):
        df, _ = self._frame()
        daily = g._build_aggregated_daily( df, {} )
        self.assertEqual( daily[ "2026-07-10" ][ "commits" ], 0 )

    def test_summary_totals( self ):
        df, commits = self._frame()
        s = g._build_summary( df, commits )

        self.assertEqual( s[ "total_added"   ], 370 )
        self.assertEqual( s[ "total_deleted" ], 37  )
        self.assertEqual( s[ "net"           ], 333 )
        self.assertEqual( s[ "total_commits" ], 6   )   # 1 + 2 + 3
        self.assertEqual( s[ "total_days"    ], 2   )
        self.assertEqual( s[ "repos"         ], [ "alpha", "beta" ] )

    def test_summary_empty_frame( self ):
        s = g._build_summary( pd.DataFrame( columns=g.CSV_COLUMNS ), {} )
        self.assertEqual( s[ "total_added"   ], 0 )
        self.assertEqual( s[ "total_commits" ], 0 )
        self.assertEqual( s[ "repos"         ], [] )


class TestFormatters( unittest.TestCase ):

    def _data( self ):
        daily = {
            "2026-07-10": {
                "added": 150, "deleted": 15, "files_touched": 3, "commits": 2,
                "by_repo":      [ { "repo": "alpha", "added": 150, "deleted": 15, "files_touched": 3, "commits": 2 } ],
                "by_file_type": [ { "file_type": "python", "added": 150, "deleted": 15, "files_touched": 3 } ],
            }
        }
        summary = {
            "total_added": 150, "total_deleted": 15, "total_files": 3,
            "total_commits": 2, "total_days": 1, "net": 135, "repos": [ "alpha" ],
        }
        return daily, summary

    def test_console_no_data( self ):
        self.assertIn( "No commits in range", g._format_console( {}, { "repos": [] }, None, None ) )

    def test_console_with_data( self ):
        daily, summary = self._data()
        text = g._format_console( daily, summary, "2026-07-08", "2026-07-14" )
        self.assertIn( "Cross-Repo Daily LoC Delta", text )
        self.assertIn( "alpha", text )
        self.assertIn( "+135", text )
        self.assertIn( "2 commits", text )

    def test_console_open_window( self ):
        daily, summary = self._data()
        self.assertIn( "all .. all", g._format_console( daily, summary, None, None ) )

    def test_json_shape( self ):
        daily, summary = self._data()
        parsed = json.loads( g._format_json( daily, summary, "2026-07-08", "2026-07-14" ) )
        self.assertEqual( parsed[ "since" ], "2026-07-08" )
        self.assertEqual( parsed[ "repos" ], [ "alpha" ] )
        self.assertEqual( parsed[ "summary" ][ "net" ], 135 )
        self.assertNotIn( "repos", parsed[ "summary" ] )
        self.assertEqual( len( parsed[ "days" ] ), 1 )
        self.assertIn( "by_repo", parsed[ "days" ][ 0 ] )


class TestDefaultPath( unittest.TestCase ):

    def test_csv_path( self ):
        p = g._default_path( "/tmp/x", "csv", "2026-07-08", "2026-07-14" )
        self.assertTrue( p.endswith( "io/loc-delta-global/global-2026-07-08_to_2026-07-14-loc-delta.csv" ) )

    def test_png_path( self ):
        p = g._default_path( "/tmp/x", "png", "2026-07-08", "2026-07-14" )
        self.assertTrue( p.endswith( "-plot.png" ) )

    def test_defaults_when_bounds_absent( self ):
        self.assertIn( "global-start_to_", g._default_path( "/tmp/x", "csv", None, None ) )


class TestParser( unittest.TestCase ):

    def test_repos_required( self ):
        with self.assertRaises( SystemExit ):
            g.create_parser().parse_args( [] )

    def test_defaults( self ):
        args = g.create_parser().parse_args( [ "--repos", "/tmp/a" ] )
        self.assertEqual( args.output, "console" )
        self.assertFalse( args.head_only )
        self.assertFalse( args.include_merges )
        self.assertFalse( args.plot )


# ─────────────────────────────────────────────────────────────────────────────
# main() end-to-end
# ─────────────────────────────────────────────────────────────────────────────

class TestMain( _GitRepoFixtureMixin, unittest.TestCase ):

    def _two_repos( self ):
        a = self.init_repo( "alpha" )
        self.commit( a, { "a.py":  self.lines( "a", 10 ) }, "a1", date="2026-07-10T09:00:00" )
        self.commit( a, { "a2.py": self.lines( "a",  5 ) }, "a2", date="2026-07-11T09:00:00" )
        b = self.init_repo( "beta" )
        self.commit( b, { "b.py":  self.lines( "b", 20 ) }, "b1", date="2026-07-10T09:00:00" )
        return a, b

    def _run( self, *argv ):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout( out ), redirect_stderr( err ):
            code = g.main( argv=list( argv ) )
        return code, out.getvalue(), err.getvalue()

    def test_json_end_to_end( self ):
        a, b = self._two_repos()
        code, out, err = self._run( "--repos", a, b, "--since", "2026-07-09", "--until", "2026-07-12", "--output", "json" )
        self.assertEqual( code, 0 )
        parsed = json.loads( out )
        self.assertEqual( parsed[ "summary" ][ "total_added"   ], 35 )
        self.assertEqual( parsed[ "summary" ][ "total_commits" ], 3  )
        self.assertEqual( parsed[ "summary" ][ "total_days"    ], 2  )

    def test_json_save_output( self ):
        a, b   = self._two_repos()
        target = os.path.join( self.workdir, "out.json" )
        code, out, err = self._run( "--repos", a, b, "--since", "2026-07-09", "--until", "2026-07-12",
                                    "--output", "json", "--save-output", target )
        self.assertEqual( code, 0 )
        with open( target ) as f:
            self.assertEqual( json.load( f )[ "summary" ][ "total_added" ], 35 )

    def test_console_to_stdout( self ):
        a, b = self._two_repos()
        code, out, err = self._run( "--repos", a, b, "--since", "2026-07-09", "--until", "2026-07-12" )
        self.assertEqual( code, 0 )
        self.assertIn( "Cross-Repo Daily LoC Delta", out )
        self.assertIn( "alpha", out )

    def test_console_save_output( self ):
        a, b   = self._two_repos()
        target = os.path.join( self.workdir, "out.txt" )
        code, out, err = self._run( "--repos", a, b, "--since", "2026-07-09", "--until", "2026-07-12",
                                    "--save-output", target )
        self.assertEqual( code, 0 )
        with open( target ) as f:
            self.assertIn( "Cross-Repo Daily LoC Delta", f.read() )

    def test_console_lists_empty_repos( self ):
        a, _  = self._two_repos()
        quiet = self.init_repo( "quiet" )
        self.commit( quiet, { "q.py": "x\n" }, "old", date="2020-01-01T09:00:00" )

        code, out, err = self._run( "--repos", a, quiet, "--since", "2026-07-09", "--until", "2026-07-12" )
        self.assertEqual( code, 0 )
        self.assertIn( "Repos with no commits in window", out )
        self.assertIn( "quiet", out )

    def test_console_lists_skipped_repos( self ):
        a, _  = self._two_repos()
        plain = self.not_a_repo()
        code, out, err = self._run( "--repos", a, plain, "--since", "2026-07-09", "--until", "2026-07-12" )
        self.assertEqual( code, 0 )
        self.assertIn( "Skipped (not a git repo)", out )

    def test_console_surfaces_coverage_warnings( self ):
        repo = self.init_repo( "binary" )
        self.commit( repo, { "a.py": self.lines( "x", 3 ) }, "text" )
        self.commit_binary( repo, "img/x.png", "binary" )

        code, out, err = self._run( "--repos", repo, "--since", "2026-07-09", "--until", "2026-07-12" )
        self.assertEqual( code, 0 )
        self.assertIn( "COVERAGE WARNINGS", out )
        self.assertIn( "COVERAGE MISMATCH", out )

    def test_csv_output_default_path_creates_parent( self ):
        a, b = self._two_repos()
        cwd  = self.plain_dir( "cwd" )
        with patch( "os.getcwd", return_value=cwd ):
            code, out, err = self._run( "--repos", a, b, "--since", "2026-07-09", "--until", "2026-07-12",
                                        "--output", "csv" )
        self.assertEqual( code, 0 )
        written = os.path.join( cwd, "io", "loc-delta-global",
                                "global-2026-07-09_to_2026-07-12-loc-delta.csv" )
        self.assertTrue( os.path.isfile( written ) )
        self.assertEqual( list( pd.read_csv( written ).columns ), g.CSV_COLUMNS )

    def test_csv_output_save_output_renamed_column( self ):
        a, b   = self._two_repos()
        target = os.path.join( self.workdir, "out.csv" )
        code, out, err = self._run( "--repos", a, b, "--since", "2026-07-09", "--until", "2026-07-12",
                                    "--output", "csv", "--save-output", target )
        self.assertEqual( code, 0 )
        df = pd.read_csv( target )
        self.assertIn(    "repo_date_commits", df.columns )
        self.assertNotIn( "commits",           df.columns )

    def test_today_default_applied( self ):
        a, _ = self._two_repos()
        code, out, err = self._run( "--repos", a, "--output", "json", "--verbose" )
        self.assertEqual( code, 0 )
        self.assertIn( "Today-default applied", err )

    def test_head_only_flag( self ):
        repo = self.init_repo( "ho" )
        self.commit( repo, { "a.py": self.lines( "a", 3 ) }, "base" )
        self._git( repo, "checkout", "-q", "-b", "lane" )
        self.commit( repo, { "b.py": self.lines( "b", 4 ) }, "lane" )
        self._git( repo, "checkout", "-q", "main" )

        code, out, err = self._run( "--repos", repo, "--since", "2026-07-09", "--until", "2026-07-12",
                                    "--head-only", "--output", "json" )
        self.assertEqual( code, 0 )
        # HEAD is main → the lane commit is NOT reachable
        self.assertEqual( json.loads( out )[ "summary" ][ "total_added" ], 3 )

    def test_include_merges_flag( self ):
        a, _ = self._two_repos()
        code, out, err = self._run( "--repos", a, "--since", "2026-07-09", "--until", "2026-07-12",
                                    "--include-merges", "--output", "json" )
        self.assertEqual( code, 0 )

    def test_no_git_repos_returns_error( self ):
        code, out, err = self._run( "--repos", self.not_a_repo(), "--since", "2026-07-09", "--until", "2026-07-12" )
        self.assertEqual( code, g.EXIT_ERROR )
        self.assertIn( "no git repositories", err )

    def test_analysis_failure_returns_error( self ):
        a, _ = self._two_repos()
        with patch.object( g, "_analyze_repos", side_effect=GitLocDeltaError( "boom" ) ):
            code, out, err = self._run( "--repos", a, "--since", "2026-07-09", "--until", "2026-07-12" )
        self.assertEqual( code, g.EXIT_ERROR )
        self.assertIn( "boom", err )

    def test_analysis_failure_with_debug_prints_traceback( self ):
        a, _ = self._two_repos()
        with patch.object( g, "_analyze_repos", side_effect=GitLocDeltaError( "boom" ) ):
            code, out, err = self._run( "--repos", a, "--since", "2026-07-09", "--until", "2026-07-12", "--debug" )
        self.assertEqual( code, g.EXIT_ERROR )
        self.assertIn( "GitLocDeltaError", err )

    def test_plot_success( self ):
        a, b   = self._two_repos()   # spans 2 dates
        target = os.path.join( self.workdir, "plot.png" )
        code, out, err = self._run( "--repos", a, b, "--since", "2026-07-09", "--until", "2026-07-12",
                                    "--output", "json", "--plot", "--plot-output", target )
        self.assertEqual( code, 0 )
        self.assertTrue( os.path.isfile( target ) )
        self.assertIn( "Plot written to", out )

    def test_plot_default_path( self ):
        a, b = self._two_repos()
        cwd  = self.plain_dir( "cwd2" )
        with patch( "os.getcwd", return_value=cwd ):
            code, out, err = self._run( "--repos", a, b, "--since", "2026-07-09", "--until", "2026-07-12",
                                        "--output", "json", "--plot" )
        self.assertEqual( code, 0 )
        self.assertIn( "Plot written to", out )

    def test_plot_insufficient_days_skipped( self ):
        b = self.init_repo( "single_day" )
        self.commit( b, { "b.py": self.lines( "b", 5 ) }, "one day" )
        code, out, err = self._run( "--repos", b, "--since", "2026-07-09", "--until", "2026-07-12",
                                    "--output", "json", "--plot" )
        self.assertEqual( code, 0 )
        self.assertIn( "--plot skipped", err )

    def test_plot_failure_returns_error( self ):
        a, b = self._two_repos()
        with patch.object( g, "plot_summary", side_effect=RuntimeError( "no canvas" ) ):
            code, out, err = self._run( "--repos", a, b, "--since", "2026-07-09", "--until", "2026-07-12",
                                        "--output", "json", "--plot" )
        self.assertEqual( code, g.EXIT_ERROR )
        self.assertIn( "Plot generation failed", err )

    def test_plot_failure_with_debug_prints_traceback( self ):
        a, b = self._two_repos()
        with patch.object( g, "plot_summary", side_effect=RuntimeError( "no canvas" ) ):
            code, out, err = self._run( "--repos", a, b, "--since", "2026-07-09", "--until", "2026-07-12",
                                        "--output", "json", "--plot", "--debug" )
        self.assertEqual( code, g.EXIT_ERROR )
        self.assertIn( "RuntimeError", err )

    def test_out_of_contract_output_falls_through_to_exit_ok( self ):
        """Defensive else-branch: argparse blocks this, so inject the namespace directly."""
        a, _ = self._two_repos()
        ns = argparse.Namespace(
            repos=[ a ], since="2026-07-09", until="2026-07-12", head_only=False,
            include_merges=False, output="bogus", save_output=None, plot=False,
            plot_output=None, verbose=False, debug=False,
        )
        fake_parser = MagicMock()
        fake_parser.parse_args.return_value = ns
        with patch.object( g, "create_parser", return_value=fake_parser ):
            out, err = io.StringIO(), io.StringIO()
            with redirect_stdout( out ), redirect_stderr( err ):
                code = g.main( argv=[] )
        self.assertEqual( code, g.EXIT_OK )


if __name__ == "__main__":
    unittest.main()
