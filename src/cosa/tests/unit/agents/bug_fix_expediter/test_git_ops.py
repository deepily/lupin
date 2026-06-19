"""
Unit tests for cosa.agents.bug_fix_expediter.git_ops.

GitOps is an async wrapper over the git + gh CLIs. Every method returns a dict
and never raises. Coverage matrix:

  _run_cmd        : debug-print on/off · success (rc 0 / rc 1) · TimeoutError
                    (kill+wait+timeout dict) · generic Exception (error dict)
  get_current_branch : success → stdout · failure → ""
  commit_on_branch   : empty files · add-fail · commit-fail · hash-fail · success
  create_fix_branch  : empty slug · checkout-fail · success
  commit_and_push    : commit-fail passthrough · push-fail · success
  create_pr          : gh-detect (debug) · gh-missing · gh present+cmd-fail · success ·
                       cached _gh_available skips re-detection
  checkout_branch    : fail · success

All subprocess/CLI boundaries mocked (asyncio.create_subprocess_exec,
asyncio.wait_for, shutil.which) — no real git/gh/subprocess/fs. _run_git is
injected at the method level for the composition tests. quick_smoke_test +
__main__ excluded via pyproject coverage config.

Created 2026-05-31 by Mr. Radio 🦉 (CoSA coverage campaign, agents Tier-2, expediter lane).
"""

import asyncio
import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import AsyncMock, MagicMock, patch

import cosa.agents.bug_fix_expediter.git_ops as git_ops_mod
from cosa.agents.bug_fix_expediter.git_ops import GitOps


def _run( coro ):
    return asyncio.run( coro )


def _ok( **over ):
    d = { "success": True, "stdout": "", "stderr": "", "returncode": 0 }
    d.update( over )
    return d


def _fail( **over ):
    d = { "success": False, "stdout": "", "stderr": "boom", "returncode": 1 }
    d.update( over )
    return d


def _fake_proc( returncode=0, stdout=b"out\n", stderr=b"err\n" ):
    proc = MagicMock()
    proc.returncode = returncode
    proc.communicate = AsyncMock( return_value=( stdout, stderr ) )
    proc.kill        = MagicMock()
    proc.wait        = AsyncMock( return_value=None )
    return proc


# ===========================================================================
# _run_cmd / _run_git low-level
# ===========================================================================
class TestRunCmd( unittest.TestCase ):

    def test_success_returncode_zero( self ):
        proc = _fake_proc( returncode=0, stdout=b"  main\n", stderr=b"" )
        go = GitOps( cwd="/tmp/x", debug=False )
        with patch.object( git_ops_mod.asyncio, "create_subprocess_exec",
                           AsyncMock( return_value=proc ) ):
            out = _run( go._run_git( "rev-parse", "HEAD" ) )
        self.assertTrue( out[ "success" ] )
        self.assertEqual( out[ "stdout" ], "main" )      # decoded + stripped
        self.assertEqual( out[ "returncode" ], 0 )

    def test_nonzero_returncode_is_failure( self ):
        proc = _fake_proc( returncode=128, stdout=b"", stderr=b"fatal: bad\n" )
        go = GitOps()
        with patch.object( git_ops_mod.asyncio, "create_subprocess_exec",
                           AsyncMock( return_value=proc ) ):
            out = _run( go._run_cmd( "git", "status" ) )
        self.assertFalse( out[ "success" ] )
        self.assertEqual( out[ "stderr" ], "fatal: bad" )
        self.assertEqual( out[ "returncode" ], 128 )

    def test_debug_prints_command( self ):
        proc = _fake_proc()
        go = GitOps( debug=True )
        buf = io.StringIO()
        with patch.object( git_ops_mod.asyncio, "create_subprocess_exec",
                           AsyncMock( return_value=proc ) ):
            with redirect_stdout( buf ):
                _run( go._run_cmd( "git", "log", "--oneline" ) )
        self.assertIn( "[GitOps] git log --oneline", buf.getvalue() )

    def test_timeout_kills_process_and_returns_timeout_dict( self ):
        proc = _fake_proc()
        go = GitOps( timeout_secs=7 )

        async def _timeout( awaitable, timeout=None ):
            # Close the proc.communicate() coroutine we're handed so it isn't
            # left un-awaited (clean run), then simulate the timeout.
            if hasattr( awaitable, "close" ):
                awaitable.close()
            raise asyncio.TimeoutError

        with patch.object( git_ops_mod.asyncio, "create_subprocess_exec",
                           AsyncMock( return_value=proc ) ), \
             patch.object( git_ops_mod.asyncio, "wait_for", _timeout ):
            out = _run( go._run_cmd( "git", "fetch" ) )
        self.assertFalse( out[ "success" ] )
        self.assertEqual( out[ "returncode" ], -1 )
        self.assertIn( "timeout after 7s", out[ "stderr" ] )
        proc.kill.assert_called_once_with()
        proc.wait.assert_awaited_once_with()

    def test_generic_exception_returns_error_dict( self ):
        go = GitOps()
        with patch.object( git_ops_mod.asyncio, "create_subprocess_exec",
                           AsyncMock( side_effect=OSError( "no git binary" ) ) ):
            out = _run( go._run_cmd( "git", "status" ) )
        self.assertFalse( out[ "success" ] )
        self.assertEqual( out[ "returncode" ], -1 )
        self.assertEqual( out[ "stderr" ], "no git binary" )


