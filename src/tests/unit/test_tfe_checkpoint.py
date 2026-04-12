"""
Unit tests for TFE checkpoint-resume infrastructure.

Session 9056c113 (2026-04-12): Tests checkpoint serialization round-trip,
StalledException propagation, do_all() STALLED state handling, and resume
guard behavior.

All tests use MagicMock/AsyncMock — no real Claude Agent SDK / Postgres / queue system.
"""

import asyncio

import pytest
from unittest.mock import MagicMock, AsyncMock, patch


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_tfe_job( debug=False ):
    """Construct a TFE job instance with minimal required args."""
    from cosa.agents.test_fix_expediter.job import TestFixExpediterJob
    return TestFixExpediterJob(
        remediation_snapshot_path = "test-suite/mock-remediation.json",
        source_test_suite_job_id  = "ts-checkpoint-test::user1",
        user_id                   = "user1",
        user_email                = "checkpoint@test.com",
        session_id                = "test-session",
        debug                     = debug,
    )


def _make_mock_orchestrator( with_clusters=True, with_diagnoses=True, with_proposals=True ):
    """Build a mock orchestrator with realistic state for checkpoint testing."""
    from cosa.agents.test_fix_expediter.state import (
        TFEPhase, FailureCluster, TestDiagnosisResult, TFEProposedFix,
    )

    orch = MagicMock()
    orch.current_phase = TFEPhase.PROPOSING
    orch.dry_run       = False
    orch.debug         = False
    orch.job_id        = "tfe-mock1234"

    # Remediation context
    orch.remediation_context = MagicMock()
    orch.remediation_context.source_test_suite_job_id = "ts-checkpoint-test::user1"
    orch.remediation_context.snapshot_path = "test-suite/mock-remediation.json"
    orch.remediation_context.failures = [ {"name": "test_a"}, {"name": "test_b"} ]

    # Phase 0: clusters
    if with_clusters:
        orch.clusters = [
            FailureCluster(
                cluster_id             = "C1",
                failure_indices        = [ 0, 1 ],
                shared_error_signature = "AssertionError in visual regression",
                hypothesis             = "Stale baselines",
                confidence             = 0.82,
            )
        ]
    else:
        orch.clusters = []

    # Phase 1: diagnoses
    if with_diagnoses:
        orch.diagnoses = {
            "C1": TestDiagnosisResult(
                cluster_id          = "C1",
                root_cause          = "Visual baselines captured by uid 1001, tests run as root in Docker",
                error_category      = "env_bug",
                confidence          = 0.82,
                evidence            = [ "file owner mismatch" ],
                affected_components = [ "io/test-suite/visual-baselines/" ],
                test_symptoms       = [ "AssertionError: snapshot mismatch" ],
            )
        }
    else:
        orch.diagnoses = {}

    # Phase 2: proposals
    if with_proposals:
        orch.proposed_fixes = [
            TFEProposedFix(
                cluster_id  = "C1",
                title       = "Regenerate visual baselines in Docker",
                description = "Run visual tests with --update-snapshots inside Docker",
                fix_type    = "config_change",
                confidence  = 0.90,
            )
        ]
    else:
        orch.proposed_fixes = []

    orch.selected_fixes           = []
    orch.fix_results              = []
    orch.files_changed_by_cluster = {}
    orch.last_plan_path           = "/var/lupin/io/swe-team/plans/test/c1-plan.md"
    orch.branch_name              = None
    orch.commit_hashes            = []
    orch.pr_url                   = None
    orch.validation_run_job_id    = None

    return orch


# ---------------------------------------------------------------------------
# Checkpoint serialization round-trip
# ---------------------------------------------------------------------------

class TestCheckpointSerialization:
    """save_checkpoint() → load_checkpoint() round-trip."""

    def test_save_checkpoint_returns_valid_structure( self ):
        from cosa.agents.test_fix_expediter.orchestrator import TFEOrchestrator
        from cosa.agents.test_fix_expediter.state import TFEPhase

        orch = _make_mock_orchestrator()
        # Attach real save_checkpoint method
        orch.save_checkpoint = TFEOrchestrator.save_checkpoint.__get__( orch )

        checkpoint = orch.save_checkpoint()

        # Required keys
        assert "phase_ordinal" in checkpoint
        assert "phase_name" in checkpoint
        assert "stall_reason" in checkpoint
        assert "stalled_at" in checkpoint
        assert "state_snapshot" in checkpoint
        assert "artifacts" in checkpoint
        assert "resume_count" in checkpoint

        # Phase
        assert checkpoint[ "phase_ordinal" ] == 3  # PROPOSING
        assert checkpoint[ "phase_name" ] == "proposing"
        assert checkpoint[ "stall_reason" ] == "voice_gate_timeout"
        assert checkpoint[ "resume_count" ] == 0

        # State snapshot
        snap = checkpoint[ "state_snapshot" ]
        assert snap[ "source_test_suite_job_id" ] == "ts-checkpoint-test::user1"
        assert len( snap[ "clusters" ] ) == 1
        assert "C1" in snap[ "diagnoses" ]
        assert len( snap[ "proposed_fixes" ] ) == 1

        # Artifacts
        assert checkpoint[ "artifacts" ][ "plan_path" ] == "/var/lupin/io/swe-team/plans/test/c1-plan.md"

    def test_save_load_round_trip( self ):
        """save → load → verify attributes match."""
        from cosa.agents.test_fix_expediter.orchestrator import TFEOrchestrator
        from cosa.agents.test_fix_expediter.state import TFEPhase

        orch = _make_mock_orchestrator()
        orch.save_checkpoint = TFEOrchestrator.save_checkpoint.__get__( orch )

        checkpoint = orch.save_checkpoint()

        # Create a fresh orchestrator mock and load the checkpoint
        orch2 = MagicMock()
        orch2.load_checkpoint = TFEOrchestrator.load_checkpoint.__get__( orch2 )
        orch2.load_checkpoint( checkpoint )

        # Verify state restored
        assert len( orch2.clusters ) == 1
        assert orch2.clusters[ 0 ].cluster_id == "C1"
        assert "C1" in orch2.diagnoses
        assert orch2.diagnoses[ "C1" ].root_cause.startswith( "Visual baselines" )
        assert len( orch2.proposed_fixes ) == 1
        assert orch2.last_plan_path == "/var/lupin/io/swe-team/plans/test/c1-plan.md"
        assert orch2.current_phase.value == "proposing"

    def test_clusters_are_pydantic_after_load( self ):
        """Loaded clusters are real FailureCluster instances, not dicts."""
        from cosa.agents.test_fix_expediter.orchestrator import TFEOrchestrator
        from cosa.agents.test_fix_expediter.state import FailureCluster

        orch = _make_mock_orchestrator()
        orch.save_checkpoint = TFEOrchestrator.save_checkpoint.__get__( orch )
        checkpoint = orch.save_checkpoint()

        orch2 = MagicMock()
        orch2.load_checkpoint = TFEOrchestrator.load_checkpoint.__get__( orch2 )
        orch2.load_checkpoint( checkpoint )

        assert isinstance( orch2.clusters[ 0 ], FailureCluster )


