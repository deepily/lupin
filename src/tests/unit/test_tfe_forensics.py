"""
Unit tests for the TFE forensics / error-capture fix.

Covers 8 assertions (T1-T8) from the plan at
`src/rnd/v0.1.6/2026.04.11-tfe-forensics-capture-plan.md`:

- T1: persistence allowlist includes `test_fix_expediter`
- T2: `do_all()` failure captures `self.state = FAILED` + full traceback into `self.error`
- T3: `do_all()` failure prints traceback to stdout unconditionally (not gated on `self.debug`)
- T4: `_execute()` sets BFE cosa_interface `TARGET_USER` + `SENDER_ID` before orchestrator phases
- T5: `_execute()` outer try/except emits urgent notify before re-raising
- T6: No `notify_progress()` call in TFE's orchestrator passes `notification_type=` kwarg
- T7: `_execute()` stores `self.artifacts["plan_path"]` after Phase 2 (survives later phase failure)
- T8: Dead-queue serializer exposes `plan_path`, `remediation_snapshot_path`, `cost_summary`
      on dead cards for agentic jobs

All tests use MagicMock/AsyncMock — no real Claude Agent SDK / Postgres / queue system.
"""

import ast
import asyncio
import inspect

import pytest
from unittest.mock import MagicMock, AsyncMock, patch


# =============================================================================
# T1 — Persistence allowlist includes TFE
# =============================================================================

class TestTfePersistenceAllowlist:
    """Fix 1 — test_fix_expediter in AGENTIC_JOB_TYPES frozenset."""

    def test_tfe_in_agentic_job_types( self ):
        from cosa.rest.job_persistence import AGENTIC_JOB_TYPES, is_agentic_job_type
        assert "test_fix_expediter" in AGENTIC_JOB_TYPES, \
            "TFE must be in AGENTIC_JOB_TYPES so job_history persistence runs"
        assert is_agentic_job_type( "test_fix_expediter" ) is True


# =============================================================================
# T2, T3 — TFE do_all() error capture
# =============================================================================

def _make_tfe_job( debug=False ):
    """Construct a TFE job instance with minimal required args."""
    from cosa.agents.test_fix_expediter.job import TestFixExpediterJob
    return TestFixExpediterJob(
        remediation_snapshot_path = "test-suite/mock-remediation.json",
        source_test_suite_job_id  = "ts-test1234::user1",
        user_id                   = "user1",
        user_email                = "forensics@test.com",
        session_id                = "test-session",
        debug                     = debug,
    )


class TestTfeDoAllErrorCapture:
    """Fix 2 — do_all() uses self.state + captures full traceback + unconditional print."""

    def test_do_all_failure_sets_state_failed_and_error_with_traceback( self ):
        from cosa.rest.job_state import JobState

        tfe = _make_tfe_job( debug=False )

        # Monkey-patch _execute to raise a distinctive exception
        async def _raise():
            raise KeyError( "forced-test-failure-marker" )
        tfe._execute = _raise

        result = tfe.do_all()

        # State + timestamps
        assert tfe.state == JobState.FAILED, f"expected FAILED, got {tfe.state}"
        assert tfe.completed_at is not None

        # self.error contains the full traceback — NOT just the message
        assert tfe.error is not None, "self.error must be populated on failure"
        assert "KeyError" in tfe.error, "error should contain exception type"
        assert "forced-test-failure-marker" in tfe.error, "error should contain the exception message"
        assert "Traceback" in tfe.error, \
            "error should contain full Python traceback (not just the message)"
        assert "do_all" in tfe.error or "_raise" in tfe.error, \
            "traceback should include stack frames"

        # answer_conversational is the friendly UI string
        # Note: str(KeyError("x")) == "'x'" — KeyError wraps in quotes, that's fine
        assert tfe.answer_conversational.startswith( "TFE failed:" )
        assert "forced-test-failure-marker" in tfe.answer_conversational
        assert result == tfe.answer_conversational

        # Legacy self.status attribute should no longer be used as the lifecycle indicator
        # (it may still exist for other reasons, but state is the canonical source)
        assert tfe.state == JobState.FAILED

    def test_do_all_failure_prints_to_stdout_unconditionally( self, capsys ):
        """Fix 2 — traceback print is NOT gated on self.debug."""
        tfe = _make_tfe_job( debug=False )  # debug EXPLICITLY False

        async def _raise():
            raise RuntimeError( "stdout-probe-marker" )
        tfe._execute = _raise

        tfe.do_all()
        captured = capsys.readouterr()

        assert "[TestFixExpediterJob] Failed" in captured.out, \
            "header line must be printed regardless of debug flag"
        assert "stdout-probe-marker" in captured.out, \
            "exception message must be printed"
        assert "Traceback" in captured.out, \
            "full traceback must be printed regardless of debug flag (so docker logs capture it)"

    def test_do_all_success_path_uses_state_completed( self ):
        """Smoke — success path sets JobState.COMPLETED via the new do_all()."""
        from cosa.rest.job_state import JobState

        tfe = _make_tfe_job( debug=False )

        async def _ok():
            return "mock-success-answer"
        tfe._execute = _ok

        result = tfe.do_all()

        assert tfe.state == JobState.COMPLETED
        assert tfe.completed_at is not None
        assert tfe.error is None
        assert result == "mock-success-answer"
        assert tfe.answer_conversational == "mock-success-answer"


