"""
Unit tests for BFE completion voice report.

Session 9056c113 Phase E.1: Bug Fix Expediter gets the same outcome-aware
TTS + rich markdown abstract pattern as TFE. Mirrors test_tfe_forensics.py
::TestTfeCompletionReport structure.
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch


def _make_bfe_job():
    """Construct a BFE job instance with minimal required args."""
    from cosa.agents.bug_fix_expediter.job import BugFixExpediterJob
    return BugFixExpediterJob(
        dead_job_id = "dr-abc12345::user1",
        user_id     = "user1",
        user_email  = "bfe-completion@test.com",
        session_id  = "test-session",
        debug       = False,
    )


class TestBfeCompletionReport:
    """BFE success path sends voice_io.notify with outcome-aware TTS + rich abstract."""

    @pytest.mark.asyncio
    async def test_completion_notify_called_on_fix_applied_and_resubmitted( self ):
        """Fix applied + resubmitted → 'Fix applied and job resubmitted' TTS."""
        bfe = _make_bfe_job()

        # Mock orchestrator + fix result for happy path
        mock_fix_result = MagicMock( success=True, applied=True, pr_url=None )
        mock_fix_result.model_dump.return_value = {}
        mock_diagnosis = MagicMock( root_cause="Missing import causes AttributeError" )
        mock_diagnosis.model_dump.return_value = {}
        mock_proposed = [ MagicMock(), MagicMock() ]
        for p in mock_proposed: p.model_dump.return_value = {}
        mock_selected = MagicMock( title="Add missing import" )
        mock_selected.model_dump.return_value = {}

        orch = MagicMock()
        orch.run_diagnosis        = AsyncMock( return_value=mock_diagnosis )
        orch.run_proposal         = AsyncMock( return_value=( mock_proposed, mock_selected, "io/swe-team/plans/plan.md" ) )
        orch.run_fix              = AsyncMock( return_value=mock_fix_result )
        orch.run_git_strategy     = AsyncMock( return_value=mock_fix_result )
        orch.last_files_changed   = [ "src/foo.py" ]

        with patch( "cosa.agents.bug_fix_expediter.job.BugFixExpediterJob._resubmit_original_job",
                    new_callable=AsyncMock, return_value="dr-resubmit123::user1" ), \
             patch( "cosa.agents.bug_fix_expediter.voice_io.notify", new_callable=AsyncMock ) as mock_notify, \
             patch( "cosa.agents.bug_fix_expediter.voice_io.reconfigure" ), \
             patch( "cosa.agents.bug_fix_expediter.voice_io.clear_job_id" ), \
             patch( "cosa.agents.bug_fix_expediter.cosa_interface" ), \
             patch( "cosa.agents.bug_fix_expediter.dead_job_packager.package_dead_job" ) as mock_pkg, \
             patch( "cosa.agents.bug_fix_expediter.orchestrator.BFEOrchestrator", return_value=orch ), \
             patch( "cosa.agents.bug_fix_expediter.config.BugFixExpediterConfig" ) as MockCfg, \
             patch( "cosa.config.configuration_manager.ConfigurationManager" ):
            mock_pkg.return_value = MagicMock( job_type="deep_research", status="failed", model_dump=lambda: {} )
            MockCfg.from_config.return_value = MagicMock()

            result = await bfe._execute()

        # Verify completion notify was called with priority=medium, queue_name=run
        # The completion notify is the only one with an abstract parameter
        completion_call = None
        for call in mock_notify.call_args_list:
            kwargs = call.kwargs
            if kwargs.get( "abstract" ) and "BFE Activity Report" in kwargs[ "abstract" ]:
                completion_call = call
                break
        assert completion_call is not None, "Expected a completion notify with BFE Activity Report abstract"

        tts_msg = completion_call.args[ 0 ] if completion_call.args else completion_call.kwargs.get( "message", "" )
        assert "complete" in tts_msg.lower()
        assert "applied" in tts_msg.lower() and "resubmitted" in tts_msg.lower()

        abstract = completion_call.kwargs[ "abstract" ]
        assert "**BFE Activity Report**" in abstract
        assert "dr-abc12345" in abstract
        assert "Missing import" in abstract
        assert "**Proposed**: 2" in abstract
        assert "Fix applied**: yes" in abstract
        assert "dr-resubmit123" in abstract

    @pytest.mark.asyncio
    async def test_completion_notify_called_on_fix_applied_no_resubmit( self ):
        """Fix applied but resubmit returned None → 'Fix applied, no resubmit' TTS."""
        bfe = _make_bfe_job()

        mock_fix_result = MagicMock( success=True, applied=True, pr_url=None )
        mock_fix_result.model_dump.return_value = {}
        mock_diagnosis = MagicMock( root_cause="Race condition" )
        mock_diagnosis.model_dump.return_value = {}
        mock_proposed = [ MagicMock() ]
        mock_proposed[ 0 ].model_dump.return_value = {}
        mock_selected = MagicMock( title="Add mutex" )
        mock_selected.model_dump.return_value = {}

        orch = MagicMock()
        orch.run_diagnosis      = AsyncMock( return_value=mock_diagnosis )
        orch.run_proposal       = AsyncMock( return_value=( mock_proposed, mock_selected, "plan.md" ) )
        orch.run_fix            = AsyncMock( return_value=mock_fix_result )
        orch.run_git_strategy   = AsyncMock( return_value=mock_fix_result )
        orch.last_files_changed = [ "x.py" ]

        with patch( "cosa.agents.bug_fix_expediter.job.BugFixExpediterJob._resubmit_original_job",
                    new_callable=AsyncMock, return_value=None ), \
             patch( "cosa.agents.bug_fix_expediter.voice_io.notify", new_callable=AsyncMock ) as mock_notify, \
             patch( "cosa.agents.bug_fix_expediter.voice_io.reconfigure" ), \
             patch( "cosa.agents.bug_fix_expediter.voice_io.clear_job_id" ), \
             patch( "cosa.agents.bug_fix_expediter.cosa_interface" ), \
             patch( "cosa.agents.bug_fix_expediter.dead_job_packager.package_dead_job" ) as mock_pkg, \
             patch( "cosa.agents.bug_fix_expediter.orchestrator.BFEOrchestrator", return_value=orch ), \
             patch( "cosa.agents.bug_fix_expediter.config.BugFixExpediterConfig" ) as MockCfg, \
             patch( "cosa.config.configuration_manager.ConfigurationManager" ):
            mock_pkg.return_value = MagicMock( job_type="deep_research", status="failed", model_dump=lambda: {} )
            MockCfg.from_config.return_value = MagicMock()

            await bfe._execute()

        completion_call = next(
            c for c in mock_notify.call_args_list
            if c.kwargs.get( "abstract" ) and "BFE Activity Report" in c.kwargs[ "abstract" ]
        )
        tts_msg = completion_call.args[ 0 ]
        assert "applied" in tts_msg.lower() and "no resubmit" in tts_msg.lower()

    @pytest.mark.asyncio
    async def test_completion_notify_called_on_no_fixes_applied( self ):
        """Fixes proposed but none applied → 'none applied successfully' TTS."""
        bfe = _make_bfe_job()

        # Fix failed
        mock_fix_result = MagicMock( success=False, applied=False, pr_url=None )
        mock_fix_result.model_dump.return_value = {}
        mock_diagnosis = MagicMock( root_cause="Unknown error" )
        mock_diagnosis.model_dump.return_value = {}
        mock_proposed = [ MagicMock(), MagicMock(), MagicMock() ]
        for p in mock_proposed: p.model_dump.return_value = {}
        mock_selected = MagicMock( title="Try A" )
        mock_selected.model_dump.return_value = {}

        orch = MagicMock()
        orch.run_diagnosis      = AsyncMock( return_value=mock_diagnosis )
        orch.run_proposal       = AsyncMock( return_value=( mock_proposed, mock_selected, "plan.md" ) )
        orch.run_fix            = AsyncMock( return_value=mock_fix_result )
        orch.run_git_strategy   = AsyncMock( return_value=mock_fix_result )
        orch.last_files_changed = []

        with patch( "cosa.agents.bug_fix_expediter.voice_io.notify", new_callable=AsyncMock ) as mock_notify, \
             patch( "cosa.agents.bug_fix_expediter.voice_io.reconfigure" ), \
             patch( "cosa.agents.bug_fix_expediter.voice_io.clear_job_id" ), \
             patch( "cosa.agents.bug_fix_expediter.cosa_interface" ), \
             patch( "cosa.agents.bug_fix_expediter.dead_job_packager.package_dead_job" ) as mock_pkg, \
             patch( "cosa.agents.bug_fix_expediter.orchestrator.BFEOrchestrator", return_value=orch ), \
             patch( "cosa.agents.bug_fix_expediter.config.BugFixExpediterConfig" ) as MockCfg, \
             patch( "cosa.config.configuration_manager.ConfigurationManager" ):
            mock_pkg.return_value = MagicMock( job_type="deep_research", status="failed", model_dump=lambda: {} )
            MockCfg.from_config.return_value = MagicMock()

            await bfe._execute()

        completion_call = next(
            c for c in mock_notify.call_args_list
            if c.kwargs.get( "abstract" ) and "BFE Activity Report" in c.kwargs[ "abstract" ]
        )
        tts_msg = completion_call.args[ 0 ]
        assert "3 fixes proposed" in tts_msg.lower()
        assert "none applied" in tts_msg.lower()

    @pytest.mark.asyncio
    async def test_completion_abstract_includes_plan_path( self ):
        """Abstract contains the plan_path link when available."""
        bfe = _make_bfe_job()

        mock_fix_result = MagicMock( success=True, applied=True, pr_url=None )
        mock_fix_result.model_dump.return_value = {}
        mock_diagnosis = MagicMock( root_cause="test" )
        mock_diagnosis.model_dump.return_value = {}
        mock_proposed = [ MagicMock() ]
        mock_proposed[ 0 ].model_dump.return_value = {}
        mock_selected = MagicMock( title="fix" )
        mock_selected.model_dump.return_value = {}

        orch = MagicMock()
        orch.run_diagnosis      = AsyncMock( return_value=mock_diagnosis )
        orch.run_proposal       = AsyncMock(
            return_value=( mock_proposed, mock_selected, "io/swe-team/plans/detailed-plan.md" )
        )
        orch.run_fix            = AsyncMock( return_value=mock_fix_result )
        orch.run_git_strategy   = AsyncMock( return_value=mock_fix_result )
        orch.last_files_changed = [ "foo.py" ]

        with patch( "cosa.agents.bug_fix_expediter.job.BugFixExpediterJob._resubmit_original_job",
                    new_callable=AsyncMock, return_value=None ), \
             patch( "cosa.agents.bug_fix_expediter.voice_io.notify", new_callable=AsyncMock ) as mock_notify, \
             patch( "cosa.agents.bug_fix_expediter.voice_io.reconfigure" ), \
             patch( "cosa.agents.bug_fix_expediter.voice_io.clear_job_id" ), \
             patch( "cosa.agents.bug_fix_expediter.cosa_interface" ), \
             patch( "cosa.agents.bug_fix_expediter.dead_job_packager.package_dead_job" ) as mock_pkg, \
             patch( "cosa.agents.bug_fix_expediter.orchestrator.BFEOrchestrator", return_value=orch ), \
             patch( "cosa.agents.bug_fix_expediter.config.BugFixExpediterConfig" ) as MockCfg, \
             patch( "cosa.config.configuration_manager.ConfigurationManager" ):
            mock_pkg.return_value = MagicMock( job_type="deep_research", status="failed", model_dump=lambda: {} )
            MockCfg.from_config.return_value = MagicMock()

            await bfe._execute()

        completion_call = next(
            c for c in mock_notify.call_args_list
            if c.kwargs.get( "abstract" ) and "BFE Activity Report" in c.kwargs[ "abstract" ]
        )
        abstract = completion_call.kwargs[ "abstract" ]
        assert "io/swe-team/plans/detailed-plan.md" in abstract
