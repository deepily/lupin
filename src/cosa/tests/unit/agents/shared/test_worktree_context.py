"""
Unit tests for cosa.agents.shared.worktree_context.WorktreeContext.

Async git-worktree isolation context manager. Boundaries mocked: cu.get_project_root,
ConfigurationManager, the instance's _run_git_in (for __aenter__/__aexit__), and
asyncio.create_subprocess_exec/wait_for (for _run_git_in itself). Filesystem work is
confined to tempdirs. No real git/subprocess.

Covers: WorktreeCollisionError, __init__, __aenter__ (disabled / enabled-relative /
enabled-abs / collision / add-failure), __aexit__ (disabled / no-cleanup / success /
remove-fail→prune / prune-also-fails / exception), _load_config (config provided /
lazy-load success / lazy-load failure / get-exception / None-value / enabled-override),
_resolve_base_ref (found / fallback), _run_git_in (success / timeout / exception).

Created 2026-05-31 (CoSA coverage campaign, shared package — Tiffany 💍). New file.
"""

import asyncio
import os
import tempfile
import unittest
from unittest.mock import Mock, AsyncMock, patch

from cosa.agents.shared.worktree_context import WorktreeContext, WorktreeCollisionError

_MOD = "cosa.agents.shared.worktree_context"

_OK   = { "success": True,  "stdout": "ok",  "stderr": "",     "returncode": 0 }
_FAIL = { "success": False, "stdout": "",    "stderr": "boom", "returncode": 1 }


def _run( coro ):
    return asyncio.run( coro )