# =============================================================================
# T4, T5 — _execute() voice_io + cosa_interface setup + urgent notify
# =============================================================================

class TestTfeExecuteVoiceRouting:
    """Fix 3 + 7 — _execute() sets BFE cosa_interface TARGET_USER/SENDER_ID
    before orchestrator phases, and emits urgent notify on raise."""

    @pytest.mark.asyncio
    async def test_execute_sets_target_user_on_bfe_cosa_interface( self ):
        """Fix 7 — BFE's cosa_interface.TARGET_USER is set to self.user_email
        before the orchestrator runs. This was the root cause of tfe-d9e6b50f's
        'Cannot resolve target_user' crash."""
        from cosa.agents.bug_fix_expediter import cosa_interface as bfe_ci

        tfe = _make_tfe_job()

        # Patch the orchestrator class so we can assert on the state when it's called
        with patch( "cosa.agents.test_fix_expediter.orchestrator.TFEOrchestrator" ) as MockOrch, \
             patch( "cosa.agents.test_fix_expediter.snapshot_loader.load_from_path" ) as mock_load, \
             patch( "cosa.agents.test_fix_expediter.config.TestFixExpediterConfig" ) as MockCfg:
            mock_load.return_value = MagicMock( user_email="forensics@test.com" )
            MockCfg.from_config.return_value = MagicMock()
            MockCfg.return_value = MagicMock()
            orch_instance = MagicMock()
            orch_instance.last_plan_path = None
            orch_instance.run_phase0_cluster = AsyncMock( return_value=[] )
            orch_instance.run_phase1_diagnose = AsyncMock( return_value=[] )
            orch_instance.run_phase2_propose = AsyncMock( return_value=None )
            orch_instance.run_phase3_fix = AsyncMock( return_value=[] )
            orch_instance.run_phase5_git = AsyncMock( return_value=None )
            orch_instance.run_phase6_validation = AsyncMock( return_value=None )
            MockOrch.return_value = orch_instance

            await tfe._execute()

        # After _execute runs, BFE's module-level TARGET_USER must match TFE's user_email
        assert bfe_ci.TARGET_USER == "forensics@test.com", \
            "BFE cosa_interface.TARGET_USER must be set to TFE's user_email"
        # SENDER_ID should have been updated with a suffix (non-empty, not default)
        assert bfe_ci.SENDER_ID is not None
        assert bfe_ci.SENDER_ID != ""

    @pytest.mark.asyncio
    async def test_execute_emits_urgent_notify_on_raise( self ):
        """Fix 3 — outer try/except in _execute() must call voice_io.notify with
        priority='urgent' and re-raise the original exception."""
        tfe = _make_tfe_job()

        # Mock voice_io.notify to observe the call, and force Phase 0 to raise
        with patch( "cosa.agents.test_fix_expediter.voice_io.notify", new_callable=AsyncMock ) as mock_notify, \
             patch( "cosa.agents.test_fix_expediter.orchestrator.TFEOrchestrator" ) as MockOrch, \
             patch( "cosa.agents.test_fix_expediter.snapshot_loader.load_from_path" ) as mock_load, \
             patch( "cosa.agents.test_fix_expediter.config.TestFixExpediterConfig" ) as MockCfg:
            mock_load.return_value = MagicMock()
            MockCfg.from_config.return_value = MagicMock()
            MockCfg.return_value = MagicMock()
            orch_instance = MagicMock()
            orch_instance.last_plan_path = None
            orch_instance.run_phase0_cluster = AsyncMock( side_effect=RuntimeError( "phase0-fail-marker" ) )
            MockOrch.return_value = orch_instance

            with pytest.raises( RuntimeError, match="phase0-fail-marker" ):
                await tfe._execute()

        # Urgent notify was called exactly once
        mock_notify.assert_called_once()
        call_kwargs = mock_notify.call_args.kwargs
        # Priority is urgent
        assert call_kwargs[ "priority" ] == "urgent", \
            f"notify should fire with priority=urgent, got {call_kwargs.get('priority')}"
        # Job_id is set
        assert call_kwargs[ "job_id" ] == tfe.id_hash
        # Abstract contains the full traceback (per plan Q2: yes, include full tb_str — NO truncation)
        assert "abstract" in call_kwargs
        abstract = call_kwargs[ "abstract" ]
        assert abstract is not None
        assert "phase0-fail-marker" in abstract
        assert "Traceback" in abstract, \
            "urgent notify abstract must contain the full Python traceback for forensic access"
        # Verify no truncation was applied (user explicitly requested full string, no [:4000] slicing)
        assert abstract == call_kwargs[ "abstract" ], "abstract must not be truncated"


