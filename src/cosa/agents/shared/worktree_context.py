"""
Async context manager for TFE/BFE git worktree isolation (Bug 9, 2026-04-16).

When `cosa worktree enabled` is true, FixExecutor (Phase 3) and GitStrategist
(Phase 5) run inside a dedicated worktree sandbox so agent edits never touch
the operator's current working tree.

Usage:
    async with WorktreeContext( job_id ) as wt:
        if wt.enabled:
            executor = FixExecutor( ..., worktree_cwd=wt.path )
            git_ops  = GitOps( cwd=wt.path )
        else:
            executor = FixExecutor( ... )
            git_ops  = GitOps( cwd=cu.get_project_root() )
        # ... work ...
    # auto-cleanup on __aexit__ (when auto_cleanup=true)

Design:
    - Config read from ConfigurationManager (LUPIN_CONFIG_MGR_CLI_ARGS)
    - `enabled=False` by default → context becomes a no-op and `wt.path` is
       the project root, so callers can uniformly pass it
    - Collision detection: target path must NOT exist at __aenter__
    - Base ref validation: falls back to HEAD with warning if configured ref missing
    - Cleanup failures are logged as warnings; never mask the primary exception

See: src/rnd/v0.1.6/2026.04.16-bug-9-worktree-isolation.md
"""

import asyncio
import logging
import os
from typing import Optional

import cosa.utils.util as cu
from cosa.agents.shared.worktree_reaper import drain_then_remove
from cosa.utils.worktree_venv import provision_worktree_venv


logger = logging.getLogger( __name__ )


class WorktreeCollisionError( RuntimeError ):
    """
    Raised when the target worktree path already exists at __aenter__.

    Requires:
        - path is the resolved absolute worktree path
    """
    def __init__( self, path: str ):
        super().__init__(
            f"Worktree target path already exists: {path}. "
            f"Two jobs may be using the same job_id, or a previous run left "
            f"an orphaned worktree. Run `git worktree prune` and retry."
        )


