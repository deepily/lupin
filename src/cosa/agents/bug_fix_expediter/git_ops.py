"""
Async git operations module for Bug Fix Expediter Phase 5.

Provides commit/branch/push/PR primitives via asyncio.create_subprocess_exec().
All methods return dicts — NEVER raise. Failures populate an `error` key.

Design:
    - Low-level `_run_git(*args)` runs `git <args>` with timeout
    - High-level methods (commit_on_branch, create_fix_branch, etc.) compose
      `_run_git` calls and return operation-specific result dicts
    - `create_pr` gracefully degrades if `gh` CLI is missing (caches detection)

Pattern reference: src/cosa/agents/swe_team/test_runner.py (lines 124-128)
"""

import asyncio
import os
import shutil
from typing import Optional


class GitOps:
    """
    Async wrapper around git CLI + gh CLI for BFE Phase 5.

    Requires:
        - cwd is None or an existing directory path
        - timeout_secs is a positive integer

    Ensures:
        - All methods return dicts with a 'success' boolean
        - Never raises — failures populate 'error' key
        - `gh` CLI availability is cached after first detection
    """

    def __init__(
        self,
        cwd: Optional[ str ] = None,
        timeout_secs: int    = 30,
        debug: bool          = False,
    ) -> None:
        self.cwd          = cwd
        self.timeout_secs = timeout_secs
        self.debug        = debug
        self._gh_available: Optional[ bool ] = None   # None = not yet detected

    async def _run_git( self, *args: str ) -> dict:
        """
        Run `git <args>` asynchronously with timeout.

        Ensures:
            - Returns {"success": bool, "stdout": str, "stderr": str, "returncode": int}
            - Never raises; timeout/exception populate error on returncode
        """
        return await self._run_cmd( "git", *args )

    async def _run_cmd( self, cmd: str, *args: str ) -> dict:
        """Generic async subprocess runner with timeout."""
        if self.debug: print( f"[GitOps] {cmd} {' '.join( args )}" )
        try:
            proc = await asyncio.create_subprocess_exec(
                cmd, *args,
                stdout = asyncio.subprocess.PIPE,
                stderr = asyncio.subprocess.PIPE,
                cwd    = self.cwd,
            )
            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    proc.communicate(),
                    timeout = self.timeout_secs,
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                return { "success": False, "stdout": "", "stderr": f"timeout after {self.timeout_secs}s", "returncode": -1 }

            stdout = stdout_bytes.decode( "utf-8", errors="replace" ).strip()
            stderr = stderr_bytes.decode( "utf-8", errors="replace" ).strip()
            return {
                "success"    : proc.returncode == 0,
                "stdout"     : stdout,
                "stderr"     : stderr,
                "returncode" : proc.returncode,
            }
        except Exception as e:
            return { "success": False, "stdout": "", "stderr": str( e ), "returncode": -1 }

    async def get_current_branch( self ) -> str:
        """
        Return current git branch name (empty string on failure).
        """
        result = await self._run_git( "rev-parse", "--abbrev-ref", "HEAD" )
        return result[ "stdout" ] if result[ "success" ] else ""

    async def commit_on_branch( self, files_changed: list, commit_message: str ) -> dict:
        """
        Stage files and commit on the current branch.

        Requires:
            - files_changed is a list of file path strings
            - commit_message is non-empty

        Ensures:
            - Returns {"success": bool, "commit_hash": str|None, "error": str|None}
            - No-op if files_changed is empty (success=False, error="no files to commit")
        """
        if not files_changed:
            return { "success": False, "commit_hash": None, "error": "no files to commit" }

        # git add <files>
        add_result = await self._run_git( "add", *files_changed )
        if not add_result[ "success" ]:
            return { "success": False, "commit_hash": None, "error": f"git add failed: {add_result[ 'stderr' ]}" }

        # git commit -m "<message>"
        commit_result = await self._run_git( "commit", "-m", commit_message )
        if not commit_result[ "success" ]:
            return { "success": False, "commit_hash": None, "error": f"git commit failed: {commit_result[ 'stderr' ]}" }

        # git rev-parse HEAD to capture hash
        hash_result = await self._run_git( "rev-parse", "HEAD" )
        if not hash_result[ "success" ]:
            return { "success": False, "commit_hash": None, "error": "commit succeeded but hash lookup failed" }

        return { "success": True, "commit_hash": hash_result[ "stdout" ], "error": None }

    async def create_fix_branch( self, slug: str ) -> dict:
        """
        Create and checkout a new fix branch named exactly <slug>.

        Requires:
            - slug is a non-empty string (caller is responsible for formatting
              e.g. "fix/2026-04-05-null-pointer")

        Ensures:
            - Returns {"success": bool, "branch_name": str|None, "error": str|None}
        """
        if not slug:
            return { "success": False, "branch_name": None, "error": "empty slug" }
        result = await self._run_git( "checkout", "-b", slug )
        if not result[ "success" ]:
            return { "success": False, "branch_name": None, "error": f"git checkout -b failed: {result[ 'stderr' ]}" }
        return { "success": True, "branch_name": slug, "error": None }

    async def commit_and_push( self, branch: str, files_changed: list, commit_message: str ) -> dict:
        """
        Stage + commit + push branch to origin with upstream tracking.

        Ensures:
            - Returns {"success": bool, "commit_hash": str|None, "error": str|None}
        """
        commit_result = await self.commit_on_branch( files_changed, commit_message )
        if not commit_result[ "success" ]:
            return commit_result

        push_result = await self._run_git( "push", "-u", "origin", branch )
        if not push_result[ "success" ]:
            return { "success": False, "commit_hash": commit_result[ "commit_hash" ], "error": f"git push failed: {push_result[ 'stderr' ]}" }

        return { "success": True, "commit_hash": commit_result[ "commit_hash" ], "error": None }

    async def create_pr( self, branch: str, title: str, body: str ) -> dict:
        """
        Create a pull request via `gh pr create`.

        Ensures:
            - Returns {"success": bool, "pr_url": str|None, "error": str|None}
            - If `gh` CLI missing: returns success=False, error="gh CLI not available"
              (caller should degrade to branch_only strategy)
        """
        if self._gh_available is None:
            self._gh_available = shutil.which( "gh" ) is not None
            if self.debug: print( f"[GitOps] gh CLI available: {self._gh_available}" )

        if not self._gh_available:
            return { "success": False, "pr_url": None, "error": "gh CLI not available" }

        result = await self._run_cmd(
            "gh", "pr", "create",
            "--title", title,
            "--body", body,
            "--head", branch,
        )
        if not result[ "success" ]:
            return { "success": False, "pr_url": None, "error": f"gh pr create failed: {result[ 'stderr' ]}" }

        # gh prints the PR URL to stdout
        return { "success": True, "pr_url": result[ "stdout" ], "error": None }

    async def checkout_branch( self, branch: str ) -> dict:
        """
        Checkout an existing branch.

        Ensures:
            - Returns {"success": bool, "error": str|None}
        """
        result = await self._run_git( "checkout", branch )
        if not result[ "success" ]:
            return { "success": False, "error": f"git checkout failed: {result[ 'stderr' ]}" }
        return { "success": True, "error": None }


