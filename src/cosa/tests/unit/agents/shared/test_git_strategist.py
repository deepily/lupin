"""
Unit tests for cosa.agents.shared.git_strategist (GitStrategist).

NEW FILE 2026-05-31 by Extra 2 🪨 (CoSA coverage campaign, shared/ lane). GitStrategist
maps trust level → git action (commit_only / branch_and_pr / branch_only) and drives a
GitOps async wrapper. ALL git/gh I/O is boundary-mocked: git_ops is a SimpleNamespace of
AsyncMock methods returning result dicts, notify_fn is an AsyncMock. ZERO real git/gh/
network. The push_branch-present vs -absent arm is controlled by including/omitting that
attribute on the SimpleNamespace (so hasattr() resolves precisely).

STALE-SMOKE FLAG (reported to Tiberius, NOT tripwired — it lives in coverage-excluded
quick_smoke_test): the module header (lines 19-20), the §comment (line 224), and the
smoke test (lines 477-482, asserting commit_and_pr_multi "should raise
NotImplementedError") are stale — commit_and_pr_multi is fully implemented and returns a
dict, never raising. No runtime prod-code bug; doc/smoke drift only.

Must run via run-sdk-cov.sh (shared/__init__ pulls fix_executor → ClaudeAgentOptions).
"""

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from cosa.agents.shared.git_strategist import GitStrategist


def make_git_ops( with_push_branch=True, **overrides ):
    ops = SimpleNamespace()
    ops.commit_on_branch   = AsyncMock( return_value={ "success": True, "commit_hash": "abcdef1234" } )
    ops.get_current_branch = AsyncMock( return_value="main" )
    ops.create_fix_branch  = AsyncMock( return_value={ "success": True, "branch_name": "fix/2026-05-31-x" } )
    ops.commit_and_push    = AsyncMock( return_value={ "success": True, "commit_hash": "abcdef1234" } )
    ops.checkout_branch    = AsyncMock( return_value={ "success": True } )
    ops.create_pr          = AsyncMock( return_value={ "success": True, "pr_url": "http://pr/1" } )
    if with_push_branch:
        ops.push_branch    = AsyncMock( return_value={ "success": True } )
    for k, v in overrides.items():
        setattr( ops, k, v )
    return ops


# ===========================================================================
# resolve_trust_level (static)
# ===========================================================================
class TestResolveTrustLevel( unittest.TestCase ):

    def test_none_proxy( self ):
        self.assertEqual( GitStrategist.resolve_trust_level( None ), 1 )

    def test_tracker_none( self ):
        self.assertEqual( GitStrategist.resolve_trust_level( SimpleNamespace( trust_tracker=None ) ), 1 )

    def test_get_level( self ):
        tracker = SimpleNamespace( get_level=lambda role: 3 )
        self.assertEqual( GitStrategist.resolve_trust_level( SimpleNamespace( trust_tracker=tracker ) ), 3 )

    def test_level_callable( self ):
        tracker = SimpleNamespace( level=lambda: 4 )
        self.assertEqual( GitStrategist.resolve_trust_level( SimpleNamespace( trust_tracker=tracker ) ), 4 )

    def test_level_attribute( self ):
        tracker = SimpleNamespace( level=5 )
        self.assertEqual( GitStrategist.resolve_trust_level( SimpleNamespace( trust_tracker=tracker ) ), 5 )

    def test_tracker_without_level_or_get_level( self ):
        # tracker present but neither attr → falls through to return 1.
        self.assertEqual(
            GitStrategist.resolve_trust_level( SimpleNamespace( trust_tracker=object() ) ), 1
        )

    def test_exception_defaults_to_one( self ):
        tracker = SimpleNamespace( get_level=MagicMock( side_effect=RuntimeError( "boom" ) ) )
        self.assertEqual( GitStrategist.resolve_trust_level( SimpleNamespace( trust_tracker=tracker ) ), 1 )