class TestWorktreeContext( unittest.TestCase ):
    """Comprehensive unit tests for WorktreeContext."""

    def _make_ctx( self, enabled=None, overrides=None, debug=False ):
        """Build a WorktreeContext with a config_mgr mock returning sensible defaults."""
        cfg = Mock()
        defaults = {
            "cosa worktree enabled"              : True,
            "cosa worktree sandbox root"         : ".claude/worktrees",
            "cosa worktree base ref"             : "origin/main",
            "cosa worktree auto cleanup"         : True,
            "cosa worktree cleanup timeout secs" : 30,
        }
        if overrides:
            defaults.update( overrides )
        cfg.get.side_effect = lambda key, default=None, return_type="string": defaults.get( key, default )
        return WorktreeContext( job_id="job1", config_mgr=cfg, enabled=enabled, debug=debug )

    # ------------------------------------------------------------------ #
    # error class + __init__                                              #
    # ------------------------------------------------------------------ #

    def test_collision_error_message( self ):
        """Test the collision error carries the path and a remediation hint."""
        err = WorktreeCollisionError( "/tmp/wt" )
        self.assertIn( "/tmp/wt", str( err ) )
        self.assertIn( "git worktree prune", str( err ) )

    def test_init_defaults( self ):
        """Test the constructor seeds the documented pre-enter state."""
        ctx = WorktreeContext( job_id="abc" )
        self.assertEqual( ctx.job_id, "abc" )
        self.assertIsNone( ctx.path )
        self.assertFalse( ctx.enabled )

    # ------------------------------------------------------------------ #
    # __aenter__                                                          #
    # ------------------------------------------------------------------ #

    def test_aenter_disabled_is_noop( self ):
        """Test a disabled context resolves path to the project root."""
        with tempfile.TemporaryDirectory() as tmp, \
             patch( f"{_MOD}.cu.get_project_root", return_value=tmp ):
            ctx = self._make_ctx( enabled=False, debug=True )
            result = _run( ctx.__aenter__() )
            self.assertFalse( result.enabled )
            self.assertEqual( result.path, tmp )

    def test_aenter_enabled_relative_sandbox( self ):
        """Test an enabled context creates a worktree under a relative sandbox root."""
        with tempfile.TemporaryDirectory() as tmp, \
             patch( f"{_MOD}.cu.get_project_root", return_value=tmp ):
            ctx = self._make_ctx( enabled=True, debug=True )
            ctx._run_git_in = AsyncMock( return_value=_OK )
            result = _run( ctx.__aenter__() )
            self.assertEqual( result.path, os.path.join( tmp, ".claude/worktrees", "job1" ) )

    def test_aenter_enabled_absolute_sandbox( self ):
        """Test an absolute sandbox root is used verbatim."""
        with tempfile.TemporaryDirectory() as tmp, \
             patch( f"{_MOD}.cu.get_project_root", return_value=tmp ):
            abs_sandbox = os.path.join( tmp, "abs-sandbox" )
            ctx = self._make_ctx( enabled=True, overrides={ "cosa worktree sandbox root": abs_sandbox } )
            ctx._run_git_in = AsyncMock( return_value=_OK )
            result = _run( ctx.__aenter__() )
            self.assertEqual( result.path, os.path.join( abs_sandbox, "job1" ) )

    def test_aenter_collision_raises( self ):
        """Test a pre-existing target path raises WorktreeCollisionError."""
        with tempfile.TemporaryDirectory() as tmp, \
             patch( f"{_MOD}.cu.get_project_root", return_value=tmp ):
            target = os.path.join( tmp, ".claude/worktrees", "job1" )
            os.makedirs( target )
            ctx = self._make_ctx( enabled=True )
            ctx._run_git_in = AsyncMock( return_value=_OK )
            with self.assertRaises( WorktreeCollisionError ):
                _run( ctx.__aenter__() )

    def test_aenter_worktree_add_failure_raises( self ):
        """Test a failed `git worktree add` raises RuntimeError."""
        with tempfile.TemporaryDirectory() as tmp, \
             patch( f"{_MOD}.cu.get_project_root", return_value=tmp ):
            ctx = self._make_ctx( enabled=True )
            # rev-parse (resolve_base_ref) succeeds, then worktree add fails
            ctx._run_git_in = AsyncMock( side_effect=[ _OK, _FAIL ] )
            with self.assertRaises( RuntimeError ):
                _run( ctx.__aenter__() )

    # ------------------------------------------------------------------ #
    # __aexit__                                                           #
    # ------------------------------------------------------------------ #

    def test_aexit_disabled_returns_false( self ):
        """Test __aexit__ is a no-op (returns False) when disabled."""
        ctx = self._make_ctx( enabled=False )
        ctx.enabled = False
        self.assertFalse( _run( ctx.__aexit__( None, None, None ) ) )

    def test_aexit_no_auto_cleanup_preserves( self ):
        """Test __aexit__ preserves the worktree when auto_cleanup is off."""
        ctx = self._make_ctx( enabled=True, debug=True )
        ctx.enabled = True
        ctx._auto_cleanup = False
        ctx.path = "/tmp/wt"
        self.assertFalse( _run( ctx.__aexit__( None, None, None ) ) )

    def test_aexit_cleanup_success( self ):
        """Test __aexit__ removes the worktree on success."""
        with patch( f"{_MOD}.cu.get_project_root", return_value="/root" ):
            ctx = self._make_ctx( enabled=True, debug=True )
            ctx.enabled = True
            ctx._auto_cleanup = True
            ctx.path = "/root/wt"
            ctx._run_git_in = AsyncMock( return_value=_OK )
            self.assertFalse( _run( ctx.__aexit__( None, None, None ) ) )
            ctx._run_git_in.assert_awaited()

    def test_aexit_remove_fail_then_prune( self ):
        """Test a failed remove falls back to prune."""
        with patch( f"{_MOD}.cu.get_project_root", return_value="/root" ):
            ctx = self._make_ctx( enabled=True )
            ctx.enabled = True
            ctx._auto_cleanup = True
            ctx.path = "/root/wt"
            ctx._run_git_in = AsyncMock( side_effect=[ _FAIL, _OK ] )   # remove fail, prune ok
            self.assertFalse( _run( ctx.__aexit__( None, None, None ) ) )

    def test_aexit_remove_and_prune_both_fail( self ):
        """Test both remove and prune failing are logged but not raised."""
        with patch( f"{_MOD}.cu.get_project_root", return_value="/root" ):
            ctx = self._make_ctx( enabled=True )
            ctx.enabled = True
            ctx._auto_cleanup = True
            ctx.path = "/root/wt"
            ctx._run_git_in = AsyncMock( side_effect=[ _FAIL, _FAIL ] )
            self.assertFalse( _run( ctx.__aexit__( None, None, None ) ) )

    def test_aexit_cleanup_exception_swallowed( self ):
        """Test an unexpected cleanup exception is logged but not raised."""
        with patch( f"{_MOD}.cu.get_project_root", return_value="/root" ):
            ctx = self._make_ctx( enabled=True )
            ctx.enabled = True
            ctx._auto_cleanup = True
            ctx.path = "/root/wt"
            ctx._run_git_in = AsyncMock( side_effect=Exception( "git blew up" ) )
            self.assertFalse( _run( ctx.__aexit__( None, None, None ) ) )

    # ------------------------------------------------------------------ #
    # _load_config                                                        #
    # ------------------------------------------------------------------ #

    def test_load_config_with_injected_config( self ):
        """Test config values are read from an injected config_mgr."""
        ctx = self._make_ctx( enabled=None )   # enabled_override None → reads config
        enabled, sandbox, ref, cleanup, timeout = ctx._load_config()
        self.assertTrue( enabled )
        self.assertEqual( sandbox, ".claude/worktrees" )
        self.assertEqual( ref, "origin/main" )
        self.assertEqual( timeout, 30 )

    def test_load_config_lazy_load_success( self ):
        """Test a None config_mgr lazily constructs a ConfigurationManager."""
        mock_cfg = Mock()
        mock_cfg.get.side_effect = lambda key, default=None, return_type="string": default
        ctx = WorktreeContext( job_id="j", config_mgr=None, enabled=False )
        with patch( "cosa.config.configuration_manager.ConfigurationManager", return_value=mock_cfg ):
            enabled, *_ = ctx._load_config()
        self.assertFalse( enabled )   # enabled_override False

    def test_load_config_lazy_load_failure_uses_defaults( self ):
        """Test a ConfigurationManager construction failure falls back to defaults."""
        ctx = WorktreeContext( job_id="j", config_mgr=None, enabled=None )
        with patch( "cosa.config.configuration_manager.ConfigurationManager", side_effect=Exception( "no cfg" ) ):
            enabled, sandbox, ref, cleanup, timeout = ctx._load_config()
        self.assertFalse( enabled )                       # default
        self.assertEqual( sandbox, ".claude/worktrees" )  # default

    def test_load_config_get_exception_returns_default( self ):
        """Test a config.get exception is caught and the default returned."""
        cfg = Mock()
        cfg.get.side_effect = Exception( "boom" )
        ctx = WorktreeContext( job_id="j", config_mgr=cfg, enabled=None )
        enabled, sandbox, *_ = ctx._load_config()
        self.assertFalse( enabled )
        self.assertEqual( sandbox, ".claude/worktrees" )

    def test_load_config_none_value_returns_default( self ):
        """Test a None config value falls back to the default."""
        cfg = Mock()
        cfg.get.side_effect = lambda key, default=None, return_type="string": None
        ctx = WorktreeContext( job_id="j", config_mgr=cfg, enabled=None )
        _, sandbox, ref, *_ = ctx._load_config()
        self.assertEqual( sandbox, ".claude/worktrees" )
        self.assertEqual( ref, "origin/main" )

    # ------------------------------------------------------------------ #
    # _resolve_base_ref                                                   #
    # ------------------------------------------------------------------ #

    def test_resolve_base_ref_found( self ):
        """Test a verifiable ref is returned unchanged."""
        ctx = self._make_ctx( enabled=True )
        ctx._run_git_in = AsyncMock( return_value=_OK )
        ref = _run( ctx._resolve_base_ref( "/root", "origin/main" ) )
        self.assertEqual( ref, "origin/main" )
        self.assertFalse( ctx._fallback_used )

    def test_resolve_base_ref_falls_back_to_head( self ):
        """Test a missing ref falls back to HEAD and flags the fallback."""
        ctx = self._make_ctx( enabled=True )
        ctx._run_git_in = AsyncMock( return_value=_FAIL )
        ref = _run( ctx._resolve_base_ref( "/root", "origin/nope" ) )
        self.assertEqual( ref, "HEAD" )
        self.assertTrue( ctx._fallback_used )

    # ------------------------------------------------------------------ #
    # _run_git_in                                                         #
    # ------------------------------------------------------------------ #

    def test_run_git_in_success( self ):
        """Test _run_git_in returns a success dict on a clean process exit."""
        ctx = self._make_ctx( enabled=True )
        proc = Mock()
        proc.returncode = 0
        proc.communicate = AsyncMock( return_value=( b"out", b"err" ) )

        with patch( f"{_MOD}.asyncio.create_subprocess_exec", AsyncMock( return_value=proc ) ):
            result = _run( ctx._run_git_in( "/root", "status" ) )

        self.assertTrue( result[ "success" ] )
        self.assertEqual( result[ "stdout" ], "out" )

    def test_run_git_in_timeout( self ):
        """Test _run_git_in kills the process and reports a timeout."""
        ctx = self._make_ctx( enabled=True )
        proc = Mock()
        proc.kill = Mock()
        proc.wait = AsyncMock()
        proc.communicate = AsyncMock( return_value=( b"", b"" ) )

        with patch( f"{_MOD}.asyncio.create_subprocess_exec", AsyncMock( return_value=proc ) ), \
             patch( f"{_MOD}.asyncio.wait_for", AsyncMock( side_effect=asyncio.TimeoutError() ) ):
            result = _run( ctx._run_git_in( "/root", "status", timeout=1 ) )

        self.assertFalse( result[ "success" ] )
        self.assertIn( "timeout", result[ "stderr" ] )
        proc.kill.assert_called_once()

    def test_run_git_in_exception( self ):
        """Test _run_git_in returns a failure dict when subprocess spawn raises."""
        ctx = self._make_ctx( enabled=True )
        with patch( f"{_MOD}.asyncio.create_subprocess_exec", AsyncMock( side_effect=OSError( "no git" ) ) ):
            result = _run( ctx._run_git_in( "/root", "status" ) )
        self.assertFalse( result[ "success" ] )
        self.assertIn( "no git", result[ "stderr" ] )


if __name__ == "__main__":
    unittest.main()
