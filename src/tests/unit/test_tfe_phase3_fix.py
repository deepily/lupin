"""
Unit tests for TFE Phase 3 fix delegation.

Session 1cfcdf73 (2026-04-10): Step 10 implementation tests. Mocks the
shared FixExecutor to verify Phase 3 orchestrator wiring, continue-on-failure
semantics, and dry-run short-circuit.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cosa.agents.bug_fix_expediter.state import FixResult
from cosa.agents.test_fix_expediter.config import TestFixExpediterConfig
from cosa.agents.test_fix_expediter.orchestrator import TFEOrchestrator
from cosa.agents.test_fix_expediter.state import (
    FailureCluster,
    TFEPhase,
    TFEProposedFix,
    TestDiagnosisResult,
    TestRemediationContext,
)


def _make_ctx():
    return TestRemediationContext(
        source_test_suite_job_id = "ts-test",
        snapshot_path            = "p",
        snapshot                 = { "schema_version": "1.0" },
        suites_run               = [ "unit" ],
        summary                  = { "all_passed": False, "total_failed": 2 },
        failures                 = [
            {
                "classname": "src.tests.unit.test_auth.TestLogin",
                "name": "test_ok", "type": "FAILED",
                "message": "assert 401 == 200",
                "traceback": 'File "src/cosa/auth/tokens.py", line 42, in refresh',
            },
            {
                "classname": "src.tests.unit.test_queue.TestQueue",
                "name": "test_push", "type": "FAILED",
                "message": "assert 0 == 1",
                "traceback": 'File "src/cosa/rest/queue.py", line 87, in push',
            },
        ],
        original_test_types      = [ "unit" ],
        user_id                  = "u1",
        user_email               = "t@t.com",
        session_id               = "s1",
    )


def _make_orchestrator( dry_run: bool = False, **config_overrides ):
    ctx = _make_ctx()
    config = TestFixExpediterConfig( **config_overrides )
    return TFEOrchestrator(
        remediation_context = ctx,
        config              = config,
        user_id             = "u1",
        user_email          = "t@t.com",
        session_id          = "s1",
        job_id              = "tfe-smoke",
        dry_run             = dry_run,
        debug               = False,
    )


def _setup_clusters_and_diagnoses( orch, k: int = 2 ):
    """Inject K clusters, matching diagnoses, and matching selected fixes."""
    orch.clusters = [
        FailureCluster(
            cluster_id=f"C{i+1}",
            failure_indices=[ i ],
            shared_error_signature=f"sig{i+1}",
        )
        for i in range( k )
    ]
    orch.diagnoses = {
        c.cluster_id: TestDiagnosisResult(
            cluster_id=c.cluster_id,
            root_cause=f"root cause {c.cluster_id}",
            error_category="code_bug",
            confidence=0.8,
        )
        for c in orch.clusters
    }
    orch.selected_fixes = [
        TFEProposedFix(
            cluster_id=c.cluster_id,
            title=f"Fix {c.cluster_id}",
            description=f"Description {c.cluster_id}",
            fix_type="code_patch",
            confidence=0.85,
            risk_level="low",
            estimated_effort="minutes",
            changes=[ { "file": f"src/foo_{i}.py", "action": "modify", "description": "x" } ],
        )
        for i, c in enumerate( orch.clusters )
    ]


class TestPhase3FixHappyPath:

    @pytest.mark.asyncio
    async def test_no_selected_fixes_empty_result( self ):
        orch = _make_orchestrator( dry_run=False )
        _setup_clusters_and_diagnoses( orch )
        orch.selected_fixes = []   # nothing selected

        results = await orch.run_phase3_fix()

        assert results == []
        assert orch.fix_results == []
        assert orch.current_phase == TFEPhase.FIXING

    @pytest.mark.asyncio
    async def test_sdk_unavailable_empty_result( self ):
        orch = _make_orchestrator( dry_run=False )
        _setup_clusters_and_diagnoses( orch )

        with patch(
            "cosa.agents.test_fix_expediter.orchestrator.SDK_AVAILABLE", False
        ):
            results = await orch.run_phase3_fix()

        assert results == []

    @pytest.mark.asyncio
    async def test_dry_run_synthetic_success( self ):
        """In dry_run, each selected fix gets a synthetic success FixResult.

        Files are synthesized from each proposal's `changes` list so Phase 5
        has non-empty file lists to walk through its happy path.
        """
        orch = _make_orchestrator( dry_run=True )
        _setup_clusters_and_diagnoses( orch, k=3 )

        results = await orch.run_phase3_fix()

        assert len( results ) == 3
        assert all( r.success is True for r in results )
        assert all( r.applied is False for r in results )
        assert all( "dry_run" in r.details for r in results )
        # files_changed_by_cluster is synthesized from proposal.changes
        assert set( orch.files_changed_by_cluster.keys() ) == { "C1", "C2", "C3" }
        # Each cluster has at least one synthesized file (from _setup helper's changes list)
        for cluster_id, files in orch.files_changed_by_cluster.items():
            assert len( files ) >= 1, f"Cluster {cluster_id} should have synthesized files from proposal.changes"
            assert all( isinstance( f, str ) for f in files )

    @pytest.mark.asyncio
    async def test_happy_path_all_clusters_succeed( self ):
        """Mock FixExecutor returns success for every cluster."""
        orch = _make_orchestrator( dry_run=False )
        _setup_clusters_and_diagnoses( orch, k=2 )

        async def mock_execute_fix( diagnosis, selected_fix ):
            return (
                FixResult(
                    applied=True, success=True,
                    details=f"Fixed {selected_fix.cluster_id}",
                    retry_eligible=True,
                ),
                [ f"src/foo_{selected_fix.cluster_id}.py" ],
            )

        mock_executor_cls = MagicMock()
        mock_instance = MagicMock()
        mock_instance.execute_fix = AsyncMock( side_effect=mock_execute_fix )
        mock_executor_cls.return_value = mock_instance

        with patch(
            "cosa.agents.shared.fix_executor.FixExecutor", mock_executor_cls
        ):
            results = await orch.run_phase3_fix()

        assert len( results ) == 2
        assert all( r.success for r in results )
        assert orch.files_changed_by_cluster[ "C1" ] == [ "src/foo_C1.py" ]
        assert orch.files_changed_by_cluster[ "C2" ] == [ "src/foo_C2.py" ]
        # Executor was constructed twice (once per cluster)
        assert mock_executor_cls.call_count == 2

    @pytest.mark.asyncio
    async def test_partial_success_continues( self ):
        """With continue_on_cluster_failure=True (default), a failed cluster does NOT abort remaining."""
        orch = _make_orchestrator( dry_run=False, continue_on_cluster_failure=True )
        _setup_clusters_and_diagnoses( orch, k=3 )

        async def mock_execute_fix( diagnosis, selected_fix ):
            # C2 fails, C1 + C3 succeed
            if selected_fix.cluster_id == "C2":
                return (
                    FixResult( applied=True, success=False, details="tests still failing" ),
                    [],
                )
            return (
                FixResult( applied=True, success=True, details="ok" ),
                [ f"src/foo.py" ],
            )

        mock_executor_cls = MagicMock()
        mock_instance = MagicMock()
        mock_instance.execute_fix = AsyncMock( side_effect=mock_execute_fix )
        mock_executor_cls.return_value = mock_instance

        with patch(
            "cosa.agents.shared.fix_executor.FixExecutor", mock_executor_cls
        ):
            results = await orch.run_phase3_fix()

        # All 3 attempted
        assert len( results ) == 3
        # 2 succeeded, 1 failed
        assert sum( 1 for r in results if r.success ) == 2

    @pytest.mark.asyncio
    async def test_abort_on_first_failure( self ):
        """With continue_on_cluster_failure=False, first failure aborts remaining clusters."""
        orch = _make_orchestrator( dry_run=False, continue_on_cluster_failure=False )
        _setup_clusters_and_diagnoses( orch, k=3 )

        async def mock_execute_fix( diagnosis, selected_fix ):
            if selected_fix.cluster_id == "C1":
                return (
                    FixResult( applied=True, success=False, details="failed" ),
                    [],
                )
            return (
                FixResult( applied=True, success=True, details="ok" ),
                [],
            )

        mock_executor_cls = MagicMock()
        mock_instance = MagicMock()
        mock_instance.execute_fix = AsyncMock( side_effect=mock_execute_fix )
        mock_executor_cls.return_value = mock_instance

        with patch(
            "cosa.agents.shared.fix_executor.FixExecutor", mock_executor_cls
        ):
            results = await orch.run_phase3_fix()

        # Only C1 processed, C2 + C3 aborted
        assert len( results ) == 1
        assert results[ 0 ].success is False

    @pytest.mark.asyncio
    async def test_executor_exception_wrapped_as_failure( self ):
        """If FixExecutor.execute_fix raises, it's caught and turned into a FixResult."""
        orch = _make_orchestrator( dry_run=False )
        _setup_clusters_and_diagnoses( orch, k=2 )

        async def mock_execute_fix( diagnosis, selected_fix ):
            if selected_fix.cluster_id == "C1":
                raise RuntimeError( "simulated executor error" )
            return (
                FixResult( applied=True, success=True, details="ok" ),
                [],
            )

        mock_executor_cls = MagicMock()
        mock_instance = MagicMock()
        mock_instance.execute_fix = AsyncMock( side_effect=mock_execute_fix )
        mock_executor_cls.return_value = mock_instance

        with patch(
            "cosa.agents.shared.fix_executor.FixExecutor", mock_executor_cls
        ):
            results = await orch.run_phase3_fix()

        assert len( results ) == 2
        assert results[ 0 ].success is False
        assert "simulated executor error" in results[ 0 ].details
        assert results[ 1 ].success is True

    @pytest.mark.asyncio
    async def test_missing_cluster_skipped( self ):
        """If a proposal references a cluster that doesn't exist, skip it."""
        orch = _make_orchestrator( dry_run=False )
        _setup_clusters_and_diagnoses( orch, k=1 )
        # Add an orphan proposal referencing C99 (no cluster)
        orch.selected_fixes.append(
            TFEProposedFix(
                cluster_id="C99", title="orphan", description="x",
                fix_type="code_patch", confidence=0.5,
            )
        )

        async def mock_execute_fix( diagnosis, selected_fix ):
            return (
                FixResult( applied=True, success=True, details="ok" ),
                [],
            )

        mock_executor_cls = MagicMock()
        mock_instance = MagicMock()
        mock_instance.execute_fix = AsyncMock( side_effect=mock_execute_fix )
        mock_executor_cls.return_value = mock_instance

        with patch(
            "cosa.agents.shared.fix_executor.FixExecutor", mock_executor_cls
        ):
            results = await orch.run_phase3_fix()

        # Only C1 attempted; C99 skipped silently
        assert len( results ) == 1
        assert mock_executor_cls.call_count == 1

    @pytest.mark.asyncio
    async def test_cancellation_mid_phase( self ):
        """request_stop() between clusters halts the loop."""
        orch = _make_orchestrator( dry_run=False )
        _setup_clusters_and_diagnoses( orch, k=3 )

        call_ids = []
        async def mock_execute_fix( diagnosis, selected_fix ):
            call_ids.append( selected_fix.cluster_id )
            if selected_fix.cluster_id == "C1":
                orch.request_stop()
            return (
                FixResult( applied=True, success=True, details="ok" ),
                [],
            )

        mock_executor_cls = MagicMock()
        mock_instance = MagicMock()
        mock_instance.execute_fix = AsyncMock( side_effect=mock_execute_fix )
        mock_executor_cls.return_value = mock_instance

        with patch(
            "cosa.agents.shared.fix_executor.FixExecutor", mock_executor_cls
        ):
            results = await orch.run_phase3_fix()

        assert call_ids == [ "C1" ]
        assert len( results ) == 1