class WorktreeContext:
    """
    Async context manager for git worktree isolation.

    Requires:
        - job_id is a non-empty string used to name the worktree directory
        - config_mgr is None (loaded lazily) or a ConfigurationManager instance

    Ensures:
        - __aenter__ creates an isolated worktree when `cosa worktree enabled`
          is true; otherwise is a no-op and `self.path` points to project root
        - __aexit__ cleans up when auto_cleanup is true; swallows cleanup errors
        - `self.enabled` reflects whether isolation is actually active

    Attributes:
        path (str): Absolute path to the worktree (or project root when disabled)
        enabled (bool): True iff isolation was activated
        job_id (str): The job_id used for worktree naming
    """

    def __init__(
        self,
        job_id: str,
        config_mgr    = None,
        enabled       : Optional[ bool ] = None,
        debug         : bool             = False,
    ) -> None:
        """
        Build a worktree context.

        Args:
            job_id: Used to name the sandbox subdirectory
            config_mgr: Optional pre-built ConfigurationManager (injected in tests)
            enabled: Optional override for `cosa worktree enabled` INI key
                     (tests force on/off without touching INI)
            debug: Enable verbose logging
        """
        self.job_id     = job_id
        self.debug      = debug
        self._config_mgr      = config_mgr
        self._enabled_override = enabled

        # Resolved on __aenter__ (None until then)
        self.path                  : Optional[ str ] = None
        self.enabled               : bool            = False
        self._auto_cleanup         : bool            = True
        self._cleanup_timeout_secs : int             = 30
        self._fallback_used        : bool            = False

    # ------------------------------------------------------------------
    # Context manager protocol
    # ------------------------------------------------------------------

    async def __aenter__( self ) -> "WorktreeContext":
        """
        Resolve config, validate base_ref, create worktree.

        Ensures:
            - self.path is always set (project root when disabled; worktree path when enabled)
            - self.enabled reflects the effective state
        """
        cfg_enabled, sandbox_root, base_ref, auto_cleanup, cleanup_timeout = self._load_config()
        self.enabled               = cfg_enabled
        self._auto_cleanup         = auto_cleanup
        self._cleanup_timeout_secs = cleanup_timeout

        project_root = cu.get_project_root()

        if not self.enabled:
            # No-op: caller sees project root and can behave identically
            self.path = project_root
            if self.debug: print( f"[WorktreeContext] Isolation disabled — using project root: {project_root}" )
            return self

        # Resolve sandbox path: <project_root>/<sandbox_root>/<job_id>
        # sandbox_root is relative to project root (INI default: .claude/worktrees)
        if os.path.isabs( sandbox_root ):
            sandbox_base = sandbox_root
        else:
            sandbox_base = os.path.join( project_root, sandbox_root )
        target_path = os.path.join( sandbox_base, self.job_id )

        # Ensure parent exists
        os.makedirs( sandbox_base, exist_ok=True )

        # Collision detection — fail loud
        if os.path.exists( target_path ):
            raise WorktreeCollisionError( target_path )

        # Validate base_ref; fall back to HEAD if missing
        effective_ref = await self._resolve_base_ref( project_root, base_ref )

        # Create the worktree
        result = await self._run_git_in( project_root, "worktree", "add", target_path, effective_ref )
        if not result[ "success" ]:
            raise RuntimeError(
                f"`git worktree add {target_path} {effective_ref}` failed: "
                f"{result.get( 'stderr', '' ) or result.get( 'stdout', '' )}"
            )

        self.path = target_path

        # ── Give the new worktree a .venv (row 9b2abfb7) ──────────────────────────
        #
        # `.venv` is gitignored, so the `git worktree add` above CANNOT have produced
        # one, and four unit files shell out to `<PROJECT_ROOT>/.venv/bin/{python,
        # pytest}`. Every `.claude/worktrees/<job_id>` tree came up without an
        # interpreter before this line existed — re-derived 2026-08-31, 6 such trees on
        # disk and 0 with a usable one. That is a census with a date on it, not a
        # standing fact; re-run it rather than quoting it. A BFE/TFE job running its own
        # tests in here would see failures caused by the sandbox rather than by the code
        # it was sent to fix.
        #
        # ⚠️ FAIL OPEN, and off the event loop. `provision_worktree_venv` never raises,
        # so a provisioning failure cannot break a job that would otherwise have run;
        # it logs at WARNING instead. It shells out, so it goes through `to_thread` for
        # the same reason `__aexit__` does with the reaper.
        venv_result = await asyncio.to_thread( provision_worktree_venv, target_path, self.debug )
        if self.debug: print( f"[WorktreeContext] venv: {venv_result[ 'status' ]} - {venv_result[ 'detail' ]}" )

        if self.debug: print( f"[WorktreeContext] Created: {target_path} @ {effective_ref}" )
        return self

    async def __aexit__( self, exc_type, exc, tb ) -> bool:
        """
        Clean up the worktree when auto_cleanup is true — via the shared
        drain-then-remove reaper (Worktree Lifecycle Contract §4a).

        Ensures:
            - Returns False so any primary exception propagates unmasked
            - Cleanup errors are logged as warnings but never raised
            - Delegates to worktree_reaper.drain_then_remove, which DIRTY-GATES:
              it auto-commits WIP to the branch ONLY when `git status --porcelain`
              is non-empty, then removes the dir + KEEPS the branch (never pushes).
              A NORMAL exit is expected-clean (FixExecutor/GitStrategist commit
              their own work by design — verified 2026-06-22), so the auto-commit
              fires ONLY on the abnormal-exit path (an exception / early-return
              that left WIP) — the rescue we want, with zero interference on the
              happy path. No in-flight check is needed: the `async with` body
              (and thus any GitStrategist op) has completed before __aexit__ runs.
        """
        if not self.enabled:
            return False

        if not self._auto_cleanup:
            if self.debug: print( f"[WorktreeContext] auto_cleanup=false — preserving {self.path}" )
            return False

        project_root = cu.get_project_root()
        try:
            # Sync reaper (subprocess git inside) → run off the event loop.
            result = await asyncio.to_thread(
                drain_then_remove, self.path, project_root=project_root, debug=self.debug,
            )
            if self.debug:
                print( f"[WorktreeContext] drain_then_remove: removed={result[ 'removed' ]} "
                       f"wip_committed={result[ 'wip_committed' ]} branch={result[ 'branch' ]}" )
            if not result[ "removed" ] and result.get( "errors" ):
                logger.warning(
                    f"[WorktreeContext] drain_then_remove did not remove {self.path}: "
                    f"{result[ 'errors' ]}"
                )
        except Exception as e:
            logger.warning( f"[WorktreeContext] Cleanup raised unexpectedly: {e}" )

        return False   # Never swallow the caller's primary exception

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _load_config( self ) -> tuple:
        """
        Read config values. Returns (enabled, sandbox_root, base_ref, auto_cleanup, cleanup_timeout).

        Tests inject either a config_mgr with get() or an enabled-override.
        """
        # Test override wins: if enabled=True/False was passed, honor it;
        # still try to load other keys from config_mgr if provided.
        if self._config_mgr is None:
            try:
                from cosa.config.configuration_manager import ConfigurationManager
                self._config_mgr = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )
            except Exception as e:
                logger.warning( f"[WorktreeContext] Config load failed, using defaults: {e}" )
                self._config_mgr = None

        def _get( key, default, return_type="string" ):
            if self._config_mgr is None:
                return default
            try:
                val = self._config_mgr.get( key, default=default, return_type=return_type )
                return val if val is not None else default
            except Exception:
                return default

        if self._enabled_override is not None:
            enabled = bool( self._enabled_override )
        else:
            enabled = _get( "cosa worktree enabled", False, return_type="boolean" )

        sandbox_root    = _get( "cosa worktree sandbox root", ".claude/worktrees" )
        base_ref        = _get( "cosa worktree base ref", "origin/main" )
        auto_cleanup    = _get( "cosa worktree auto cleanup", True, return_type="boolean" )
        cleanup_timeout = _get( "cosa worktree cleanup timeout secs", 30, return_type="int" )

        return ( enabled, sandbox_root, base_ref, auto_cleanup, cleanup_timeout )

    async def _resolve_base_ref( self, cwd: str, configured_ref: str ) -> str:
        """
        Validate that `configured_ref` exists. If not, fall back to HEAD with warning.
        """
        result = await self._run_git_in( cwd, "rev-parse", "--verify", f"{configured_ref}^{{commit}}" )
        if result[ "success" ]:
            return configured_ref

        logger.warning(
            f"[WorktreeContext] base_ref '{configured_ref}' not found "
            f"(git rev-parse returned: {result.get( 'stderr', '' ).strip()}). "
            f"Falling back to HEAD."
        )
        self._fallback_used = True
        return "HEAD"

    async def _run_git_in( self, cwd: str, *args: str, timeout: int = 60 ) -> dict:
        """
        Run `git <args>` in a specific cwd with timeout.

        Returns:
            dict with keys: success (bool), stdout (str), stderr (str), returncode (int)
        """
        try:
            proc = await asyncio.create_subprocess_exec(
                "git", *args,
                stdout = asyncio.subprocess.PIPE,
                stderr = asyncio.subprocess.PIPE,
                cwd    = cwd,
            )
            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    proc.communicate(), timeout=timeout,
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                return { "success": False, "stdout": "", "stderr": f"timeout after {timeout}s", "returncode": -1 }

            return {
                "success"    : proc.returncode == 0,
                "stdout"     : stdout_bytes.decode( "utf-8", errors="replace" ).strip(),
                "stderr"     : stderr_bytes.decode( "utf-8", errors="replace" ).strip(),
                "returncode" : proc.returncode,
            }
        except Exception as e:
            return { "success": False, "stdout": "", "stderr": str( e ), "returncode": -1 }