def quick_smoke_test():
    """Quick smoke test for GitOps (mocks subprocess)."""
    import cosa.utils.util as cu

    cu.print_banner( "BFE GitOps Smoke Test", prepend_nl=True )

    try:
        # 1: Instantiation
        git_ops = GitOps( cwd=cu.get_project_root(), debug=False )
        assert git_ops.cwd == cu.get_project_root()
        assert git_ops.timeout_secs == 30
        assert git_ops._gh_available is None
        print( "✓ GitOps instantiation" )

        # 2: Real get_current_branch (hit actual repo)
        branch = asyncio.run( git_ops.get_current_branch() )
        assert isinstance( branch, str ) and len( branch ) > 0
        print( f"✓ get_current_branch returns [{branch}]" )

        # 3: commit_on_branch with no files (guard path)
        result = asyncio.run( git_ops.commit_on_branch( [], "test" ) )
        assert result[ "success" ] == False
        assert "no files" in result[ "error" ]
        print( "✓ commit_on_branch rejects empty files list" )

        # 4: create_fix_branch with empty slug (guard path)
        result = asyncio.run( git_ops.create_fix_branch( "" ) )
        assert result[ "success" ] == False
        assert "empty slug" in result[ "error" ]
        print( "✓ create_fix_branch rejects empty slug" )

        # 5: gh availability detection cached
        _ = asyncio.run( git_ops.create_pr( "test", "title", "body" ) )
        assert git_ops._gh_available is not None  # Cache populated
        print( f"✓ gh CLI detection cached (available={git_ops._gh_available})" )

        print( "\n✓ BFE GitOps smoke test completed successfully" )

    except Exception as e:
        print( f"\n✗ Smoke test failed: {e}" )
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    quick_smoke_test()