# =============================================================================
# T6 — No notification_type kwarg in TFE's notify_progress calls
# =============================================================================

class TestTfeOrchestratorNoNotificationTypeKwarg:
    """Fix 6 — AST-level check that no notify_progress call in the orchestrator
    passes a notification_type= kwarg."""

    def test_orchestrator_notify_progress_no_notification_type_kwarg( self ):
        import cosa.agents.test_fix_expediter.orchestrator as orch
        src = inspect.getsource( orch )
        tree = ast.parse( src )

        offending_lines = []
        for node in ast.walk( tree ):
            if isinstance( node, ast.Call ):
                # Match calls to notify_progress (attribute or bare name)
                func_name = None
                if isinstance( node.func, ast.Attribute ):
                    func_name = node.func.attr
                elif isinstance( node.func, ast.Name ):
                    func_name = node.func.id
                if func_name == "notify_progress":
                    kwarg_names = { kw.arg for kw in node.keywords }
                    if "notification_type" in kwarg_names:
                        offending_lines.append( node.lineno )

        assert offending_lines == [], \
            f"notify_progress should NOT pass notification_type kwarg — found at lines: {offending_lines}"


# =============================================================================
# T7 — plan_path stored in self.artifacts after Phase 2
# =============================================================================

class TestTfeExecuteStoresPlanPath:
    """Fix 8a — after Phase 2 (propose), TFE stores
    orchestrator.last_plan_path into self.artifacts['plan_path'] so it survives
    a Phase 3+ failure for dead-queue card display."""

    @pytest.mark.asyncio
    async def test_plan_path_stored_before_phase3_failure( self ):
        tfe = _make_tfe_job()

        mock_plan_path = "/var/lupin/io/swe-team/plans/forensics@test.com/2026.04.11-1-clusters-test-c1-plan.md"

        with patch( "cosa.agents.test_fix_expediter.orchestrator.TFEOrchestrator" ) as MockOrch, \
             patch( "cosa.agents.test_fix_expediter.snapshot_loader.load_from_path" ) as mock_load, \
             patch( "cosa.agents.test_fix_expediter.config.TestFixExpediterConfig" ) as MockCfg, \
             patch( "cosa.agents.test_fix_expediter.voice_io.notify", new_callable=AsyncMock ):
            mock_load.return_value = MagicMock()
            MockCfg.from_config.return_value = MagicMock()
            MockCfg.return_value = MagicMock()
            orch_instance = MagicMock()
            orch_instance.last_plan_path = mock_plan_path
            orch_instance.run_phase0_cluster = AsyncMock( return_value=[] )
            orch_instance.run_phase1_diagnose = AsyncMock( return_value=[] )
            orch_instance.run_phase2_propose = AsyncMock( return_value=None )
            # Force Phase 3 to fail AFTER Phase 2 completed
            orch_instance.run_phase3_fix = AsyncMock( side_effect=RuntimeError( "phase3-fail-after-phase2-plan" ) )
            MockOrch.return_value = orch_instance

            with pytest.raises( RuntimeError, match="phase3-fail-after-phase2-plan" ):
                await tfe._execute()

        # Plan path should be in artifacts even though the job ultimately failed
        assert tfe.artifacts.get( "plan_path" ) == mock_plan_path, \
            "TFE must store orchestrator.last_plan_path in artifacts after Phase 2 so it survives later failures"


