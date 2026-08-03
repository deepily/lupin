"""
Unit tests for `cosa.repo.git_loc_delta.coverage_guard`.

The guard exists because the roll-up spent weeks being self-consistent and
confidently wrong (bugs bbff93a3 + 37a8beeb). It asks git a SECOND, INDEPENDENT
question — "how many commits are in this window?" — and refuses to let a silent
coverage gap pass as a clean number.

These tests use real git repos: a guard tested against mocks would share the very
blind spot it exists to detect.
"""

import os
import subprocess
import tempfile
import unittest
from unittest.mock import patch, MagicMock

from cosa.repo.git_loc_delta.coverage_guard import reconcile_coverage, _rev_list_shas
from cosa.repo.git_loc_delta.exceptions     import GitCommandError


class _RepoMixin:

    def setUp( self ):
        self.workdir = tempfile.mkdtemp( prefix="coverage_guard_test_" )
        self.addCleanup( self._cleanup )
        self.repo = os.path.join( self.workdir, "repo" )
        os.makedirs( self.repo )
        self._git( "init", "-q", "-b", "main" )
        self._git( "config", "user.email", "test@local" )
        self._git( "config", "user.name",  "Test" )

    def _cleanup( self ):
        import shutil
        shutil.rmtree( self.workdir, ignore_errors=True )

    def _git( self, *cmd, date="2026-07-10T12:00:00" ):
        env = { **os.environ, "GIT_AUTHOR_DATE": date, "GIT_COMMITTER_DATE": date }
        subprocess.run( [ "git", *cmd ], cwd=self.repo, check=True, capture_output=True, env=env )

    def commit_text( self, name="a.py", body="x\n", date="2026-07-10T12:00:00" ):
        with open( os.path.join( self.repo, name ), "w" ) as f:
            f.write( body )
        self._git( "add", "-A", date=date )
        self._git( "commit", "-q", "-m", f"add {name}", date=date )
        return subprocess.run(
            [ "git", "rev-parse", "HEAD" ], cwd=self.repo, capture_output=True, text=True
        ).stdout.strip()

    def commit_binary( self, name="img.png", date="2026-07-10T12:00:00" ):
        with open( os.path.join( self.repo, name ), "wb" ) as f:
            f.write( bytes( range( 256 ) ) * 4 )
        self._git( "add", "-A", date=date )
        self._git( "commit", "-q", "-m", f"add {name}", date=date )
        return subprocess.run(
            [ "git", "rev-parse", "HEAD" ], cwd=self.repo, capture_output=True, text=True
        ).stdout.strip()


