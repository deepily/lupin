"""
Unit tests for BFE checkpoint-resume infrastructure.

Session 9056c113 Phase E.2: BFE gets the same checkpoint-resume pattern as TFE.
Mirrors test_tfe_checkpoint.py structure.
"""

import pytest
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# Phase ordinals
# ---------------------------------------------------------------------------

class TestBfePhaseOrdinals:
    """BFE_PHASE_ORDINALS mapping is contiguous and includes all active phases."""

    def test_ordinals_are_contiguous( self ):
        from cosa.agents.bug_fix_expediter.state import BFE_PHASE_ORDINALS
        ordinals = sorted( BFE_PHASE_ORDINALS.values() )
        assert ordinals == list( range( 7 ) ), f"Expected 0-6, got {ordinals}"

    def test_proposing_is_ordinal_2( self ):
        from cosa.agents.bug_fix_expediter.state import BFE_PHASE_ORDINALS, BFEPhase
        assert BFE_PHASE_ORDINALS[ BFEPhase.PROPOSING ] == 2

    def test_all_active_phases_in_mapping( self ):
        from cosa.agents.bug_fix_expediter.state import BFE_PHASE_ORDINALS, BFEPhase
        for phase in [
            BFEPhase.PACKAGING, BFEPhase.DIAGNOSING, BFEPhase.PROPOSING,
            BFEPhase.FIXING, BFEPhase.COMMITTING, BFEPhase.RESUBMITTING,
            BFEPhase.RETRYING,
        ]:
            assert phase in BFE_PHASE_ORDINALS, f"Missing mapping for {phase}"


# ---------------------------------------------------------------------------
# Exception type re-exports
# ---------------------------------------------------------------------------

class TestExceptionReExports:
    """VoiceGateTimeoutError / StalledException / CheckpointData re-exported from TFE."""

    def test_voice_gate_timeout_error_importable_from_bfe_state( self ):
        from cosa.agents.bug_fix_expediter.state import VoiceGateTimeoutError
        exc = VoiceGateTimeoutError( phase="proposing" )
        assert exc.phase == "proposing"

    def test_stalled_exception_importable_from_bfe_state( self ):
        from cosa.agents.bug_fix_expediter.state import StalledException
        exc = StalledException( checkpoint={}, phase="diagnosing" )
        assert exc.phase == "diagnosing"
        assert exc.checkpoint == {}

    def test_bfe_and_tfe_exceptions_are_same_class( self ):
        """Re-exported via `from cosa.agents.test_fix_expediter.state import ...` — not duplicated."""
        from cosa.agents.bug_fix_expediter.state import StalledException as BFEStalled
        from cosa.agents.test_fix_expediter.state import StalledException as TFEStalled
        assert BFEStalled is TFEStalled


# ---------------------------------------------------------------------------
# Orchestrator save/load/round-trip
# ---------------------------------------------------------------------------

def _make_mock_bfe_orchestrator():
    """Build a minimal BFE orchestrator with pipeline state populated."""
    from cosa.agents.bug_fix_expediter.state import (
        BFEPhase, DiagnosisResult, ProposedFix, FixResult, DeadJobContext
    )

    orch = MagicMock()
    orch.current_phase = BFEPhase.PROPOSING
    orch.dead_job_context = MagicMock( id_hash="dr-test-123::u1" )

    orch.diagnosis = DiagnosisResult(
        root_cause       = "Missing import",
        error_category   = "code_bug",
        confidence       = 0.9,
        evidence         = [ "ImportError in logs" ],
        affected_components = [ "src/foo.py" ],
    )
    orch.proposed_fixes = [
        ProposedFix(
            title="Add import", description="Add missing import",
            fix_type="code_patch", confidence=0.85, risk_level="low",
        )
    ]
    orch.selected_fix = orch.proposed_fixes[ 0 ]
    orch.fix_result = None
    orch.plan_path = "io/swe-team/plans/plan.md"
    orch.branch_name = None
    orch.commit_hashes = []
    orch.pr_url = None

    return orch


