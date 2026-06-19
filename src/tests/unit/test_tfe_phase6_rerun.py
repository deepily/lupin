"""
Unit tests for TFE Phase 6 async rerun validation.

Session 1cfcdf73 (2026-04-10): Step 12 implementation tests. Mocks
create_agentic_job + todo queue for offline-safe runs.
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


def _make_orchestrator(
    dry_run: bool = False,
    rerun_scope: str = "affected",
    original_test_types: list = None,
    original_pytest_args: list = None,
):
    ctx = TestRemediationContext(
        source_test_suite_job_id = "ts-abc12345",
        snapshot_path            = "p",
        snapshot                 = { "schema_version": "1.0" },
        suites_run               = [ "unit" ],
        summary                  = { "all_passed": False, "total_failed": 2 },
        failures                 = [
            {
                "classname": "src.tests.unit.test_x.TestX",
                "name": "test_y", "type": "FAILED",
                "message": "x", "traceback": 'File "src/x.py", line 1',
            },
        ],
        original_test_types      = original_test_types or [ "unit" ],
        original_pytest_args     = original_pytest_args or [],
        user_id                  = "u1",
        user_email               = "t@t.com",
        session_id               = "s1",
    )
    config = TestFixExpediterConfig( rerun_scope=rerun_scope )
    return TFEOrchestrator(
        remediation_context=ctx,
        config=config,
        user_id="u1",
        user_email="t@t.com",
        session_id="s1",
        job_id="tfe-phase6-test",
        dry_run=dry_run,
        debug=False,
    )


def _setup_phase6_state( orch, all_success: bool = True, n: int = 2 ):
    orch.selected_fixes = [
        TFEProposedFix(
            cluster_id=f"C{i+1}", title=f"Fix {i+1}", description="x",
            fix_type="code_patch", confidence=0.8,
        )
        for i in range( n )
    ]
    orch.fix_results = [
        FixResult( applied=True, success=all_success, details="ok" )
        for _ in range( n )
    ]


class TestResolveRerunTestTypes:

    def test_affected_scope_returns_original( self ):
        orch = _make_orchestrator( rerun_scope="affected", original_test_types=[ "unit", "integration" ] )
        assert orch._resolve_rerun_test_types() == [ "unit", "integration" ]

    def test_full_scope_returns_all( self ):
        orch = _make_orchestrator( rerun_scope="full", original_test_types=[ "unit" ] )
        assert orch._resolve_rerun_test_types() == [ "all" ]

    def test_unknown_scope_falls_back_to_affected( self ):
        orch = _make_orchestrator( rerun_scope="mystery", original_test_types=[ "unit" ] )
        assert orch._resolve_rerun_test_types() == [ "unit" ]


class TestPhase6Guards:

    @pytest.mark.asyncio
    async def test_skips_when_no_successful_fixes( self ):
        orch = _make_orchestrator( dry_run=True )
        _setup_phase6_state( orch, all_success=False )

        result = await orch.run_phase6_validation()

        assert result is None
        assert orch.validation_run_job_id is None
        assert orch.current_phase == TFEPhase.RESUBMITTING

    @pytest.mark.asyncio
    async def test_skips_with_empty_fix_results( self ):
        orch = _make_orchestrator( dry_run=True )
        orch.fix_results = []
        orch.selected_fixes = []

        result = await orch.run_phase6_validation()

        assert result is None


class TestPhase6DryRun:

    @pytest.mark.asyncio
    async def test_dry_run_returns_placeholder( self ):
        orch = _make_orchestrator( dry_run=True )
        _setup_phase6_state( orch, all_success=True )

        result = await orch.run_phase6_validation()

        assert result == "dry-run-skipped"
        assert orch.validation_run_job_id == "dry-run-skipped"

    @pytest.mark.asyncio
    async def test_dry_run_does_not_call_factory( self ):
        orch = _make_orchestrator( dry_run=True )
        _setup_phase6_state( orch, all_success=True )

        with patch( "cosa.rest.agentic_job_factory.create_agentic_job" ) as mock_factory:
            await orch.run_phase6_validation()

        mock_factory.assert_not_called()


class TestPhase6DispatchAffected:

    @pytest.mark.asyncio
    async def test_happy_path_dispatches_with_affected_scope( self ):
        orch = _make_orchestrator(
            dry_run=False,
            rerun_scope="affected",
            original_test_types=[ "unit" ],
        )
        _setup_phase6_state( orch, all_success=True )

        fake_job = MagicMock()
        fake_job.id_hash = "ts-validation-xyz"
        fake_job.metadata = None

        mock_queue = MagicMock()

        with (
            patch(
                "cosa.rest.agentic_job_factory.create_agentic_job",
                return_value=fake_job,
            ) as mock_factory,
            patch(
                "lupin_app.main.jobs_todo_queue",
                mock_queue,
                create=True,
            ),
        ):
            result = await orch.run_phase6_validation()

        assert result == "ts-validation-xyz"
        assert orch.validation_run_job_id == "ts-validation-xyz"

        # Factory called with affected suites
        mock_factory.assert_called_once()
        call_kwargs = mock_factory.call_args.kwargs
        assert call_kwargs[ "command" ] == "agent router go to test suite"
        assert call_kwargs[ "args_dict" ][ "test_types" ] == "unit"
        assert call_kwargs[ "user_id" ] == "u1"

        # Metadata recursion guard set
        assert fake_job.metadata[ "triggered_by_tfe" ] == "tfe-phase6-test"
        assert fake_job.metadata[ "tfe_source_test_suite_job_id" ] == "ts-abc12345"
        assert fake_job.metadata[ "tfe_fix_count" ] == 2

        # Pushed to queue
        mock_queue.push.assert_called_once_with( fake_job )

    @pytest.mark.asyncio
    async def test_full_scope_dispatches_all( self ):
        orch = _make_orchestrator(
            dry_run=False,
            rerun_scope="full",
            original_test_types=[ "unit" ],
        )
        _setup_phase6_state( orch, all_success=True )

        fake_job = MagicMock()
        fake_job.id_hash = "ts-full-rerun"
        fake_job.metadata = None

        with (
            patch(
                "cosa.rest.agentic_job_factory.create_agentic_job",
                return_value=fake_job,
            ) as mock_factory,
            patch(
                "lupin_app.main.jobs_todo_queue",
                MagicMock(),
                create=True,
            ),
        ):
            await orch.run_phase6_validation()

        assert mock_factory.call_args.kwargs[ "args_dict" ][ "test_types" ] == "all"

    @pytest.mark.asyncio
    async def test_pytest_args_propagated( self ):
        orch = _make_orchestrator(
            dry_run=False,
            original_pytest_args=[ "-k", "auth or token" ],
        )
        _setup_phase6_state( orch, all_success=True )

        fake_job = MagicMock()
        fake_job.id_hash = "ts-with-args"
        fake_job.metadata = {}

        with (
            patch(
                "cosa.rest.agentic_job_factory.create_agentic_job",
                return_value=fake_job,
            ) as mock_factory,
            patch(
                "lupin_app.main.jobs_todo_queue",
                MagicMock(),
                create=True,
            ),
        ):
            await orch.run_phase6_validation()

        args_dict = mock_factory.call_args.kwargs[ "args_dict" ]
        assert "pytest_args" in args_dict
        assert "auth or token" in args_dict[ "pytest_args" ]


class TestPhase6FailureModes:

    @pytest.mark.asyncio
    async def test_factory_returns_none( self ):
        orch = _make_orchestrator( dry_run=False )
        _setup_phase6_state( orch, all_success=True )

        with patch(
            "cosa.rest.agentic_job_factory.create_agentic_job",
            return_value=None,
        ):
            result = await orch.run_phase6_validation()

        assert result is None
        assert orch.validation_run_job_id is None

    @pytest.mark.asyncio
    async def test_factory_raises( self ):
        orch = _make_orchestrator( dry_run=False )
        _setup_phase6_state( orch, all_success=True )

        with patch(
            "cosa.rest.agentic_job_factory.create_agentic_job",
            side_effect=RuntimeError( "factory error" ),
        ):
            result = await orch.run_phase6_validation()

        assert result is None
        assert orch.validation_run_job_id is None

    @pytest.mark.asyncio
    async def test_queue_push_fails( self ):
        orch = _make_orchestrator( dry_run=False )
        _setup_phase6_state( orch, all_success=True )

        fake_job = MagicMock()
        fake_job.id_hash = "ts-x"
        fake_job.metadata = None

        broken_queue = MagicMock()
        broken_queue.push = MagicMock( side_effect=RuntimeError( "queue broken" ) )

        with (
            patch(
                "cosa.rest.agentic_job_factory.create_agentic_job",
                return_value=fake_job,
            ),
            patch(
                "lupin_app.main.jobs_todo_queue",
                broken_queue,
                create=True,
            ),
        ):
            result = await orch.run_phase6_validation()

        assert result is None


class TestPhase6RecursionGuard:

    @pytest.mark.asyncio
    async def test_metadata_flag_is_string_not_none( self ):
        """Recursion guard metadata must be set to the TFE job_id string."""
        orch = _make_orchestrator( dry_run=False )
        _setup_phase6_state( orch, all_success=True )

        fake_job = MagicMock()
        fake_job.id_hash = "ts-x"
        fake_job.metadata = None

        with (
            patch(
                "cosa.rest.agentic_job_factory.create_agentic_job",
                return_value=fake_job,
            ),
            patch(
                "lupin_app.main.jobs_todo_queue",
                MagicMock(),
                create=True,
            ),
        ):
            await orch.run_phase6_validation()

        assert fake_job.metadata is not None
        assert fake_job.metadata[ "triggered_by_tfe" ] == "tfe-phase6-test"
        assert isinstance( fake_job.metadata[ "triggered_by_tfe" ], str )
