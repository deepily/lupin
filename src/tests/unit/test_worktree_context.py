"""
Unit tests for WorktreeContext (Bug 9, 2026-04-16).

Uses tempfile.TemporaryDirectory + real `git init` to exercise the real git
CLI — mocking subprocess calls would hide behavioral bugs in the worktree
plumbing itself. Tests are fast (~100ms each) and isolated.

See: src/rnd/v0.1.6/2026.04.16-bug-9-worktree-isolation.md
"""

import asyncio
import os
import subprocess
import tempfile
from unittest.mock import patch

import pytest

from cosa.agents.shared.worktree_context import WorktreeContext, WorktreeCollisionError


# ---------------------------------------------------------------------------
# Fixture: create an isolated bare-git repo we can safely run worktree ops in
# ---------------------------------------------------------------------------

def _init_test_repo( path: str ) -> None:
    """Initialize a minimal git repo with one commit + origin/main ref."""
    env = { **os.environ, "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null" }

    def run( *args ):
        subprocess.run( args, cwd=path, env=env, check=True, capture_output=True )

    run( "git", "init", "-b", "main", "." )
    run( "git", "config", "user.email", "test@example.com" )
    run( "git", "config", "user.name", "Test" )
    # Initial commit
    with open( os.path.join( path, "README.md" ), "w" ) as f:
        f.write( "# test\n" )
    run( "git", "add", "." )
    run( "git", "commit", "-m", "initial" )
    # Simulate origin/main by tagging HEAD as such
    run( "git", "update-ref", "refs/remotes/origin/main", "HEAD" )


@pytest.fixture
def test_repo():
    """Yield a temp git repo + project-root patch. Cleans up worktrees on exit."""
    with tempfile.TemporaryDirectory() as tmp:
        _init_test_repo( tmp )
        # Patch cu.get_project_root() to point at our temp repo so WorktreeContext
        # resolves sandbox_root under it.
        with patch( "cosa.agents.shared.worktree_context.cu.get_project_root",
                    return_value=tmp ):
            yield tmp
        # Cleanup any leftover worktrees before TemporaryDirectory removes the tree.
        try:
            subprocess.run(
                [ "git", "worktree", "prune" ], cwd=tmp, check=False, capture_output=True,
            )
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Stub ConfigurationManager for test isolation (no INI read)
# ---------------------------------------------------------------------------

class _StubConfig:
    """Minimal ConfigurationManager stub that returns a static dict of values."""

    def __init__( self, values: dict ):
        self._values = values

    def get( self, key: str, default=None, return_type: str = "string" ):
        return self._values.get( key, default )


# ===========================================================================
# Tests
# ===========================================================================

class TestWorktreeContextDisabled:
    """When enabled=False, context is a no-op routing to project root."""

    @pytest.mark.asyncio
    async def test_disabled_yields_project_root( self, test_repo ):
        async with WorktreeContext( job_id="tfe-disabled", enabled=False ) as wt:
            assert wt.enabled is False
            assert wt.path == test_repo

    @pytest.mark.asyncio
    async def test_disabled_does_not_create_sandbox( self, test_repo ):
        async with WorktreeContext( job_id="tfe-disabled-2", enabled=False ):
            pass
        sandbox = os.path.join( test_repo, ".claude", "worktrees" )
        assert not os.path.exists( sandbox )