# ===========================================================================
# generate_slug (static)
# ===========================================================================
class TestGenerateSlug( unittest.TestCase ):

    def test_with_words( self ):
        slug = GitStrategist.generate_slug( "Fix null pointer in auth module" )
        self.assertTrue( slug.startswith( "fix/" ) )
        self.assertIn( "fix-null-pointer", slug )

    def test_empty_falls_back_to_fix( self ):
        self.assertTrue( GitStrategist.generate_slug( "" ).endswith( "-fix" ) )

    def test_none_falls_back_to_fix( self ):
        self.assertTrue( GitStrategist.generate_slug( None ).endswith( "-fix" ) )


# ===========================================================================
# commit_and_pr_single (BFE path)
# ===========================================================================
class TestCommitAndPrSingle( unittest.IsolatedAsyncioTestCase ):

    async def _run( self, git_ops, trust, notify=None ):
        gs = GitStrategist( debug=True )
        notify = notify or AsyncMock()
        return await gs.commit_and_pr_single(
            git_ops=git_ops, files_changed=[ "a.py" ], commit_message="msg",
            pr_title="t", pr_body="b", trust_level=trust, notify_fn=notify,
        ), notify

    async def test_l1_commit_only_success( self ):
        result, _ = await self._run( make_git_ops(), trust=1 )
        self.assertEqual( result[ "git_strategy" ], "commit_only" )
        self.assertEqual( result[ "commit_hash" ], "abcdef1234" )

    async def test_l1_commit_fail( self ):
        ops = make_git_ops()
        ops.commit_on_branch = AsyncMock( return_value={ "success": False, "error": "dirty tree" } )
        result, _ = await self._run( ops, trust=2 )
        self.assertIsNone( result[ "git_strategy" ] )
        self.assertEqual( result[ "error" ], "dirty tree" )

    async def test_l3_branch_create_fail( self ):
        ops = make_git_ops()
        ops.create_fix_branch = AsyncMock( return_value={ "success": False, "error": "no branch" } )
        result, _ = await self._run( ops, trust=3 )
        self.assertEqual( result[ "error" ], "no branch" )
        self.assertIsNone( result[ "git_strategy" ] )

    async def test_l3_push_fail_checks_out_original( self ):
        ops = make_git_ops()
        ops.commit_and_push = AsyncMock( return_value={ "success": False, "error": "push denied" } )
        result, _ = await self._run( ops, trust=3 )
        self.assertEqual( result[ "error" ], "push denied" )
        ops.checkout_branch.assert_awaited_once_with( "main" )

    async def test_l3_push_fail_no_original_branch( self ):
        # get_current_branch "" → 190 `if original_branch:` false (no checkout).
        ops = make_git_ops()
        ops.get_current_branch = AsyncMock( return_value="" )
        ops.commit_and_push = AsyncMock( return_value={ "success": False, "error": "push denied" } )
        result, _ = await self._run( ops, trust=3 )
        ops.checkout_branch.assert_not_awaited()

    async def test_l3_full_success_pr( self ):
        ops = make_git_ops()
        result, _ = await self._run( ops, trust=4 )
        self.assertEqual( result[ "git_strategy" ], "branch_and_pr" )
        self.assertEqual( result[ "pr_url" ], "http://pr/1" )
        ops.checkout_branch.assert_awaited_once_with( "main" )

    async def test_l3_pr_fail_degrades_branch_only_no_original( self ):
        # pr fail → branch_only; original_branch "" → 211 `if original_branch:` false.
        ops = make_git_ops()
        ops.get_current_branch = AsyncMock( return_value="" )
        ops.create_pr = AsyncMock( return_value={ "success": False, "error": "gh missing" } )
        result, _ = await self._run( ops, trust=5 )
        self.assertEqual( result[ "git_strategy" ], "branch_only" )
        self.assertEqual( result[ "error" ], "gh missing" )
        ops.checkout_branch.assert_not_awaited()

    async def test_exception_path_notify_ok( self ):
        ops = make_git_ops()
        ops.commit_on_branch = AsyncMock( side_effect=RuntimeError( "git exploded" ) )
        result, notify = await self._run( ops, trust=1 )
        self.assertEqual( result[ "error" ], "git exploded" )
        notify.assert_awaited()

    async def test_exception_path_notify_also_errors( self ):
        # both git_ops AND notify_fn raise → inner except swallows (219-220).
        ops = make_git_ops()
        ops.commit_on_branch = AsyncMock( side_effect=RuntimeError( "git exploded" ) )
        notify = AsyncMock( side_effect=RuntimeError( "voice down" ) )
        result, _ = await self._run( ops, trust=1, notify=notify )
        self.assertEqual( result[ "error" ], "git exploded" )


