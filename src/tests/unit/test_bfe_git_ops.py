"""
Unit tests for Bug Fix Expediter Phase 5: GitOps async module.

Tests mock asyncio.create_subprocess_exec to validate git command
construction, result parsing, error handling, and gh CLI degradation.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cosa.agents.bug_fix_expediter.git_ops import GitOps


# =============================================================================
# Helpers
# =============================================================================

def _mock_proc( returncode: int = 0, stdout: bytes = b"", stderr: bytes = b"" ):
    """Build a mock subprocess with pre-populated communicate() output."""
    proc = MagicMock()
    proc.returncode = returncode
    proc.communicate = AsyncMock( return_value=( stdout, stderr ) )
    proc.kill = MagicMock()
    proc.wait = AsyncMock()
    return proc


# =============================================================================
# _run_git / _run_cmd
# =============================================================================

def test_run_git_success():
    git_ops = GitOps( debug=False )
    proc = _mock_proc( returncode=0, stdout=b"main\n" )
    with patch( "asyncio.create_subprocess_exec", return_value=proc ):
        result = asyncio.run( git_ops._run_git( "rev-parse", "--abbrev-ref", "HEAD" ) )
    assert result[ "success" ] is True
    assert result[ "returncode" ] == 0
    assert result[ "stdout" ] == "main"
    assert result[ "stderr" ] == ""


def test_run_git_failure():
    git_ops = GitOps( debug=False )
    proc = _mock_proc( returncode=1, stdout=b"", stderr=b"fatal: not a git repository" )
    with patch( "asyncio.create_subprocess_exec", return_value=proc ):
        result = asyncio.run( git_ops._run_git( "status" ) )
    assert result[ "success" ] is False
    assert result[ "returncode" ] == 1
    assert "not a git repository" in result[ "stderr" ]


def test_run_git_exception_handled():
    git_ops = GitOps( debug=False )
    with patch( "asyncio.create_subprocess_exec", side_effect=FileNotFoundError( "git not found" ) ):
        result = asyncio.run( git_ops._run_git( "status" ) )
    assert result[ "success" ] is False
    assert result[ "returncode" ] == -1
    assert "git not found" in result[ "stderr" ]


# =============================================================================
# commit_on_branch
# =============================================================================

def test_commit_on_branch_success():
    git_ops = GitOps( debug=False )
    # add → ok, commit → ok, rev-parse → ok (returns hash)
    procs = [
        _mock_proc( returncode=0 ),                    # git add
        _mock_proc( returncode=0 ),                    # git commit
        _mock_proc( returncode=0, stdout=b"abc123def456" ),  # git rev-parse HEAD
    ]
    with patch( "asyncio.create_subprocess_exec", side_effect=procs ):
        result = asyncio.run( git_ops.commit_on_branch( [ "file1.py", "file2.py" ], "[BFE] Fix bug" ) )
    assert result[ "success" ] is True
    assert result[ "commit_hash" ] == "abc123def456"
    assert result[ "error" ] is None


def test_commit_on_branch_rejects_empty_files():
    git_ops = GitOps( debug=False )
    result = asyncio.run( git_ops.commit_on_branch( [], "test" ) )
    assert result[ "success" ] is False
    assert result[ "commit_hash" ] is None
    assert "no files" in result[ "error" ]


def test_commit_on_branch_add_fails():
    git_ops = GitOps( debug=False )
    proc = _mock_proc( returncode=1, stderr=b"pathspec did not match" )
    with patch( "asyncio.create_subprocess_exec", return_value=proc ):
        result = asyncio.run( git_ops.commit_on_branch( [ "missing.py" ], "test" ) )
    assert result[ "success" ] is False
    assert "git add failed" in result[ "error" ]


# =============================================================================
# create_fix_branch
# =============================================================================

def test_create_fix_branch_success():
    git_ops = GitOps( debug=False )
    proc = _mock_proc( returncode=0 )
    with patch( "asyncio.create_subprocess_exec", return_value=proc ):
        result = asyncio.run( git_ops.create_fix_branch( "fix/2026-04-05-null-pointer" ) )
    assert result[ "success" ] is True
    assert result[ "branch_name" ] == "fix/2026-04-05-null-pointer"
    assert result[ "error" ] is None


def test_create_fix_branch_rejects_empty_slug():
    git_ops = GitOps( debug=False )
    result = asyncio.run( git_ops.create_fix_branch( "" ) )
    assert result[ "success" ] is False
    assert result[ "branch_name" ] is None
    assert "empty slug" in result[ "error" ]


# =============================================================================
# commit_and_push
# =============================================================================

def test_commit_and_push_sequence():
    git_ops = GitOps( debug=False )
    # add → ok, commit → ok, rev-parse → ok (hash), push → ok
    procs = [
        _mock_proc( returncode=0 ),                        # git add
        _mock_proc( returncode=0 ),                        # git commit
        _mock_proc( returncode=0, stdout=b"deadbeef" ),    # git rev-parse
        _mock_proc( returncode=0 ),                        # git push -u origin
    ]
    with patch( "asyncio.create_subprocess_exec", side_effect=procs ):
        result = asyncio.run( git_ops.commit_and_push(
            "fix/2026-04-05-bug", [ "a.py" ], "[BFE] Fix"
        ) )
    assert result[ "success" ] is True
    assert result[ "commit_hash" ] == "deadbeef"
    assert result[ "error" ] is None


def test_commit_and_push_push_fails():
    git_ops = GitOps( debug=False )
    procs = [
        _mock_proc( returncode=0 ),                        # git add
        _mock_proc( returncode=0 ),                        # git commit
        _mock_proc( returncode=0, stdout=b"deadbeef" ),    # git rev-parse
        _mock_proc( returncode=1, stderr=b"auth failure" ), # git push -u origin
    ]
    with patch( "asyncio.create_subprocess_exec", side_effect=procs ):
        result = asyncio.run( git_ops.commit_and_push(
            "fix/test", [ "a.py" ], "[BFE] Fix"
        ) )
    assert result[ "success" ] is False
    assert result[ "commit_hash" ] == "deadbeef"   # commit succeeded
    assert "git push failed" in result[ "error" ]


# =============================================================================
# create_pr
# =============================================================================

def test_create_pr_success():
    git_ops = GitOps( debug=False )
    git_ops._gh_available = True   # pre-cache
    proc = _mock_proc( returncode=0, stdout=b"https://github.com/foo/bar/pull/42" )
    with patch( "asyncio.create_subprocess_exec", return_value=proc ):
        result = asyncio.run( git_ops.create_pr(
            "fix/test", "[BFE] Fix bug", "Automated fix body"
        ) )
    assert result[ "success" ] is True
    assert result[ "pr_url" ] == "https://github.com/foo/bar/pull/42"
    assert result[ "error" ] is None


def test_create_pr_gh_unavailable_degrades():
    git_ops = GitOps( debug=False )
    with patch( "shutil.which", return_value=None ):
        result = asyncio.run( git_ops.create_pr( "fix/test", "t", "b" ) )
    assert result[ "success" ] is False
    assert result[ "pr_url" ] is None
    assert "gh CLI not available" in result[ "error" ]
    assert git_ops._gh_available is False   # cached


def test_create_pr_gh_command_fails():
    git_ops = GitOps( debug=False )
    git_ops._gh_available = True
    proc = _mock_proc( returncode=1, stderr=b"pull request already exists" )
    with patch( "asyncio.create_subprocess_exec", return_value=proc ):
        result = asyncio.run( git_ops.create_pr( "fix/test", "t", "b" ) )
    assert result[ "success" ] is False
    assert result[ "pr_url" ] is None
    assert "gh pr create failed" in result[ "error" ]


# =============================================================================
# get_current_branch / checkout_branch
# =============================================================================

def test_get_current_branch_success():
    git_ops = GitOps( debug=False )
    proc = _mock_proc( returncode=0, stdout=b"main\n" )
    with patch( "asyncio.create_subprocess_exec", return_value=proc ):
        branch = asyncio.run( git_ops.get_current_branch() )
    assert branch == "main"


def test_get_current_branch_on_failure_returns_empty():
    git_ops = GitOps( debug=False )
    proc = _mock_proc( returncode=128, stderr=b"fatal" )
    with patch( "asyncio.create_subprocess_exec", return_value=proc ):
        branch = asyncio.run( git_ops.get_current_branch() )
    assert branch == ""


def test_checkout_branch_success():
    git_ops = GitOps( debug=False )
    proc = _mock_proc( returncode=0 )
    with patch( "asyncio.create_subprocess_exec", return_value=proc ):
        result = asyncio.run( git_ops.checkout_branch( "main" ) )
    assert result[ "success" ] is True
    assert result[ "error" ] is None
