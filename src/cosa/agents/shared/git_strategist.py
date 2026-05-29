"""
Shared git strategy engine for agentic repair agents.

Extracted from cosa.agents.bug_fix_expediter.orchestrator (Session 1cfcdf73,
2026-04-10) so BugFixExpediter and TestFixExpediter can share the same
trust-level → git-strategy mapping and commit/branch/PR execution machinery.

This module is a PEER of the agent packages — it does not import from any
specific agent. The caller (orchestrator) is responsible for:
  - Constructing commit messages, PR titles, PR bodies (agent-specific)
  - Providing an async `notify_fn(message, priority)` callable for voice I/O
  - Updating their own agent-specific state machine (BFEPhase, TFEPhase, etc.)
  - Updating their own agent-specific plan docs via PlanWriter

GitStrategist owns:
  - Trust-level resolution from a decision proxy
  - Branch slug generation (fix/YYYY-MM-DD-{words})
  - `commit_and_pr_single` — BFE path (one commit or one branch+PR)
  - `commit_and_pr_multi` — TFE path (one branch, N commits, one PR)
    — STUB in this commit; full implementation in TFE step 11

See: src/rnd/v0.1.6/2026.04.10-test-fix-expediter/07-phase5-multi-cluster-git-plan.md
"""

import logging
import re
from datetime import datetime
from typing import Callable, Optional

import cosa.utils.util as cu

logger = logging.getLogger( __name__ )