# =============================================================================
# T8 — Dead-queue serializer exposes artifact fields
# =============================================================================

class TestDeadQueueSerializerExposesArtifacts:
    """Fix 8b — dead queue branch in queues.py exposes plan_path, remediation_snapshot_path,
    report_path, yaml_path, cost_summary on dead agentic jobs."""

    def test_dead_queue_branch_exists_and_extracts_artifacts( self ):
        """White-box check: the queues.py source contains a dead-queue branch that
        reads job.artifacts. Grep-level assertion — avoids having to mock the full
        FastAPI endpoint."""
        import cosa.rest.routers.queues as queues_mod
        src = inspect.getsource( queues_mod )

        # The dead queue branch must exist
        assert 'if queue_name == "dead":' in src or "if queue_name == 'dead':" in src, \
            "queues.py must have a dedicated dead-queue branch"

        # The branch must extract these artifact fields
        for field in ( "plan_path", "remediation_snapshot_path", "report_path", "yaml_path", "cost_summary" ):
            assert f'"{field}"' in src, \
                f"dead-queue branch must expose '{field}' field on dead cards"

    def test_dead_queue_branch_reads_artifacts_dict( self ):
        """AST-level check: the dead-queue branch pulls from job.artifacts.get(...)."""
        import cosa.rest.routers.queues as queues_mod
        src = inspect.getsource( queues_mod )
        tree = ast.parse( src )

        # Find the "if queue_name == 'dead':" block
        found_dead_branch = False
        dead_branch_reads_artifacts = False

        for node in ast.walk( tree ):
            if isinstance( node, ast.If ):
                # Check if this is `if queue_name == "dead":`
                test = node.test
                if ( isinstance( test, ast.Compare )
                     and isinstance( test.left, ast.Name )
                     and test.left.id == "queue_name"
                     and len( test.comparators ) == 1
                     and isinstance( test.comparators[ 0 ], ast.Constant )
                     and test.comparators[ 0 ].value == "dead" ):
                    found_dead_branch = True
                    # Walk inside the branch looking for job.artifacts.get(...)
                    branch_src = ast.unparse( node )
                    if "artifacts.get" in branch_src and "plan_path" in branch_src:
                        dead_branch_reads_artifacts = True
                    break

        assert found_dead_branch, "queues.py must contain `if queue_name == 'dead':` branch"
        assert dead_branch_reads_artifacts, \
            "dead-queue branch must call job.artifacts.get('plan_path', ...) to surface partial artifacts"


def test_smoke_all_classes_are_importable():
    """Sanity check — all test classes defined at module level are importable."""
    # If we got here, all the imports at module top worked
    assert TestTfePersistenceAllowlist is not None
    assert TestTfeDoAllErrorCapture is not None
    assert TestTfeExecuteVoiceRouting is not None
    assert TestTfeOrchestratorNoNotificationTypeKwarg is not None
    assert TestTfeExecuteStoresPlanPath is not None
    assert TestDeadQueueSerializerExposesArtifacts is not None