# ==========================================================================
# Quick smoke test
# ==========================================================================

def quick_smoke_test():
    """Quick smoke test for WorktreeContext (no live git operations)."""
    import inspect
    import tempfile
    import asyncio as _asyncio

    cu.print_banner( "WorktreeContext Smoke Test", prepend_nl=True )

    try:
        # Test 1: Instantiation
        print( "Testing instantiation..." )
        wt = WorktreeContext( job_id="tfe-smoketest-001" )
        assert wt.job_id == "tfe-smoketest-001"
        assert wt.path is None   # not yet entered
        assert wt.enabled is False   # not yet loaded
        print( "  ok" )

        # Test 2: Disabled path (enabled=False) is a no-op
        print( "Testing disabled __aenter__ no-op..." )
        async def _disabled():
            async with WorktreeContext( job_id="disabled-smoketest", enabled=False ) as w:
                assert w.enabled is False
                assert w.path == cu.get_project_root()
            return True
        ok = _asyncio.run( _disabled() )
        assert ok
        print( f"  ok — disabled path resolves to project root" )

        # Test 3: Async methods
        print( "Testing async method signatures..." )
        assert inspect.iscoroutinefunction( wt.__aenter__ )
        assert inspect.iscoroutinefunction( wt.__aexit__ )
        print( "  ok" )

        # Test 4: Collision error class
        print( "Testing WorktreeCollisionError..." )
        err = WorktreeCollisionError( "/tmp/fake" )
        assert "/tmp/fake" in str( err )
        assert "git worktree prune" in str( err )
        print( "  ok" )

        print( "\n  WorktreeContext smoke test completed successfully" )

    except Exception as e:
        print( f"\n  Smoke test failed: {e}" )
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    quick_smoke_test()