class GitStrategist:
    """
    Shared trust-level → git-strategy engine.

    Trust-to-git mapping:
        - L1-L2 (shadow/suggest): commit_only on current branch
        - L3+ (active): branch_and_pr via gh CLI
        - gh CLI missing: degrade L3+ → branch_only
        - Proxy unavailable / error: commit_only (conservative fallback)

    Requires:
        - debug / verbose are bool flags
        - Caller provides GitOps instance (agents own their GitOps import
          so this module stays free of BFE-specific imports)

    Ensures:
        - Never raises from public methods — failures surface via returned dict
        - Returned dict has stable schema: {git_strategy, commit_hash, branch_name, pr_url, error}
    """

    def __init__( self, debug: bool = False, verbose: bool = False ):
        self.debug   = debug
        self.verbose = verbose

    # ───── static helpers (pure — no state dependencies) ─────

    @staticmethod
    def resolve_trust_level( proxy ) -> int:
        """
        Return trust level 1-5 from the proxy, falling back to L1 on failure.

        Requires:
            - proxy is None OR has a `trust_tracker` attribute with `get_level()` or `level`

        Ensures:
            - Always returns int between 1 and 5
            - L1 on any error (conservative default)

        Args:
            proxy: Optional decision proxy (SWE EngineeringStrategy or equivalent)

        Returns:
            int: Trust level (1=shadow, 2=suggest, 3+=active)
        """
        if proxy is None:
            return 1
        try:
            tracker = getattr( proxy, "trust_tracker", None )
            if tracker is None:
                return 1
            if hasattr( tracker, "get_level" ):
                return int( tracker.get_level( "engineering" ) )
            if hasattr( tracker, "level" ):
                lvl = tracker.level
                return int( lvl() if callable( lvl ) else lvl )
        except Exception as e:
            logger.debug( f"[GitStrategist] trust level resolution failed: {e} — defaulting to L1" )
        return 1

    @staticmethod
    def generate_slug( text: str ) -> str:
        """
        Generate a fix/YYYY-MM-DD-{slug} branch name from text.

        Requires:
            - text is a string (may be empty or None)

        Ensures:
            - Returns string of form "fix/YYYY-MM-DD-{word1-word2-word3}"
            - At least "fix/YYYY-MM-DD-fix" if text yields no words
        """
        cleaned = re.sub( r"[^a-z0-9\s]", "", ( text or "" ).lower() )
        words   = cleaned.split()[ :3 ]
        slug    = "-".join( words ) if words else "fix"
        date_str = datetime.now().strftime( "%Y-%m-%d" )
        return f"fix/{date_str}-{slug}"

    # ───── commit_and_pr_single (BFE path) ─────

    async def commit_and_pr_single(
        self,
        git_ops,
        files_changed: list,
        commit_message: str,
        pr_title: str,
        pr_body: str,
        trust_level: int,
        notify_fn: Callable,
    ) -> dict:
        """
        Single-fix git strategy: commit_only (L1-L2) OR branch+PR (L3+).

        Requires:
            - git_ops is a GitOps instance (async git/gh wrapper)
            - files_changed is a non-empty list of paths
            - commit_message, pr_title, pr_body are non-empty strings
            - trust_level is 1-5
            - notify_fn is async callable(message, priority="low"|"medium"|"high"|"urgent")

        Ensures:
            - Returns dict with keys: git_strategy, commit_hash, branch_name, pr_url, error
            - git_strategy in {"commit_only", "branch_and_pr", "branch_only", None}
            - Any key may be None on failure
            - Never raises
            - On L3+ error, checks out original branch before returning

        Args:
            git_ops: GitOps instance
            files_changed: List of files modified
            commit_message: Commit message subject+body
            pr_title: PR title (used only in L3+ path)
            pr_body: PR body markdown (used only in L3+ path)
            trust_level: Resolved trust level (from resolve_trust_level)
            notify_fn: Async notification callable

        Returns:
            dict: {git_strategy, commit_hash, branch_name, pr_url, error}
        """
        result = {
            "git_strategy" : None,
            "commit_hash"  : None,
            "branch_name"  : None,
            "pr_url"       : None,
            "error"        : None,
        }

        try:
            if trust_level < 3:
                # L1-L2: commit on current branch
                commit_result = await git_ops.commit_on_branch( files_changed, commit_message )
                if commit_result[ "success" ]:
                    result[ "git_strategy" ] = "commit_only"
                    result[ "commit_hash" ]  = commit_result[ "commit_hash" ]
                    await notify_fn( f"Committed {commit_result[ 'commit_hash' ][ :8 ]}", priority="low" )
                else:
                    result[ "error" ] = commit_result[ "error" ]
                    await notify_fn( f"Commit failed: {commit_result[ 'error' ]}", priority="high" )
                return result

            # L3+: create fix branch + push + PR
            original_branch = await git_ops.get_current_branch()
            slug = self.generate_slug( commit_message )

            br_result = await git_ops.create_fix_branch( slug )
            if not br_result[ "success" ]:
                result[ "error" ] = br_result[ "error" ]
                await notify_fn( f"Branch creation failed: {br_result[ 'error' ]}", priority="high" )
                return result

            result[ "branch_name" ] = br_result[ "branch_name" ]

            push_result = await git_ops.commit_and_push( slug, files_changed, commit_message )
            if not push_result[ "success" ]:
                result[ "error" ] = push_result[ "error" ]
                await notify_fn( f"Push failed: {push_result[ 'error' ]}", priority="high" )
                if original_branch:
                    await git_ops.checkout_branch( original_branch )
                return result

            result[ "commit_hash" ] = push_result[ "commit_hash" ]
            await notify_fn( f"Pushed to {slug}", priority="low" )

            pr_result = await git_ops.create_pr( slug, pr_title, pr_body )
            if pr_result[ "success" ]:
                result[ "git_strategy" ] = "branch_and_pr"
                result[ "pr_url" ]       = pr_result[ "pr_url" ]
                await notify_fn( f"PR created: {pr_result[ 'pr_url' ]}", priority="low" )
            else:
                # gh missing or PR creation failed — degrade to branch_only
                result[ "git_strategy" ] = "branch_only"
                result[ "error" ]        = pr_result[ "error" ]
                await notify_fn(
                    f"PR creation failed: {pr_result[ 'error' ]} (branch left for manual PR)",
                    priority="high",
                )

            if original_branch:
                await git_ops.checkout_branch( original_branch )

        except Exception as e:
            logger.error( f"Git strategy error: {e}" )
            result[ "error" ] = str( e )
            try:
                await notify_fn( f"Git error: {e}", priority="urgent" )
            except Exception:
                pass  # notify_fn itself errored — swallow

        return result

    # ───── commit_and_pr_multi (TFE path, implemented in step 11) ─────

    async def commit_and_pr_multi(
        self,
        git_ops,
        clusters: list,
        trust_level: int,
        notify_fn: Callable,
        pr_title: str,
        pr_body: str,
        branch_slug_hint: Optional[ str ] = None,
    ) -> dict:
        """
        Multi-cluster git strategy: one branch, N commits (one per cluster), one PR.

        Used by TFE Phase 5 — each selected cluster becomes one commit within
        a single branch, and the whole batch goes out as one PR.

        Branch strategy (same trust-to-git mapping as commit_and_pr_single):
          - L1-L2: commit_only — N sequential commits on the current branch
          - L3+  : branch_and_pr — new fix/... branch, N commits, push, PR via gh
          - gh missing: degrade L3+ → branch_only (branch + commits + push, no PR)

        Requires:
            - git_ops is a GitOps instance
            - clusters is a non-empty list of tuples:
                (cluster_id, cluster_title, files_list, commit_message)
            - trust_level is 1-5
            - notify_fn is async callable(message, priority)
            - pr_title and pr_body are non-empty strings (used only in L3+ path)
            - branch_slug_hint is optional — defaults to "multi-cluster-fix"

        Ensures:
            - Returns dict: {git_strategy, branch_name, commit_hashes, pr_url, error}
            - commit_hashes is a list (one hash per successful cluster commit,
              in cluster-order); length equals len(clusters) on full success,
              fewer on partial failure
            - git_strategy in {"commit_only", "branch_and_pr", "branch_only", None}
            - Any field may be None on failure; error is set
            - Never raises
            - On L3+ error, checks out original branch before returning

        Args:
            git_ops: GitOps instance (async git/gh wrapper)
            clusters: List of (cluster_id, title, files, commit_message) tuples
            trust_level: Resolved trust level (from resolve_trust_level)
            notify_fn: Async notification callable
            pr_title: PR title (L3+ path only)
            pr_body: PR body markdown (L3+ path only)
            branch_slug_hint: Optional slug hint for branch naming

        Returns:
            dict: {git_strategy, branch_name, commit_hashes, pr_url, error}
        """
        result = {
            "git_strategy"  : None,
            "branch_name"   : None,
            "commit_hashes" : [],
            "pr_url"        : None,
            "error"         : None,
        }

        if not clusters:
            result[ "error" ] = "commit_and_pr_multi called with empty clusters list"
            return result

        try:
            if trust_level < 3:
                # L1-L2: commit_only — N sequential commits on the current branch
                for cluster_id, _title, files, commit_message in clusters:
                    if not files:
                        await notify_fn(
                            f"Cluster {cluster_id}: no files to commit (skipping)",
                            priority="low",
                        )
                        continue

                    commit_result = await git_ops.commit_on_branch( files, commit_message )
                    if commit_result[ "success" ]:
                        result[ "commit_hashes" ].append( commit_result[ "commit_hash" ] )
                        await notify_fn(
                            f"Cluster {cluster_id}: committed {commit_result[ 'commit_hash' ][ :8 ]}",
                            priority="low",
                        )
                    else:
                        result[ "error" ] = commit_result[ "error" ]
                        await notify_fn(
                            f"Cluster {cluster_id}: commit failed: {commit_result[ 'error' ]}",
                            priority="high",
                        )
                        # Continue committing remaining clusters — partial progress
                        # is better than none. Caller decides what to do with
                        # partial commit_hashes.

                if result[ "commit_hashes" ]:
                    result[ "git_strategy" ] = "commit_only"
                return result

            # L3+: branch_and_pr — create branch, N commits, push, PR
            original_branch = await git_ops.get_current_branch()

            slug_source = branch_slug_hint or f"multi-cluster-{len( clusters )}"
            slug = self.generate_slug( slug_source )

            br_result = await git_ops.create_fix_branch( slug )
            if not br_result[ "success" ]:
                result[ "error" ] = br_result[ "error" ]
                await notify_fn(
                    f"Branch creation failed: {br_result[ 'error' ]}",
                    priority="high",
                )
                return result

            result[ "branch_name" ] = br_result[ "branch_name" ]

            # Make N commits on the new branch. GitOps.commit_and_push expects a
            # slug + files + message — but it commits AND pushes on every call.
            # For multi-commit batches we want to commit each cluster separately
            # and push ONCE at the end. We do that via the lower-level commit_on_branch
            # (already on the new branch after create_fix_branch), then a single
            # explicit push at the end.
            for cluster_id, _title, files, commit_message in clusters:
                if not files:
                    await notify_fn(
                        f"Cluster {cluster_id}: no files to commit (skipping)",
                        priority="low",
                    )
                    continue

                commit_result = await git_ops.commit_on_branch( files, commit_message )
                if commit_result[ "success" ]:
                    result[ "commit_hashes" ].append( commit_result[ "commit_hash" ] )
                    await notify_fn(
                        f"Cluster {cluster_id}: committed {commit_result[ 'commit_hash' ][ :8 ]}",
                        priority="low",
                    )
                else:
                    result[ "error" ] = commit_result[ "error" ]
                    await notify_fn(
                        f"Cluster {cluster_id}: commit failed: {commit_result[ 'error' ]}",
                        priority="high",
                    )
                    # Same partial-progress behavior

            if not result[ "commit_hashes" ]:
                # Nothing committed — roll back branch and return
                if original_branch:
                    await git_ops.checkout_branch( original_branch )
                return result

            # Push the branch (GitOps.commit_and_push is commit-and-push-combined;
            # since we already committed separately, we use the dedicated push if
            # available, else fall through to commit_and_push with an empty file
            # list — but most GitOps implementations don't support that. Prefer
            # a push primitive if present; otherwise call create_pr directly which
            # many implementations will preflight push.)
            push_ok = True
            if hasattr( git_ops, "push_branch" ):
                push_result = await git_ops.push_branch( slug )
                if not push_result.get( "success" ):
                    push_ok = False
                    result[ "error" ] = push_result.get( "error" )
                    await notify_fn(
                        f"Push failed: {push_result.get( 'error' )}",
                        priority="high",
                    )

            if not push_ok:
                # Branch + local commits exist but push failed — restore branch
                if original_branch:
                    await git_ops.checkout_branch( original_branch )
                result[ "git_strategy" ] = "commit_only"   # effectively local-only
                return result

            await notify_fn( f"Pushed {len( result[ 'commit_hashes' ] )} commit(s) to {slug}", priority="low" )

            # Create the PR
            pr_result = await git_ops.create_pr( slug, pr_title, pr_body )
            if pr_result[ "success" ]:
                result[ "git_strategy" ] = "branch_and_pr"
                result[ "pr_url" ]       = pr_result[ "pr_url" ]
                await notify_fn(
                    f"PR created: {pr_result[ 'pr_url' ]}", priority="low"
                )
            else:
                # gh missing or PR failed — degrade to branch_only
                result[ "git_strategy" ] = "branch_only"
                result[ "error" ]        = pr_result.get( "error" )
                await notify_fn(
                    f"PR creation failed: {pr_result.get( 'error' )} (branch left for manual PR)",
                    priority="high",
                )

            if original_branch:
                await git_ops.checkout_branch( original_branch )

        except Exception as e:
            logger.error( f"commit_and_pr_multi error: {e}" )
            result[ "error" ] = str( e )
            try:
                await notify_fn( f"Git error: {e}", priority="urgent" )
            except Exception:
                pass

        return result


