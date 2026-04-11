"""
Unit tests for TFE Phase 5 multi-cluster git + shared GitStrategist.commit_and_pr_multi.

Session 1cfcdf73 (2026-04-10): Step 11 implementation tests. Mocks GitOps
for offline-safe runs.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cosa.agents.bug_fix_expediter.state import FixResult
from cosa.agents.shared.git_strategist import GitStrategist
from cosa.agents.test_fix_expediter.config import TestFixExpediterConfig
from cosa.agents.test_fix_expediter.orchestrator import TFEOrchestrator
from cosa.agents.test_fix_expediter.state import (
    FailureCluster,
    TFEProposedFix,
    TestDiagnosisResult,
    TestRemediationContext,
)


# ─────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────


def _make_git_ops_mock( commit_success: bool = True, pr_success: bool = True, push_success: bool = True ):
    """Build a mock GitOps object with configurable success behavior."""
    mock = MagicMock()
    mock.get_current_branch = AsyncMock( return_value="main" )
    mock.commit_on_branch = AsyncMock(
        side_effect=lambda files, msg: {
            "success": commit_success,
            "commit_hash": f"abc{hash( msg ) % 10000:04d}",
            "error": None if commit_success else "commit failed",
        }
    )
    mock.create_fix_branch = AsyncMock(
        return_value={ "success": True, "branch_name": "fix/2026-04-10-tfe-mixed-3-clusters", "error": None }
    )
    mock.push_branch = AsyncMock(
        return_value={ "success": push_success, "error": None if push_success else "push failed" }
    )
    mock.create_pr = AsyncMock(
        return_value={
            "success": pr_success,
            "pr_url": "https://github.com/deepily/lupin/pull/1234" if pr_success else None,
            "error": None if pr_success else "gh not found",
        }
    )
    mock.checkout_branch = AsyncMock( return_value={ "success": True } )
    return mock


async def _noop_notify( *args, **kwargs ):
    pass


# ─────────────────────────────────────────────────────────────────────────
# GitStrategist.commit_and_pr_multi tests
# ─────────────────────────────────────────────────────────────────────────


class TestCommitAndPrMultiL1:
    """L1-L2 path: commit_only, N sequential commits on the current branch."""

    @pytest.mark.asyncio
    async def test_all_clusters_commit_success( self ):
        strategist = GitStrategist( debug=False )
        git_ops = _make_git_ops_mock( commit_success=True )

        clusters = [
            ( "C1", "Fix auth", [ "src/auth.py" ], "fix(tfe): C1 Fix auth" ),
            ( "C2", "Fix queue", [ "src/queue.py" ], "fix(tfe): C2 Fix queue" ),
            ( "C3", "Fix db", [ "src/db.py" ], "fix(tfe): C3 Fix db" ),
        ]

        result = await strategist.commit_and_pr_multi(
            git_ops=git_ops,
            clusters=clusters,
            trust_level=1,
            notify_fn=_noop_notify,
            pr_title="x", pr_body="y",
        )

        assert result[ "git_strategy" ] == "commit_only"
        assert len( result[ "commit_hashes" ] ) == 3
        assert result[ "branch_name" ] is None
        assert result[ "pr_url" ] is None
        assert result[ "error" ] is None
        # Verify N commit_on_branch calls
        assert git_ops.commit_on_branch.call_count == 3
        # No branch creation or push in L1 path
        git_ops.create_fix_branch.assert_not_called()
        git_ops.create_pr.assert_not_called()

    @pytest.mark.asyncio
    async def test_empty_files_skipped_but_continues( self ):
        strategist = GitStrategist( debug=False )
        git_ops = _make_git_ops_mock( commit_success=True )

        clusters = [
            ( "C1", "Fix 1", [ "src/a.py" ], "msg1" ),
            ( "C2", "Fix 2", [], "msg2" ),    # no files
            ( "C3", "Fix 3", [ "src/b.py" ], "msg3" ),
        ]

        result = await strategist.commit_and_pr_multi(
            git_ops=git_ops, clusters=clusters, trust_level=1,
            notify_fn=_noop_notify, pr_title="x", pr_body="y",
        )

        assert len( result[ "commit_hashes" ] ) == 2  # C1 + C3
        assert git_ops.commit_on_branch.call_count == 2

    @pytest.mark.asyncio
    async def test_commit_failure_continues_partial( self ):
        """If one commit fails, the others still happen and partial progress is returned."""
        strategist = GitStrategist( debug=False )

        mock = MagicMock()
        mock.get_current_branch = AsyncMock( return_value="main" )

        # C1 succeeds, C2 fails, C3 succeeds
        commit_results = [
            { "success": True, "commit_hash": "aaaa", "error": None },
            { "success": False, "commit_hash": None, "error": "merge conflict" },
            { "success": True, "commit_hash": "cccc", "error": None },
        ]
        mock.commit_on_branch = AsyncMock( side_effect=commit_results )

        clusters = [
            ( "C1", "x", [ "a" ], "m1" ),
            ( "C2", "y", [ "b" ], "m2" ),
            ( "C3", "z", [ "c" ], "m3" ),
        ]

        result = await strategist.commit_and_pr_multi(
            git_ops=mock, clusters=clusters, trust_level=1,
            notify_fn=_noop_notify, pr_title="x", pr_body="y",
        )

        assert len( result[ "commit_hashes" ] ) == 2
        assert result[ "commit_hashes" ] == [ "aaaa", "cccc" ]
        assert result[ "error" ] == "merge conflict"
        assert result[ "git_strategy" ] == "commit_only"

    @pytest.mark.asyncio
    async def test_empty_clusters_list( self ):
        strategist = GitStrategist( debug=False )
        result = await strategist.commit_and_pr_multi(
            git_ops=_make_git_ops_mock(),
            clusters=[],
            trust_level=1,
            notify_fn=_noop_notify,
            pr_title="x", pr_body="y",
        )
        assert result[ "error" ] is not None
        assert result[ "git_strategy" ] is None


class TestCommitAndPrMultiL3:
    """L3+ path: branch_and_pr via gh CLI."""

    @pytest.mark.asyncio
    async def test_full_success_branch_and_pr( self ):
        strategist = GitStrategist( debug=False )
        git_ops = _make_git_ops_mock( commit_success=True, pr_success=True, push_success=True )

        clusters = [
            ( "C1", "Fix 1", [ "src/a.py" ], "msg1" ),
            ( "C2", "Fix 2", [ "src/b.py" ], "msg2" ),
        ]

        result = await strategist.commit_and_pr_multi(
            git_ops=git_ops, clusters=clusters, trust_level=3,
            notify_fn=_noop_notify,
            pr_title="TFE Fix Title", pr_body="TFE Fix Body",
            branch_slug_hint="tfe-unit-2-clusters",
        )

        assert result[ "git_strategy" ] == "branch_and_pr"
        assert len( result[ "commit_hashes" ] ) == 2
        assert result[ "branch_name" ] == "fix/2026-04-10-tfe-mixed-3-clusters"
        assert result[ "pr_url" ] == "https://github.com/deepily/lupin/pull/1234"
        assert result[ "error" ] is None
        # Branch + push + PR invoked
        git_ops.create_fix_branch.assert_called_once()
        git_ops.push_branch.assert_called_once()
        git_ops.create_pr.assert_called_once()
        # Original branch restored at end
        git_ops.checkout_branch.assert_called_with( "main" )

    @pytest.mark.asyncio
    async def test_branch_creation_failure( self ):
        strategist = GitStrategist( debug=False )
        git_ops = _make_git_ops_mock()
        git_ops.create_fix_branch = AsyncMock(
            return_value={ "success": False, "branch_name": None, "error": "branch exists" }
        )

        clusters = [ ( "C1", "x", [ "a" ], "m" ) ]
        result = await strategist.commit_and_pr_multi(
            git_ops=git_ops, clusters=clusters, trust_level=3,
            notify_fn=_noop_notify, pr_title="x", pr_body="y",
        )

        assert result[ "error" ] == "branch exists"
        assert result[ "git_strategy" ] is None
        assert result[ "branch_name" ] is None
        assert result[ "commit_hashes" ] == []
        # No push or PR attempted
        git_ops.push_branch.assert_not_called()
        git_ops.create_pr.assert_not_called()

    @pytest.mark.asyncio
    async def test_push_failure_restores_branch( self ):
        strategist = GitStrategist( debug=False )
        git_ops = _make_git_ops_mock( commit_success=True, push_success=False )

        clusters = [ ( "C1", "x", [ "a" ], "m" ) ]
        result = await strategist.commit_and_pr_multi(
            git_ops=git_ops, clusters=clusters, trust_level=3,
            notify_fn=_noop_notify, pr_title="x", pr_body="y",
        )

        assert result[ "git_strategy" ] == "commit_only"  # degrades to local-only
        assert result[ "error" ] == "push failed"
        # Branch restored
        git_ops.checkout_branch.assert_called_with( "main" )
        # PR not attempted
        git_ops.create_pr.assert_not_called()

    @pytest.mark.asyncio
    async def test_gh_missing_degrades_to_branch_only( self ):
        strategist = GitStrategist( debug=False )
        git_ops = _make_git_ops_mock( commit_success=True, push_success=True, pr_success=False )

        clusters = [ ( "C1", "x", [ "a" ], "m" ) ]
        result = await strategist.commit_and_pr_multi(
            git_ops=git_ops, clusters=clusters, trust_level=3,
            notify_fn=_noop_notify, pr_title="x", pr_body="y",
        )

        assert result[ "git_strategy" ] == "branch_only"
        assert result[ "pr_url" ] is None
        assert result[ "error" ] == "gh not found"
        assert len( result[ "commit_hashes" ] ) == 1


# ─────────────────────────────────────────────────────────────────────────
# TFE Orchestrator Phase 5 tests
# ─────────────────────────────────────────────────────────────────────────


def _make_orchestrator( dry_run: bool = True, trust_mode: str = "inherit" ):
    ctx = TestRemediationContext(
        source_test_suite_job_id = "ts-abc12345",
        snapshot_path            = "p",
        snapshot                 = { "schema_version": "1.0" },
        suites_run               = [ "unit" ],
        summary                  = { "all_passed": False, "total_failed": 2 },
        failures                 = [
            {
                "classname": "src.tests.unit.test_auth.TestLogin",
                "name": "test_ok", "type": "FAILED",
                "message": "assert 401 == 200",
                "traceback": 'File "src/cosa/auth/tokens.py", line 42',
            },
            {
                "classname": "src.tests.unit.test_queue.TestQueue",
                "name": "test_push", "type": "FAILED",
                "message": "assert 0 == 1",
                "traceback": 'File "src/cosa/rest/queue.py", line 87',
            },
        ],
        original_test_types      = [ "unit" ],
        user_id                  = "u1",
        user_email               = "t@t.com",
        session_id               = "s1",
    )
    config = TestFixExpediterConfig( trust_mode=trust_mode )
    return TFEOrchestrator(
        remediation_context=ctx,
        config=config,
        user_id="u1",
        user_email="t@t.com",
        session_id="s1",
        job_id="tfe-smoke",
        dry_run=dry_run,
        debug=False,
    )


def _setup_phase5_state( orch, k: int = 2, all_success: bool = True ):
    """Inject clusters, diagnoses, selected_fixes, fix_results, files_changed."""
    orch.clusters = [
        FailureCluster(
            cluster_id=f"C{i+1}", failure_indices=[ i ],
            shared_error_signature=f"sig{i+1}",
        )
        for i in range( k )
    ]
    orch.diagnoses = {
        c.cluster_id: TestDiagnosisResult(
            cluster_id=c.cluster_id, root_cause="x",
            error_category="code_bug", confidence=0.8,
        )
        for c in orch.clusters
    }
    orch.selected_fixes = [
        TFEProposedFix(
            cluster_id=c.cluster_id, title=f"Fix {c.cluster_id}",
            description="desc", fix_type="code_patch", confidence=0.85,
            risk_level="low", estimated_effort="minutes",
            changes=[ { "file": f"src/foo_{c.cluster_id}.py", "action": "modify", "description": "x" } ],
        )
        for c in orch.clusters
    ]
    orch.fix_results = [
        FixResult( applied=True, success=all_success, details="ok" )
        for _ in orch.clusters
    ]
    orch.files_changed_by_cluster = {
        c.cluster_id: [ f"src/foo_{c.cluster_id}.py" ]
        for c in orch.clusters
    }


class TestPhase5GitHelpers:

    def test_suite_abbrev_single( self ):
        assert TFEOrchestrator._suite_abbrev( [ "unit" ] ) == "unit"

    def test_suite_abbrev_mixed( self ):
        assert TFEOrchestrator._suite_abbrev( [ "unit", "e2e" ] ) == "mixed"

    def test_suite_abbrev_empty( self ):
        assert TFEOrchestrator._suite_abbrev( [] ) == "none"

    def test_build_commit_message( self ):
        fix = TFEProposedFix(
            cluster_id="C1", title="Short title",
            description="Longer description goes here",
            fix_type="code_patch", confidence=0.85,
            risk_level="low", estimated_effort="minutes",
        )
        msg = TFEOrchestrator._build_tfe_commit_message( fix )
        assert "fix(tfe): C1 Short title" in msg
        assert "Confidence: 85%" in msg
        assert "Risk: low" in msg
        assert "Longer description" in msg

    def test_resolve_tfe_trust_level( self ):
        orch = _make_orchestrator( trust_mode="inherit" )
        assert orch._resolve_tfe_trust_level() == 1
        orch = _make_orchestrator( trust_mode="fixed_l1" )
        assert orch._resolve_tfe_trust_level() == 1
        orch = _make_orchestrator( trust_mode="fixed_l3" )
        assert orch._resolve_tfe_trust_level() == 3
        orch = _make_orchestrator( trust_mode="shadow" )
        assert orch._resolve_tfe_trust_level() == 1
        orch = _make_orchestrator( trust_mode="unknown" )
        assert orch._resolve_tfe_trust_level() == 1

    def test_render_git_summary( self ):
        summary = TFEOrchestrator._render_git_summary( {
            "git_strategy": "branch_and_pr",
            "branch_name": "fix/2026-04-10-tfe-unit-2-clusters",
            "commit_hashes": [ "abc12345", "def67890" ],
            "pr_url": "https://github.com/x/y/pull/1",
            "error": None,
        } )
        assert "branch_and_pr" in summary
        assert "fix/2026-04-10-tfe-unit-2-clusters" in summary
        assert "abc12345" in summary
        assert "https://github.com/x/y/pull/1" in summary


class TestPhase5GitOrchestrator:

    @pytest.mark.asyncio
    async def test_dry_run_synthetic_result( self ):
        orch = _make_orchestrator( dry_run=True )
        _setup_phase5_state( orch, k=2 )

        result = await orch.run_phase5_git()

        assert result[ "git_strategy" ] == "dry_run"
        assert len( result[ "commit_hashes" ] ) == 2
        assert orch.branch_name is not None
        assert orch.pr_url is None

    @pytest.mark.asyncio
    async def test_no_successful_fixes_skips( self ):
        orch = _make_orchestrator( dry_run=True )
        _setup_phase5_state( orch, k=2, all_success=False )

        result = await orch.run_phase5_git()

        assert result[ "git_strategy" ] is None
        assert result[ "commit_hashes" ] == []
        assert orch.branch_name is None

    @pytest.mark.asyncio
    async def test_missing_files_skipped_per_cluster( self ):
        orch = _make_orchestrator( dry_run=True )
        _setup_phase5_state( orch, k=2 )
        # Clear C1's files — only C2 should be committed
        orch.files_changed_by_cluster[ "C1" ] = []

        result = await orch.run_phase5_git()

        assert result[ "git_strategy" ] == "dry_run"
        assert len( result[ "commit_hashes" ] ) == 1   # only C2

    @pytest.mark.asyncio
    async def test_real_git_l1_path_mocked( self ):
        """Non-dry-run path with mocked GitOps + GitStrategist."""
        orch = _make_orchestrator( dry_run=False, trust_mode="fixed_l1" )
        _setup_phase5_state( orch, k=2 )

        mock_git_ops = _make_git_ops_mock( commit_success=True )

        with patch(
            "cosa.agents.bug_fix_expediter.git_ops.GitOps",
            return_value=mock_git_ops,
        ):
            result = await orch.run_phase5_git()

        assert result[ "git_strategy" ] == "commit_only"
        assert len( result[ "commit_hashes" ] ) == 2
        assert orch.commit_hashes == result[ "commit_hashes" ]