# ---------------------------------------------------------------------------
# StalledException propagation
# ---------------------------------------------------------------------------

class TestStalledExceptionFlow:
    """VoiceGateTimeoutError → StalledException → do_all() STALLED."""

    def test_stalled_exception_carries_checkpoint( self ):
        from cosa.agents.test_fix_expediter.state import StalledException

        checkpoint = { "phase_ordinal": 3, "phase_name": "proposing", "state_snapshot": {} }
        exc = StalledException( checkpoint=checkpoint, phase="proposing" )

        assert exc.checkpoint is checkpoint
        assert exc.phase == "proposing"
        assert "proposing" in str( exc )

    def test_do_all_sets_stalled_state( self ):
        """When _execute returns __STALLED__, do_all() sets state=STALLED."""
        from cosa.rest.job_state import JobState

        tfe = _make_tfe_job()

        async def _stall():
            tfe.orchestrator = _make_mock_orchestrator()
            return "__STALLED__"
        tfe._execute = _stall

        result = tfe.do_all()

        assert tfe.state == JobState.STALLED
        assert tfe.completed_at is not None
        assert "stalled" in result.lower()
        assert "proposals" in result.lower()

    def test_checkpoint_in_artifacts_on_stall( self ):
        """When _execute stalls, checkpoint data appears in self.artifacts."""
        tfe = _make_tfe_job()

        mock_checkpoint = {
            "phase_ordinal"  : 3,
            "phase_name"     : "proposing",
            "stall_reason"   : "voice_gate_timeout",
            "stalled_at"     : "2026-04-12T10:00:00",
            "state_snapshot" : {},
            "artifacts"      : { "plan_path": "/test/plan.md" },
            "resume_count"   : 0,
        }

        async def _stall():
            from cosa.agents.test_fix_expediter.state import StalledException
            tfe.orchestrator = _make_mock_orchestrator()
            tfe.artifacts[ "checkpoint" ] = mock_checkpoint
            tfe.artifacts[ "plan_path" ] = "/test/plan.md"
            return "__STALLED__"
        tfe._execute = _stall

        tfe.do_all()

        assert "checkpoint" in tfe.artifacts
        assert tfe.artifacts[ "checkpoint" ][ "phase_ordinal" ] == 3
        assert tfe.artifacts[ "plan_path" ] == "/test/plan.md"


# ---------------------------------------------------------------------------
# Resume guard
# ---------------------------------------------------------------------------

class TestResumeGuard:
    """set_resume_phase() marks phases as completed for skip."""

    def test_set_resume_phase_stores_ordinal( self ):
        from cosa.agents.test_fix_expediter.orchestrator import TFEOrchestrator

        orch = MagicMock()
        orch.set_resume_phase = TFEOrchestrator.set_resume_phase.__get__( orch )
        orch.set_resume_phase( 3 )

        assert orch._resume_from_ordinal == 3


# ---------------------------------------------------------------------------
# Phase ordinals
# ---------------------------------------------------------------------------

class TestPhaseOrdinals:
    """TFE_PHASE_ORDINALS mapping is complete and ordered."""

    def test_ordinals_are_contiguous( self ):
        from cosa.agents.test_fix_expediter.state import TFE_PHASE_ORDINALS
        ordinals = sorted( TFE_PHASE_ORDINALS.values() )
        assert ordinals == list( range( 7 ) )

    def test_proposing_is_ordinal_3( self ):
        from cosa.agents.test_fix_expediter.state import TFE_PHASE_ORDINALS, TFEPhase
        assert TFE_PHASE_ORDINALS[ TFEPhase.PROPOSING ] == 3


# ---------------------------------------------------------------------------
# Persistence rich_fields includes checkpoint
# ---------------------------------------------------------------------------

class TestPersistenceRichFields:
    """checkpoint is in the metadata_json rich_fields list."""

    def test_checkpoint_in_rich_fields( self ):
        from cosa.rest.job_persistence import _build_metadata_json

        metadata = {
            "checkpoint": {
                "phase_ordinal" : 3,
                "phase_name"    : "proposing",
                "state_snapshot": {},
            }
        }
        result = _build_metadata_json( metadata )
        assert "checkpoint" in result
        assert result[ "checkpoint" ][ "phase_ordinal" ] == 3