# ===========================================================================
# get_current_branch
# ===========================================================================
class TestGetCurrentBranch( unittest.TestCase ):

    def test_success_returns_branch( self ):
        go = GitOps()
        go._run_git = AsyncMock( return_value=_ok( stdout="wip-branch" ) )
        self.assertEqual( _run( go.get_current_branch() ), "wip-branch" )

    def test_failure_returns_empty_string( self ):
        go = GitOps()
        go._run_git = AsyncMock( return_value=_fail() )
        self.assertEqual( _run( go.get_current_branch() ), "" )


# ===========================================================================
# commit_on_branch
# ===========================================================================
class TestCommitOnBranch( unittest.TestCase ):

    def test_empty_files_is_noop( self ):
        go = GitOps()
        go._run_git = AsyncMock()
        out = _run( go.commit_on_branch( [], "msg" ) )
        self.assertFalse( out[ "success" ] )
        self.assertIsNone( out[ "commit_hash" ] )
        self.assertEqual( out[ "error" ], "no files to commit" )
        go._run_git.assert_not_called()

    def test_add_failure( self ):
        go = GitOps()
        go._run_git = AsyncMock( side_effect=[ _fail( stderr="add boom" ) ] )
        out = _run( go.commit_on_branch( [ "a.py" ], "msg" ) )
        self.assertFalse( out[ "success" ] )
        self.assertIn( "git add failed: add boom", out[ "error" ] )

    def test_commit_failure( self ):
        go = GitOps()
        go._run_git = AsyncMock( side_effect=[ _ok(), _fail( stderr="commit boom" ) ] )
        out = _run( go.commit_on_branch( [ "a.py" ], "msg" ) )
        self.assertFalse( out[ "success" ] )
        self.assertIn( "git commit failed: commit boom", out[ "error" ] )

    def test_hash_lookup_failure( self ):
        go = GitOps()
        go._run_git = AsyncMock( side_effect=[ _ok(), _ok(), _fail() ] )
        out = _run( go.commit_on_branch( [ "a.py" ], "msg" ) )
        self.assertFalse( out[ "success" ] )
        self.assertEqual( out[ "error" ], "commit succeeded but hash lookup failed" )

    def test_full_success_returns_hash( self ):
        go = GitOps()
        go._run_git = AsyncMock( side_effect=[ _ok(), _ok(), _ok( stdout="abc1234" ) ] )
        out = _run( go.commit_on_branch( [ "a.py", "b.py" ], "msg" ) )
        self.assertTrue( out[ "success" ] )
        self.assertEqual( out[ "commit_hash" ], "abc1234" )
        self.assertIsNone( out[ "error" ] )


# ===========================================================================
# create_fix_branch
# ===========================================================================
class TestCreateFixBranch( unittest.TestCase ):

    def test_empty_slug( self ):
        go = GitOps()
        go._run_git = AsyncMock()
        out = _run( go.create_fix_branch( "" ) )
        self.assertFalse( out[ "success" ] )
        self.assertEqual( out[ "error" ], "empty slug" )
        go._run_git.assert_not_called()

    def test_checkout_failure( self ):
        go = GitOps()
        go._run_git = AsyncMock( return_value=_fail( stderr="exists" ) )
        out = _run( go.create_fix_branch( "fix/x" ) )
        self.assertFalse( out[ "success" ] )
        self.assertIn( "git checkout -b failed: exists", out[ "error" ] )

    def test_success( self ):
        go = GitOps()
        go._run_git = AsyncMock( return_value=_ok() )
        out = _run( go.create_fix_branch( "fix/x" ) )
        self.assertTrue( out[ "success" ] )
        self.assertEqual( out[ "branch_name" ], "fix/x" )
        self.assertIsNone( out[ "error" ] )