class TestReconcileCoverage( _RepoMixin, unittest.TestCase ):

    def test_clean_reconciliation( self ):
        sha = self.commit_text()
        report = reconcile_coverage(
            repo_path    = self.repo,
            counted_shas = { sha },
            since        = "2026-07-09",
            until        = "2026-07-12",
            repo_name    = "repo",
        )
        self.assertTrue( report[ "reconciled" ] )
        self.assertEqual( report[ "expected" ], 1 )
        self.assertEqual( report[ "counted"  ], 1 )
        self.assertEqual( report[ "uncounted"  ], [] )
        self.assertEqual( report[ "unexpected" ], [] )
        self.assertIsNone( report[ "warning" ] )
        self.assertEqual( report[ "repo" ], "repo" )

    def test_uncounted_commit_is_named( self ):
        """A binary-only commit yields no countable rows — surfaced, not inferred."""
        text_sha   = self.commit_text()
        binary_sha = self.commit_binary()

        report = reconcile_coverage(
            repo_path    = self.repo,
            counted_shas = { text_sha },       # the binary commit produced no rows
            since        = "2026-07-09",
            until        = "2026-07-12",
            repo_name    = "repo",
        )
        self.assertFalse( report[ "reconciled" ] )
        self.assertEqual( report[ "expected" ], 2 )
        self.assertEqual( report[ "counted"  ], 1 )
        self.assertEqual( report[ "uncounted" ], [ binary_sha ] )
        self.assertIn( "COVERAGE MISMATCH", report[ "warning" ] )
        self.assertIn( binary_sha[ :8 ],     report[ "warning" ] )
        self.assertIn( "binary-only or empty", report[ "warning" ] )
        self.assertIn( "bbff93a3",            report[ "warning" ] )

    def test_unexpected_commit_is_flagged_as_never_benign( self ):
        """We counted a commit git says is out of window — the date-basis bug class."""
        sha = self.commit_text()
        report = reconcile_coverage(
            repo_path    = self.repo,
            counted_shas = { sha, "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef" },
            since        = "2026-07-09",
            until        = "2026-07-12",
            repo_name    = "repo",
        )
        self.assertFalse( report[ "reconciled" ] )
        self.assertEqual( report[ "unexpected" ], [ "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef" ] )
        self.assertIn( "OUTSIDE git's window",  report[ "warning" ] )
        self.assertIn( "committer vs author",   report[ "warning" ] )
        self.assertIn( "never benign",          report[ "warning" ] )

    def test_many_uncounted_are_truncated_with_more_marker( self ):
        counted = set()
        for i in range( 12 ):
            self.commit_binary( name=f"img{i}.png" )
        report = reconcile_coverage(
            repo_path    = self.repo,
            counted_shas = counted,
            since        = "2026-07-09",
            until        = "2026-07-12",
            repo_name    = "repo",
        )
        self.assertEqual( report[ "expected" ], 12 )
        self.assertIn( "(+2 more)", report[ "warning" ] )

    def test_many_unexpected_are_truncated_with_more_marker( self ):
        self.commit_text()
        fakes = { f"{i:040x}" for i in range( 12 ) }
        report = reconcile_coverage(
            repo_path    = self.repo,
            counted_shas = fakes,
            since        = "2026-07-09",
            until        = "2026-07-12",
        )
        self.assertIn( "(+2 more)", report[ "warning" ] )

    def test_repo_name_defaults_to_path( self ):
        self.commit_text()
        report = reconcile_coverage(
            repo_path    = self.repo,
            counted_shas = set(),
            since        = "2026-07-09",
            until        = "2026-07-12",
        )
        self.assertEqual( report[ "repo" ], self.repo )

    def test_debug_emits_line( self ):
        import io
        from contextlib import redirect_stdout
        sha = self.commit_text()
        buf = io.StringIO()
        with redirect_stdout( buf ):
            reconcile_coverage(
                repo_path    = self.repo,
                counted_shas = { sha },
                since        = "2026-07-09",
                until        = "2026-07-12",
                debug        = True,
            )
        self.assertIn( "[coverage_guard]", buf.getvalue() )

    def test_all_branches_sees_sibling_branch_commits( self ):
        base = self.commit_text( "base.py" )
        self._git( "checkout", "-q", "-b", "lane" )
        lane = self.commit_text( "lane.py" )
        self._git( "checkout", "-q", "main" )

        head_only = _rev_list_shas( self.repo, "2026-07-09", "2026-07-12", None, False, False, 30 )
        all_local = _rev_list_shas( self.repo, "2026-07-09", "2026-07-12", None, True,  False, 30 )

        self.assertEqual( head_only, { base } )
        self.assertEqual( all_local, { base, lane } )

    def test_rev_range_path( self ):
        base = self.commit_text( "base.py" )
        self._git( "checkout", "-q", "-b", "feature" )
        feat = self.commit_text( "feat.py" )

        shas = _rev_list_shas( self.repo, None, None, "main..feature", False, False, 30 )
        self.assertEqual( shas, { feat } )

    def test_include_merges_toggles_no_merges_flag( self ):
        self.commit_text( "a.py" )
        self._git( "checkout", "-q", "-b", "feature" )
        self.commit_text( "b.py" )
        self._git( "checkout", "-q", "main" )
        self.commit_text( "c.py" )
        self._git( "merge", "-q", "--no-ff", "feature", "-m", "merge" )

        without = _rev_list_shas( self.repo, None, None, None, False, False, 30 )
        with_m  = _rev_list_shas( self.repo, None, None, None, False, True,  30 )
        self.assertGreater( len( with_m ), len( without ) )


class TestRevListFailureModes( unittest.TestCase ):
    """Failure translation — mocked, because these are subprocess-layer faults."""

    def test_timeout_raises_git_command_error( self ):
        with patch( "subprocess.run", side_effect=subprocess.TimeoutExpired( cmd="git", timeout=5 ) ):
            with self.assertRaises( GitCommandError ) as ctx:
                _rev_list_shas( "/tmp", None, None, None, False, False, 5 )
        self.assertIn( "timed out", str( ctx.exception ) )

    def test_git_missing_raises_git_command_error( self ):
        with patch( "subprocess.run", side_effect=FileNotFoundError() ):
            with self.assertRaises( GitCommandError ) as ctx:
                _rev_list_shas( "/tmp", None, None, None, False, False, 5 )
        self.assertIn( "Git command not found", str( ctx.exception ) )

    def test_non_zero_return_code_raises( self ):
        fake = MagicMock( returncode=128, stdout="", stderr="fatal: not a git repository" )
        with patch( "subprocess.run", return_value=fake ):
            with self.assertRaises( GitCommandError ) as ctx:
                _rev_list_shas( "/tmp", None, None, None, False, False, 5 )
        self.assertIn( "return code 128", str( ctx.exception ) )

    def test_blank_lines_are_ignored( self ):
        fake = MagicMock( returncode=0, stdout="abc123\n\n  \ndef456\n", stderr="" )
        with patch( "subprocess.run", return_value=fake ):
            shas = _rev_list_shas( "/tmp", None, None, None, False, False, 5 )
        self.assertEqual( shas, { "abc123", "def456" } )


if __name__ == "__main__":
    unittest.main()