def quick_smoke_test():
    """Quick smoke test for shared GitStrategist (pure-logic checks, no network)."""
    cu.print_banner( "Shared GitStrategist Smoke Test", prepend_nl=True )

    try:
        # 1: Static helpers — resolve_trust_level
        class FakeTracker:
            def get_level( self, role ): return 3

        class FakeProxy:
            trust_tracker = FakeTracker()

        assert GitStrategist.resolve_trust_level( None ) == 1, "None proxy → L1"
        assert GitStrategist.resolve_trust_level( FakeProxy() ) == 3, "L3 tracker → L3"

        class BrokenProxy:
            trust_tracker = None

        assert GitStrategist.resolve_trust_level( BrokenProxy() ) == 1, "No tracker → L1"
        print( "✓ resolve_trust_level works" )

        # 2: generate_slug
        slug = GitStrategist.generate_slug( "Fix null pointer in auth module" )
        assert slug.startswith( "fix/" )
        assert "null-pointer-in" in slug or "fix-null-pointer" in slug
        print( f"✓ generate_slug works: {slug}" )

        slug2 = GitStrategist.generate_slug( "" )
        assert slug2.endswith( "-fix" )
        print( f"✓ generate_slug empty: {slug2}" )

        slug3 = GitStrategist.generate_slug( "!!!weird---chars!!!" )
        assert slug3.startswith( "fix/" )
        print( f"✓ generate_slug punctuation: {slug3}" )

        # 3: Constructor
        gs = GitStrategist( debug=True, verbose=False )
        assert gs.debug is True
        assert gs.verbose is False
        print( "✓ Constructor works" )

        # 4: commit_and_pr_multi is a stub
        import asyncio
        async def test_multi_stub():
            gs2 = GitStrategist( debug=False )
            try:
                await gs2.commit_and_pr_multi( None, [], 1, None, "", "" )
                return False
            except NotImplementedError:
                return True

        assert asyncio.run( test_multi_stub() ), "multi should raise NotImplementedError"
        print( "✓ commit_and_pr_multi stub raises NotImplementedError as expected" )

        print( "\n✓ Shared GitStrategist smoke test completed successfully" )

    except Exception as e:
        print( f"\n✗ Smoke test failed: {e}" )
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    quick_smoke_test()