class TestWorktreeContextEnabled:
    """When enabled=True, creates + cleans up worktree."""

    @pytest.mark.asyncio
    async def test_enter_creates_worktree_on_origin_main( self, test_repo ):
        cfg = _StubConfig( {
            "cosa worktree sandbox root"         : ".claude/worktrees",
            "cosa worktree base ref"             : "origin/main",
            "cosa worktree auto cleanup"         : True,
            "cosa worktree cleanup timeout secs" : 30,
        } )
        async with WorktreeContext( job_id="tfe-job-a", config_mgr=cfg, enabled=True ) as wt:
            assert wt.enabled is True
            assert wt.path is not None
            assert wt.path.endswith( os.path.join( ".claude", "worktrees", "tfe-job-a" ) )
            # Worktree actually exists and contains the repo contents
            assert os.path.isdir( wt.path )
            assert os.path.exists( os.path.join( wt.path, "README.md" ) )

    @pytest.mark.asyncio
    async def test_exit_auto_cleanup_removes_worktree( self, test_repo ):
        cfg = _StubConfig( {
            "cosa worktree sandbox root"         : ".claude/worktrees",
            "cosa worktree base ref"             : "origin/main",
            "cosa worktree auto cleanup"         : True,
            "cosa worktree cleanup timeout secs" : 30,
        } )
        async with WorktreeContext( job_id="tfe-job-cleanup", config_mgr=cfg, enabled=True ) as wt:
            path = wt.path
            assert os.path.isdir( path )
        # After exit, worktree is gone
        assert not os.path.exists( path )

    @pytest.mark.asyncio
    async def test_auto_cleanup_disabled_preserves_worktree( self, test_repo ):
        cfg = _StubConfig( {
            "cosa worktree sandbox root"         : ".claude/worktrees",
            "cosa worktree base ref"             : "origin/main",
            "cosa worktree auto cleanup"         : False,
            "cosa worktree cleanup timeout secs" : 30,
        } )
        async with WorktreeContext( job_id="tfe-job-preserve", config_mgr=cfg, enabled=True ) as wt:
            path = wt.path
        # Preserved
        assert os.path.isdir( path )
        # Manual cleanup so tempdir teardown doesn't hit admin-file residue
        subprocess.run( [ "git", "worktree", "remove", "--force", path ],
                        cwd=test_repo, check=False, capture_output=True )

    @pytest.mark.asyncio
    async def test_collision_detected( self, test_repo ):
        """Pre-existing path at target raises WorktreeCollisionError."""
        cfg = _StubConfig( {
            "cosa worktree sandbox root"         : ".claude/worktrees",
            "cosa worktree base ref"             : "origin/main",
            "cosa worktree auto cleanup"         : False,   # preserve first worktree
            "cosa worktree cleanup timeout secs" : 30,
        } )
        async with WorktreeContext( job_id="collide-1", config_mgr=cfg, enabled=True ) as wt:
            path = wt.path
        # Attempt to re-enter with the same job_id should collide
        with pytest.raises( WorktreeCollisionError ) as exc_info:
            async with WorktreeContext( job_id="collide-1", config_mgr=cfg, enabled=True ):
                pass
        assert "collide-1" in str( exc_info.value )
        assert "git worktree prune" in str( exc_info.value )
        # Manual cleanup
        subprocess.run( [ "git", "worktree", "remove", "--force", path ],
                        cwd=test_repo, check=False, capture_output=True )

    @pytest.mark.asyncio
    async def test_base_ref_missing_falls_back_to_head( self, test_repo ):
        """Invalid base_ref → fall back to HEAD with warning."""
        cfg = _StubConfig( {
            "cosa worktree sandbox root"         : ".claude/worktrees",
            "cosa worktree base ref"             : "origin/nonexistent-branch",
            "cosa worktree auto cleanup"         : True,
            "cosa worktree cleanup timeout secs" : 30,
        } )
        async with WorktreeContext( job_id="fallback-head", config_mgr=cfg, enabled=True ) as wt:
            assert wt.enabled is True
            assert wt.path is not None
            # Fallback happened — HEAD worktree created successfully
            assert os.path.isdir( wt.path )
            assert wt._fallback_used is True


class TestWorktreeContextCleanupSafety:
    """Cleanup errors must not mask the primary exception."""

    @pytest.mark.asyncio
    async def test_cleanup_error_does_not_mask_primary_exception( self, test_repo ):
        """Simulate a cleanup failure by removing the worktree dir manually before __aexit__."""
        cfg = _StubConfig( {
            "cosa worktree sandbox root"         : ".claude/worktrees",
            "cosa worktree base ref"             : "origin/main",
            "cosa worktree auto cleanup"         : True,
            "cosa worktree cleanup timeout secs" : 30,
        } )

        class _PrimaryError( Exception ):
            pass

        with pytest.raises( _PrimaryError ):
            async with WorktreeContext( job_id="cleanup-fail", config_mgr=cfg, enabled=True ) as wt:
                # Corrupt the worktree so `git worktree remove` will fail
                # (removing the .git pointer file simulates a mid-flight crash)
                git_dir = os.path.join( wt.path, ".git" )
                if os.path.exists( git_dir ) and os.path.isfile( git_dir ):
                    os.remove( git_dir )
                raise _PrimaryError( "primary raise from caller" )


# ===========================================================================
# Row 438a8b49: a finished job must not leave its folder when git's record is gone
# ===========================================================================

_CLEANUP_CFG = {
    "cosa worktree sandbox root"         : ".claude/worktrees",
    "cosa worktree base ref"             : "origin/main",
    "cosa worktree auto cleanup"         : True,
    "cosa worktree cleanup timeout secs" : 30,
}