# ===========================================================================
# commit_and_push
# ===========================================================================
class TestCommitAndPush( unittest.TestCase ):

    def test_commit_failure_passes_through( self ):
        go = GitOps()
        failed = { "success": False, "commit_hash": None, "error": "no files to commit" }
        go.commit_on_branch = AsyncMock( return_value=failed )
        go._run_git = AsyncMock()
        out = _run( go.commit_and_push( "fix/x", [], "msg" ) )
        self.assertIs( out, failed )                     # returned verbatim
        go._run_git.assert_not_called()                 # never reaches push

    def test_push_failure( self ):
        go = GitOps()
        go.commit_on_branch = AsyncMock(
            return_value={ "success": True, "commit_hash": "abc1234", "error": None } )
        go._run_git = AsyncMock( return_value=_fail( stderr="rejected" ) )
        out = _run( go.commit_and_push( "fix/x", [ "a.py" ], "msg" ) )
        self.assertFalse( out[ "success" ] )
        self.assertEqual( out[ "commit_hash" ], "abc1234" )
        self.assertIn( "git push failed: rejected", out[ "error" ] )

    def test_success( self ):
        go = GitOps()
        go.commit_on_branch = AsyncMock(
            return_value={ "success": True, "commit_hash": "abc1234", "error": None } )
        go._run_git = AsyncMock( return_value=_ok() )
        out = _run( go.commit_and_push( "fix/x", [ "a.py" ], "msg" ) )
        self.assertTrue( out[ "success" ] )
        self.assertEqual( out[ "commit_hash" ], "abc1234" )
        self.assertIsNone( out[ "error" ] )


# ===========================================================================
# create_pr
# ===========================================================================
class TestCreatePr( unittest.TestCase ):

    def test_gh_missing_returns_unavailable_and_debug_prints( self ):
        go = GitOps( debug=True )
        buf = io.StringIO()
        with patch.object( git_ops_mod.shutil, "which", return_value=None ):
            with redirect_stdout( buf ):
                out = _run( go.create_pr( "fix/x", "title", "body" ) )
        self.assertFalse( out[ "success" ] )
        self.assertEqual( out[ "error" ], "gh CLI not available" )
        self.assertFalse( go._gh_available )             # cached False
        self.assertIn( "[GitOps] gh CLI available: False", buf.getvalue() )

    def test_gh_present_command_failure( self ):
        go = GitOps()
        go._run_cmd = AsyncMock( return_value=_fail( stderr="auth required" ) )
        with patch.object( git_ops_mod.shutil, "which", return_value="/usr/bin/gh" ):
            out = _run( go.create_pr( "fix/x", "title", "body" ) )
        self.assertFalse( out[ "success" ] )
        self.assertIn( "gh pr create failed: auth required", out[ "error" ] )
        self.assertTrue( go._gh_available )

    def test_gh_present_success_returns_pr_url( self ):
        go = GitOps()
        go._run_cmd = AsyncMock( return_value=_ok( stdout="https://github.com/o/r/pull/7" ) )
        with patch.object( git_ops_mod.shutil, "which", return_value="/usr/bin/gh" ):
            out = _run( go.create_pr( "fix/x", "title", "body" ) )
        self.assertTrue( out[ "success" ] )
        self.assertEqual( out[ "pr_url" ], "https://github.com/o/r/pull/7" )
        self.assertIsNone( out[ "error" ] )
        go._run_cmd.assert_awaited_once_with(
            "gh", "pr", "create", "--title", "title", "--body", "body", "--head", "fix/x",
        )

    def test_cached_gh_availability_skips_redetection( self ):
        go = GitOps()
        go._gh_available = True                          # pre-cached → which not called
        go._run_cmd = AsyncMock( return_value=_ok( stdout="url" ) )
        with patch.object( git_ops_mod.shutil, "which", return_value=None ) as which:
            out = _run( go.create_pr( "fix/x", "title", "body" ) )
        self.assertTrue( out[ "success" ] )
        which.assert_not_called()                        # detection skipped


# ===========================================================================
# checkout_branch
# ===========================================================================
class TestCheckoutBranch( unittest.TestCase ):

    def test_failure( self ):
        go = GitOps()
        go._run_git = AsyncMock( return_value=_fail( stderr="no such branch" ) )
        out = _run( go.checkout_branch( "main" ) )
        self.assertFalse( out[ "success" ] )
        self.assertIn( "git checkout failed: no such branch", out[ "error" ] )

    def test_success( self ):
        go = GitOps()
        go._run_git = AsyncMock( return_value=_ok() )
        out = _run( go.checkout_branch( "main" ) )
        self.assertTrue( out[ "success" ] )
        self.assertIsNone( out[ "error" ] )


class TestConstruction( unittest.TestCase ):

    def test_defaults( self ):
        go = GitOps()
        self.assertIsNone( go.cwd )
        self.assertEqual( go.timeout_secs, 30 )
        self.assertFalse( go.debug )
        self.assertIsNone( go._gh_available )


if __name__ == "__main__":
    unittest.main()