# ===========================================================================
# commit_and_pr_multi (TFE path)
# ===========================================================================
class TestCommitAndPrMulti( unittest.IsolatedAsyncioTestCase ):

    async def _run( self, git_ops, clusters, trust, notify=None, hint=None ):
        gs = GitStrategist( debug=False )
        notify = notify or AsyncMock()
        return await gs.commit_and_pr_multi(
            git_ops=git_ops, clusters=clusters, trust_level=trust,
            notify_fn=notify, pr_title="t", pr_body="b", branch_slug_hint=hint,
        ), notify

    async def test_empty_clusters_errors( self ):
        result, _ = await self._run( make_git_ops(), clusters=[ ], trust=1 )
        self.assertIn( "empty clusters", result[ "error" ] )

    async def test_l1_commit_only_with_skip_and_fail( self ):
        ops = make_git_ops()
        # cluster 2 commit fails; cluster 3 has no files (skip); cluster 1 ok.
        ops.commit_on_branch = AsyncMock( side_effect=[
            { "success": True, "commit_hash": "hash1aaaa" },
            { "success": False, "error": "conflict" },
        ] )
        clusters = [
            ( "c1", "t1", [ "a.py" ], "m1" ),
            ( "c2", "t2", [ "b.py" ], "m2" ),
            ( "c3", "t3", [ ], "m3" ),          # no files → skip
        ]
        result, _ = await self._run( ops, clusters, trust=1 )
        self.assertEqual( result[ "git_strategy" ], "commit_only" )
        self.assertEqual( result[ "commit_hashes" ], [ "hash1aaaa" ] )
        self.assertEqual( result[ "error" ], "conflict" )

    async def test_l1_all_skipped_no_strategy( self ):
        # single no-files cluster → nothing committed → git_strategy stays None.
        result, _ = await self._run( make_git_ops(), [ ( "c1", "t", [ ], "m" ) ], trust=1 )
        self.assertIsNone( result[ "git_strategy" ] )
        self.assertEqual( result[ "commit_hashes" ], [ ] )

    async def test_l3_branch_create_fail( self ):
        ops = make_git_ops()
        ops.create_fix_branch = AsyncMock( return_value={ "success": False, "error": "no branch" } )
        result, _ = await self._run( ops, [ ( "c1", "t", [ "a.py" ], "m" ) ], trust=3 )
        self.assertEqual( result[ "error" ], "no branch" )

    async def test_l3_full_success_with_push_branch( self ):
        ops = make_git_ops( with_push_branch=True )
        clusters = [ ( "c1", "t1", [ "a.py" ], "m1" ), ( "c2", "t2", [ "b.py" ], "m2" ) ]
        result, _ = await self._run( ops, clusters, trust=3, hint="my-fix" )
        self.assertEqual( result[ "git_strategy" ], "branch_and_pr" )
        self.assertEqual( len( result[ "commit_hashes" ] ), 2 )
        self.assertEqual( result[ "pr_url" ], "http://pr/1" )
        ops.push_branch.assert_awaited_once()

    async def test_l3_no_push_branch_attr_proceeds_to_pr( self ):
        # hasattr(git_ops, "push_branch") False → push_ok stays True → create_pr.
        ops = make_git_ops( with_push_branch=False )
        result, _ = await self._run( ops, [ ( "c1", "t", [ "a.py" ], "m" ) ], trust=3 )
        self.assertEqual( result[ "git_strategy" ], "branch_and_pr" )

    async def test_l3_no_commits_rolls_back( self ):
        # all clusters no-files in L3 → no commit_hashes → checkout original + return.
        ops = make_git_ops()
        result, _ = await self._run( ops, [ ( "c1", "t", [ ], "m" ) ], trust=3 )
        self.assertEqual( result[ "commit_hashes" ], [ ] )
        ops.checkout_branch.assert_awaited_once_with( "main" )

    async def test_l3_commit_fail_in_loop( self ):
        ops = make_git_ops()
        ops.commit_on_branch = AsyncMock( return_value={ "success": False, "error": "conflict" } )
        result, _ = await self._run( ops, [ ( "c1", "t", [ "a.py" ], "m" ) ], trust=3 )
        # no successful commits → rolled back
        self.assertEqual( result[ "commit_hashes" ], [ ] )

    async def test_l3_push_fail_restores_branch( self ):
        ops = make_git_ops( with_push_branch=True )
        ops.push_branch = AsyncMock( return_value={ "success": False, "error": "push denied" } )
        result, _ = await self._run( ops, [ ( "c1", "t", [ "a.py" ], "m" ) ], trust=3 )
        self.assertEqual( result[ "git_strategy" ], "commit_only" )   # effectively local-only
        self.assertEqual( result[ "error" ], "push denied" )
        ops.checkout_branch.assert_awaited_once_with( "main" )

    async def test_l3_pr_fail_degrades_branch_only( self ):
        ops = make_git_ops( with_push_branch=True )
        ops.create_pr = AsyncMock( return_value={ "success": False, "error": "gh missing" } )
        result, _ = await self._run( ops, [ ( "c1", "t", [ "a.py" ], "m" ) ], trust=3 )
        self.assertEqual( result[ "git_strategy" ], "branch_only" )
        self.assertEqual( result[ "error" ], "gh missing" )

    async def test_l3_no_commits_rollback_no_original( self ):
        # original_branch "" → 370->372 `if original_branch:` false (skip checkout).
        ops = make_git_ops()
        ops.get_current_branch = AsyncMock( return_value="" )
        result, _ = await self._run( ops, [ ( "c1", "t", [ ], "m" ) ], trust=3 )
        self.assertEqual( result[ "commit_hashes" ], [ ] )
        ops.checkout_branch.assert_not_awaited()

    async def test_l3_push_fail_no_original( self ):
        # original_branch "" → 393->395 `if original_branch:` false on push-fail restore.
        ops = make_git_ops( with_push_branch=True )
        ops.get_current_branch = AsyncMock( return_value="" )
        ops.push_branch = AsyncMock( return_value={ "success": False, "error": "push denied" } )
        result, _ = await self._run( ops, [ ( "c1", "t", [ "a.py" ], "m" ) ], trust=3 )
        self.assertEqual( result[ "git_strategy" ], "commit_only" )
        ops.checkout_branch.assert_not_awaited()

    async def test_l3_success_no_original( self ):
        # original_branch "" → 417->428 `if original_branch:` false at end.
        ops = make_git_ops( with_push_branch=True )
        ops.get_current_branch = AsyncMock( return_value="" )
        result, _ = await self._run( ops, [ ( "c1", "t", [ "a.py" ], "m" ) ], trust=3 )
        self.assertEqual( result[ "git_strategy" ], "branch_and_pr" )
        ops.checkout_branch.assert_not_awaited()

    async def test_exception_path_notify_ok( self ):
        ops = make_git_ops()
        ops.get_current_branch = AsyncMock( side_effect=RuntimeError( "git exploded" ) )
        result, notify = await self._run( ops, [ ( "c1", "t", [ "a.py" ], "m" ) ], trust=3 )
        self.assertEqual( result[ "error" ], "git exploded" )
        notify.assert_awaited()

    async def test_exception_path_notify_also_errors( self ):
        ops = make_git_ops()
        ops.get_current_branch = AsyncMock( side_effect=RuntimeError( "git exploded" ) )
        notify = AsyncMock( side_effect=RuntimeError( "voice down" ) )
        result, _ = await self._run( ops, [ ( "c1", "t", [ "a.py" ], "m" ) ], trust=3, notify=notify )
        self.assertEqual( result[ "error" ], "git exploded" )


if __name__ == "__main__":
    unittest.main()