class TestFixContextConstruction:
    """Verify the FixContext passed into FixExecutor has the right shape for TFE prompts."""

    @pytest.mark.asyncio
    async def test_fix_context_has_cluster_id_and_user_email( self ):
        orch = _make_orchestrator( dry_run=False )
        _setup_clusters_and_diagnoses( orch, k=1 )

        captured_contexts = []

        async def mock_execute_fix( diagnosis, selected_fix ):
            return (
                FixResult( applied=True, success=True, details="ok" ),
                [],
            )

        def capture_init( *args, **kwargs ):
            captured_contexts.append( kwargs.get( "fix_context" ) )
            inst = MagicMock()
            inst.execute_fix = AsyncMock( side_effect=mock_execute_fix )
            return inst

        mock_executor_cls = MagicMock( side_effect=capture_init )

        with patch(
            "cosa.agents.shared.fix_executor.FixExecutor", mock_executor_cls
        ):
            await orch.run_phase3_fix()

        assert len( captured_contexts ) == 1
        ctx = captured_contexts[ 0 ]
        assert ctx.cluster_id == "C1"
        assert ctx.user_email == "t@t.com"
        assert ctx.failure_indices == [ 0 ]


class TestTFEPromptRegistration:
    """Verify TFE prompts are registered in the shared FIX_PROMPT_BUILDERS registry."""

    def test_tfe_key_present( self ):
        # Importing the orchestrator triggers the side-effect registration
        from cosa.agents.shared.fix_executor import FIX_PROMPT_BUILDERS
        assert "tfe" in FIX_PROMPT_BUILDERS

    def test_tfe_bundle_shape( self ):
        from cosa.agents.shared.fix_executor import FIX_PROMPT_BUILDERS
        bundle = FIX_PROMPT_BUILDERS[ "tfe" ]
        assert "build_fix_prompt" in bundle
        assert "build_verify_prompt" in bundle
        assert "build_redelegate_prompt" in bundle
        assert "coder_system_prompt" in bundle
        assert "tester_system_prompt" in bundle
        assert callable( bundle[ "build_fix_prompt" ] )
        assert isinstance( bundle[ "coder_system_prompt" ], str )
        assert len( bundle[ "coder_system_prompt" ] ) > 100

    def test_tfe_prompts_differ_from_bfe( self ):
        """TFE tester prompt specifically mentions pytest -k filtering."""
        from cosa.agents.shared.fix_executor import FIX_PROMPT_BUILDERS
        tfe = FIX_PROMPT_BUILDERS[ "tfe" ]
        bfe = FIX_PROMPT_BUILDERS[ "bfe" ]
        assert tfe[ "tester_system_prompt" ] != bfe[ "tester_system_prompt" ]
        assert "pytest -k" in tfe[ "tester_system_prompt" ]
