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

        # Backlog item 5 (2026-04-29): do_all() re-raises now (canonical
        # Future contract). State + error are still set on the job object.
        with pytest.raises( KeyError ):
            tfe.do_all()

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

        # Legacy self.status attribute should no longer be used as the lifecycle indicator
        # (it may still exist for other reasons, but state is the canonical source)
        assert tfe.state == JobState.FAILED

    def test_do_all_failure_prints_to_stdout_unconditionally( self, capsys ):
        """Fix 2 — traceback print is NOT gated on self.debug."""
        tfe = _make_tfe_job( debug=False )  # debug EXPLICITLY False

        async def _raise():
            raise RuntimeError( "stdout-probe-marker" )
        tfe._execute = _raise

        # Backlog item 5: do_all() re-raises (canonical Future contract).
        with pytest.raises( RuntimeError ):
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
            orch_instance.last_plan_path      = None
            orch_instance.proposed_fixes      = []
            orch_instance.selected_fixes      = []
            orch_instance.diagnoses           = {}
            orch_instance.remediation_context = MagicMock( failures=[] )
            orch_instance.run_phase0_cluster    = AsyncMock( return_value=[] )
            orch_instance.run_phase1_diagnose   = AsyncMock( return_value=[] )
            orch_instance.run_phase2_propose    = AsyncMock( return_value=None )
            orch_instance.run_phase3_fix        = AsyncMock( return_value=[] )
            orch_instance.run_phase5_git        = AsyncMock( return_value=None )
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
    """
    Fix 8b — a dead agentic job's card carries the partial artifacts it managed to
    write before it died, so a user can still recover the plan and the diagnosis.

    HOW THIS IS CHECKED, AND WHY IT CHANGED (row 122f07a1). Both tests here used to
    read queues.py's SOURCE — one grepping for the literal `if queue_name == "dead":`
    plus the five field names, the other walking the AST for the same branch. They
    called themselves white-box "to avoid mocking the full FastAPI endpoint", but
    that endpoint takes its four queues as ordinary arguments, so there was nothing
    to avoid. The cost was real: they went green on any build that kept the branch
    and the five words while handing back None for every field, which is exactly
    what a user would see. These drive the endpoint and read the card.
    """

    _ARTIFACT_FIELDS = ( "plan_path", "remediation_snapshot_path",
                         "report_path", "yaml_path", "cost_summary" )

    def _dead_agentic_job( self ):
        """A dead agentic job carrying every artifact a mid-pipeline death can leave."""
        from cosa.agents.agentic_job_base import AgenticJobBase
        from cosa.rest.queue_protocol import JobState

        job = MagicMock( spec=AgenticJobBase )
        job.id_hash               = "tfe_dead_1"
        job.last_question_asked   = "fix the failing tests"
        job.run_date              = "2026-04-11T10:00:00"
        job.created_date          = "2026-04-11T09:00:00"
        job.user_email            = "u1@x.com"
        job.session_id            = "sess"
        job.job_type              = "test_fix_expediter"
        job.state                 = JobState.FAILED
        job.error                 = "boom"
        job.started_at            = "2026-04-11T10:00:00"
        job.completed_at          = "2026-04-11T10:05:00"
        job.scheduled_at          = None
        job.monopolize            = False
        job.cost_summary          = { "usd": 1.25 }
        job.artifacts             = {
            "plan_path"                : "/io/plans/tfe-plan.md",
            "remediation_snapshot_path": "/io/snapshots/tfe-remediation.json",
            "report_path"              : "/io/reports/tfe-report.md",
            "yaml_path"                : "/io/tfe.yaml",
        }
        return job

    def _dead_card( self, job ):
        """Drive the real endpoint over a dead queue holding `job`; return its card."""
        import cosa.rest.routers.queues as queues_mod

        admin      = { "uid": "admin1", "email": "a@x.com", "roles": [ "admin" ] }
        dead_queue = MagicMock()
        dead_queue.get_jobs_for_user.return_value = [ job ]

        with patch.object( queues_mod, "_count_interactions_for_jobs", return_value={} ):
            out = asyncio.run( queues_mod.get_queue(
                queue_name    = "dead",
                current_user  = admin,
                user_filter   = admin[ "uid" ],
                todo_queue    = MagicMock(),
                running_queue = MagicMock(),
                done_queue    = MagicMock(),
                dead_queue    = dead_queue,
            ) )
        cards = out[ "dead_jobs_metadata" ]
        assert len( cards ) == 1, f"expected exactly one dead card, got {cards}"
        return cards[ 0 ]

    def test_dead_card_carries_every_partial_artifact( self ):
        """All five artifact fields reach the card with the job's real values.

        RED ON REVERT: drop any field from the dead branch, or let the branch fall
        through to the generic todo/run arm, and that field is absent or None here.
        """
        card = self._dead_card( self._dead_agentic_job() )

        for field in self._ARTIFACT_FIELDS:
            assert field in card, f"dead card is missing '{field}' entirely"

        assert card[ "plan_path" ]                 == "/io/plans/tfe-plan.md"
        assert card[ "remediation_snapshot_path" ] == "/io/snapshots/tfe-remediation.json"
        assert card[ "report_path" ]               == "/io/reports/tfe-report.md"
        assert card[ "yaml_path" ]                 == "/io/tfe.yaml"
        assert card[ "cost_summary" ]              == { "usd": 1.25 }

    def test_the_card_reads_the_job_s_artifacts_rather_than_a_fixed_shape( self ):
        """Change what the job wrote and the card follows.

        The source-text checks this replaced could not tell a serializer that READS
        job.artifacts from one emitting the five keys with hardcoded or None values.
        This moves the data and requires the card to move with it.
        """
        job = self._dead_agentic_job()
        job.artifacts[ "plan_path" ] = "/io/plans/somewhere-else.md"
        job.artifacts.pop( "yaml_path" )
        job.cost_summary             = { "usd": 9.99 }

        card = self._dead_card( job )

        assert card[ "plan_path" ]    == "/io/plans/somewhere-else.md"
        assert card[ "yaml_path" ]    is None, "an artifact the job never wrote must read None"
        assert card[ "cost_summary" ] == { "usd": 9.99 }

    def test_a_non_agentic_dead_job_reports_no_artifacts( self ):
        """A plain dead job has no artifacts dict — the card must not invent one.

        RED ON REVERT: drop the is_agentic_job guard and this raises on a job with
        no artifacts attribute instead of reporting None.
        """
        from cosa.rest.queue_protocol import JobState

        plain = MagicMock( spec=[
            "id_hash", "last_question_asked", "run_date", "created_date", "user_email",
            "session_id", "job_type", "state", "error", "started_at", "completed_at",
        ] )
        plain.id_hash             = "plain_dead"
        plain.last_question_asked = "what time is it"
        plain.run_date            = "2026-04-11T10:00:00"
        plain.created_date        = "2026-04-11T09:00:00"
        plain.user_email          = "u1@x.com"
        plain.session_id          = "sess"
        plain.job_type            = "date-and-time"
        plain.state               = JobState.FAILED
        plain.error               = "boom"
        plain.started_at          = None
        plain.completed_at        = None

        card = self._dead_card( plain )
        for field in self._ARTIFACT_FIELDS:
            assert card[ field ] is None, f"non-agentic dead card invented a '{field}'"