class TestBfeCheckpointSerialization:
    """save_checkpoint() → load_checkpoint() round-trip."""

    def test_save_checkpoint_returns_valid_structure( self ):
        from cosa.agents.bug_fix_expediter.orchestrator import BFEOrchestrator
        orch = _make_mock_bfe_orchestrator()
        orch.save_checkpoint = BFEOrchestrator.save_checkpoint.__get__( orch )

        cp = orch.save_checkpoint()

        assert "phase_ordinal" in cp
        assert "phase_name" in cp
        assert "state_snapshot" in cp
        assert "artifacts" in cp
        assert cp[ "phase_ordinal" ] == 2   # PROPOSING
        assert cp[ "phase_name" ] == "proposing"
        assert cp[ "stall_reason" ] == "voice_gate_timeout"

        snap = cp[ "state_snapshot" ]
        assert snap[ "dead_job_id" ] == "dr-test-123::u1"
        assert snap[ "diagnosis" ][ "root_cause" ] == "Missing import"
        assert len( snap[ "proposed_fixes" ] ) == 1
        assert snap[ "selected_fix" ][ "title" ] == "Add import"
        assert snap[ "plan_path" ] == "io/swe-team/plans/plan.md"

        # Plan path surfaced as artifact
        assert cp[ "artifacts" ][ "plan_path" ] == "io/swe-team/plans/plan.md"

    def test_save_load_round_trip( self ):
        from cosa.agents.bug_fix_expediter.orchestrator import BFEOrchestrator
        from cosa.agents.bug_fix_expediter.state import DiagnosisResult, ProposedFix

        orch = _make_mock_bfe_orchestrator()
        orch.save_checkpoint = BFEOrchestrator.save_checkpoint.__get__( orch )
        cp = orch.save_checkpoint()

        # Load into a fresh mock orchestrator
        orch2 = MagicMock()
        orch2.load_checkpoint = BFEOrchestrator.load_checkpoint.__get__( orch2 )
        orch2.load_checkpoint( cp )

        assert isinstance( orch2.diagnosis, DiagnosisResult )
        assert orch2.diagnosis.root_cause == "Missing import"
        assert len( orch2.proposed_fixes ) == 1
        assert isinstance( orch2.proposed_fixes[ 0 ], ProposedFix )
        assert orch2.plan_path == "io/swe-team/plans/plan.md"
        assert orch2.current_phase.value == "proposing"


# ---------------------------------------------------------------------------
# Resume guard
# ---------------------------------------------------------------------------

class TestBfeResumeGuard:
    """set_resume_phase() stores the ordinal for phase-skip guards."""

    def test_set_resume_phase_stores_ordinal( self ):
        from cosa.agents.bug_fix_expediter.orchestrator import BFEOrchestrator
        orch = MagicMock()
        orch.set_resume_phase = BFEOrchestrator.set_resume_phase.__get__( orch )
        orch.set_resume_phase( 2 )
        assert orch._resume_from_ordinal == 2


# ---------------------------------------------------------------------------
# StalledException flow in job.py
# ---------------------------------------------------------------------------

class TestBfeStalledFlow:
    """do_all() handles __STALLED__ sentinel + sets JobState.STALLED."""

    def test_stalled_exception_carries_checkpoint( self ):
        from cosa.agents.bug_fix_expediter.state import StalledException

        cp = { "phase_ordinal": 2, "phase_name": "proposing", "state_snapshot": {} }
        exc = StalledException( checkpoint=cp, phase="proposing" )

        assert exc.checkpoint is cp
        assert exc.phase == "proposing"

    def test_do_all_stalled_sentinel_sets_job_state_stalled( self ):
        """When _execute returns __STALLED__, do_all() sets state=STALLED.

        Uses a fresh event loop to avoid polluting the shared loop used by
        downstream tests that call `asyncio.get_event_loop()`.
        """
        import asyncio
        from cosa.agents.bug_fix_expediter.job import BugFixExpediterJob
        from cosa.rest.job_state import JobState

        bfe = BugFixExpediterJob(
            dead_job_id="dr-x::u1", user_id="u1",
            user_email="s@test.com", session_id="s",
        )

        async def _stall():
            return "__STALLED__"
        bfe._execute = _stall

        # Isolate our event loop to avoid breaking sibling tests
        original_loop = None
        try:
            original_loop = asyncio.get_event_loop()
        except RuntimeError:
            pass

        try:
            result = bfe.do_all()
        finally:
            # Re-establish an event loop for subsequent tests
            if original_loop and not original_loop.is_closed():
                asyncio.set_event_loop( original_loop )
            else:
                asyncio.set_event_loop( asyncio.new_event_loop() )

        assert bfe.state == JobState.STALLED
        assert bfe.completed_at is not None
        assert "stalled" in result.lower()