def _drop_git_record( repo: str, job_id: str ) -> None:
    """Delete git's record of a worktree, as a host-side prune does."""
    record = os.path.join( repo, ".git", "worktrees", job_id )
    os.rename( record, record + ".dropped" )


class TestFinishedJobLeavesNoFolder:
    """A finished job leaves no folder even when git forgot the tree."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize( "outcome", [ "success", "failure", "cancel" ] )
    async def test_record_gone_folder_removed( self, test_repo, outcome ):
        job_id = f"tfe-orphan-{outcome}"
        raised = { "failure": RuntimeError, "cancel": asyncio.CancelledError }.get( outcome )
        path   = None
        try:
            async with WorktreeContext( job_id=job_id, config_mgr=_StubConfig( _CLEANUP_CFG ), enabled=True ) as wt:
                path = wt.path
                _drop_git_record( test_repo, job_id )
                assert os.path.isdir( path )
                if raised: raise raised( "job ended" )
        except ( RuntimeError, asyncio.CancelledError ):
            assert raised is not None
        assert path is not None
        assert not os.path.exists( path )

    @pytest.mark.asyncio
    async def test_folder_without_git_link_is_kept( self, test_repo ):
        """Only a folder with a dangling .git link is deleted."""
        async with WorktreeContext( job_id="tfe-nolink", config_mgr=_StubConfig( _CLEANUP_CFG ), enabled=True ) as wt:
            path = wt.path
            os.remove( os.path.join( path, ".git" ) )
        assert os.path.isdir( path )

    @pytest.mark.asyncio
    async def test_rmtree_failure_is_logged_not_raised( self, test_repo, caplog ):
        with patch( "cosa.agents.shared.worktree_context.shutil.rmtree", side_effect=OSError( "busy" ) ):
            async with WorktreeContext( job_id="tfe-rmfail", config_mgr=_StubConfig( _CLEANUP_CFG ), enabled=True ) as wt:
                path = wt.path
                _drop_git_record( test_repo, "tfe-rmfail" )
        assert os.path.isdir( path )
        assert "could not remove dangling sandbox" in caplog.text


class TestHasDanglingGitLink:
    """Edges of the predicate that gates deletion."""

    def test_missing_path( self, tmp_path ):
        from cosa.agents.shared.worktree_context import has_dangling_git_link
        assert has_dangling_git_link( str( tmp_path / "nope" ) ) is False

    def test_git_directory( self, tmp_path ):
        from cosa.agents.shared.worktree_context import has_dangling_git_link
        ( tmp_path / ".git" ).mkdir()
        assert has_dangling_git_link( str( tmp_path ) ) is False

    def test_not_a_gitdir_line( self, tmp_path ):
        from cosa.agents.shared.worktree_context import has_dangling_git_link
        ( tmp_path / ".git" ).write_text( "garbage\n" )
        assert has_dangling_git_link( str( tmp_path ) ) is False

    def test_unreadable_file( self, tmp_path ):
        from cosa.agents.shared.worktree_context import has_dangling_git_link
        ( tmp_path / ".git" ).write_text( "gitdir: /x\n" )
        with patch( "builtins.open", side_effect=OSError( "denied" ) ):
            assert has_dangling_git_link( str( tmp_path ) ) is False

    def test_live_and_dangling( self, tmp_path ):
        from cosa.agents.shared.worktree_context import has_dangling_git_link
        live = tmp_path / "live-record"; live.mkdir()
        ( tmp_path / ".git" ).write_text( f"gitdir: {live}\n" )
        assert has_dangling_git_link( str( tmp_path ) ) is False
        ( tmp_path / ".git" ).write_text( f"gitdir: {tmp_path}/gone\n" )
        assert has_dangling_git_link( str( tmp_path ) ) is True


class TestBrokenFolderWithoutDanglingLink:
    @pytest.mark.asyncio
    async def test_reaper_refusal_without_dangling_link_leaves_folder( self, test_repo, caplog ):
        """The reaper says broken, but the folder has no .git link to judge by: keep it and warn."""
        refusal = { "removed": False, "skipped_reason": "broken_or_not_a_worktree", "errors": [ "x" ],
                    "wip_committed": False, "branch": None }
        with patch( "cosa.agents.shared.worktree_context.drain_then_remove", return_value=refusal ):
            async with WorktreeContext( job_id="tfe-nolink2", config_mgr=_StubConfig( _CLEANUP_CFG ), enabled=True, debug=True ) as wt:
                path = wt.path
                os.remove( os.path.join( path, ".git" ) )
        assert os.path.isdir( path )
        assert "no dangling link" in caplog.text