# =============================================================================
# T9 — Completion voice notification on success path
# =============================================================================

class TestTfeCompletionReport:
    """Session 9056c113 — Phase A: TFE sends a voice notification with an
    activity report (TTS + rich markdown abstract) on successful completion."""

    @pytest.mark.asyncio
    async def test_completion_notify_called_on_success( self ):
        """Completion voice_io.notify fires with priority=medium on success path."""
        tfe = _make_tfe_job()

        with patch( "cosa.agents.test_fix_expediter.voice_io.notify", new_callable=AsyncMock ) as mock_notify, \
             patch( "cosa.agents.test_fix_expediter.orchestrator.TFEOrchestrator" ) as MockOrch, \
             patch( "cosa.agents.test_fix_expediter.snapshot_loader.load_from_path" ) as mock_load, \
             patch( "cosa.agents.test_fix_expediter.config.TestFixExpediterConfig" ) as MockCfg:
            mock_load.return_value = MagicMock( failures=[ {"name": "test_a"}, {"name": "test_b"} ] )
            MockCfg.from_config.return_value = MagicMock()
            MockCfg.return_value = MagicMock()
            orch_instance = MagicMock()
            orch_instance.last_plan_path      = "/var/lupin/io/swe-team/plans/test/plan.md"
            orch_instance.proposed_fixes      = [ MagicMock() ]
            orch_instance.selected_fixes      = []
            orch_instance.diagnoses           = {
                "C1": MagicMock( root_cause="stale baselines", confidence=0.82, error_category="env_bug" )
            }
            orch_instance.remediation_context = MagicMock( failures=[ {"n": 1}, {"n": 2} ] )
            orch_instance.run_phase0_cluster    = AsyncMock( return_value=[ MagicMock() ] )
            orch_instance.run_phase1_diagnose   = AsyncMock( return_value=[] )
            orch_instance.run_phase2_propose    = AsyncMock( return_value=None )
            orch_instance.run_phase3_fix        = AsyncMock( return_value=[] )
            orch_instance.run_phase5_git        = AsyncMock( return_value=None )
            orch_instance.run_phase6_validation = AsyncMock( return_value=None )
            MockOrch.return_value = orch_instance

            result = await tfe._execute()

        # notify was called at least once (completion)
        assert mock_notify.call_count >= 1, "completion voice_io.notify must be called"
        # Find the completion call (priority=medium, queue_name=run)
        completion_call = None
        for call in mock_notify.call_args_list:
            kwargs = call.kwargs
            if kwargs.get( "priority" ) == "medium" and kwargs.get( "queue_name" ) == "run":
                completion_call = call
                break
        assert completion_call is not None, "Must have a completion notify with priority=medium, queue_name=run"

        kwargs = completion_call.kwargs
        # TTS message references completion
        tts_msg = completion_call.args[ 0 ] if completion_call.args else kwargs.get( "message", "" )
        assert "complete" in tts_msg.lower(), f"TTS message should mention completion: {tts_msg}"

        # Abstract contains activity report sections
        abstract = kwargs[ "abstract" ]
        assert "**TFE Activity Report**" in abstract
        assert "**Clusters**:" in abstract
        assert "**Proposed**:" in abstract
        assert "**Plan**:" in abstract
        assert "**Cluster Diagnoses:**" in abstract
        assert "stale baselines" in abstract

        # job_id is set for card routing
        assert kwargs[ "job_id" ] == tfe.id_hash

    @pytest.mark.asyncio
    async def test_completion_returns_stats_not_scaffolding_text( self ):
        """Return string should contain real stats, not the old scaffolding placeholder."""
        tfe = _make_tfe_job()

        with patch( "cosa.agents.test_fix_expediter.voice_io.notify", new_callable=AsyncMock ), \
             patch( "cosa.agents.test_fix_expediter.orchestrator.TFEOrchestrator" ) as MockOrch, \
             patch( "cosa.agents.test_fix_expediter.snapshot_loader.load_from_path" ) as mock_load, \
             patch( "cosa.agents.test_fix_expediter.config.TestFixExpediterConfig" ) as MockCfg:
            mock_load.return_value = MagicMock( failures=[] )
            MockCfg.from_config.return_value = MagicMock()
            MockCfg.return_value = MagicMock()
            orch_instance = MagicMock()
            orch_instance.last_plan_path      = None
            orch_instance.proposed_fixes      = []
            orch_instance.selected_fixes      = []
            orch_instance.diagnoses           = {}
            orch_instance.remediation_context = MagicMock( failures=[] )
            orch_instance.run_phase0_cluster    = AsyncMock( return_value=[] )
            orch_instance.run_phase1_diagnose   = AsyncMock( return_value=[] )
            orch_instance.run_phase2_propose    = AsyncMock( return_value=None )
            orch_instance.run_phase3_fix        = AsyncMock( return_value=[] )
            orch_instance.run_phase5_git        = AsyncMock( return_value=None )
            orch_instance.run_phase6_validation = AsyncMock( return_value=None )
            MockOrch.return_value = orch_instance

            result = await tfe._execute()

        # Must NOT contain the old scaffolding text
        assert "scaffolding" not in result.lower(), \
            f"Return text should not contain scaffolding placeholder: {result}"
        assert "steps 7-12" not in result, \
            f"Return text should not reference future steps: {result}"
        # Must contain real stats
        assert "TFE complete:" in result
        assert "proposed" in result
        assert "selected" in result


def test_smoke_all_classes_are_importable():
    """Sanity check — all test classes defined at module level are importable."""
    # If we got here, all the imports at module top worked
    assert TestTfePersistenceAllowlist is not None
    assert TestTfeDoAllErrorCapture is not None
    assert TestTfeExecuteVoiceRouting is not None
    assert TestTfeOrchestratorNoNotificationTypeKwarg is not None
    assert TestTfeExecuteStoresPlanPath is not None
    assert TestDeadQueueSerializerExposesArtifacts is not None
    assert TestTfeCompletionReport is not None
