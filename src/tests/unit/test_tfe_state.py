"""
Unit tests for TestFixExpediter state models.

Session 1cfcdf73 (2026-04-10): Phase 2 scaffolding tests.
"""

import pytest
from pydantic import ValidationError

from cosa.agents.test_fix_expediter.state import (
    TFEPhase,
    TestRemediationContext,
    FailureCluster,
    TestDiagnosisResult,
    TFEProposedFix,
    create_initial_state,
)


class TestTFEPhaseEnum:

    def test_phase_values( self ):
        assert TFEPhase.LOADING.value == "loading"
        assert TFEPhase.CLUSTERING.value == "clustering"
        assert TFEPhase.DIAGNOSING.value == "diagnosing"
        assert TFEPhase.PROPOSING.value == "proposing"
        assert TFEPhase.FIXING.value == "fixing"
        assert TFEPhase.COMMITTING.value == "committing"
        assert TFEPhase.RESUBMITTING.value == "resubmitting"
        assert TFEPhase.COMPLETED.value == "completed"
        assert TFEPhase.FAILED.value == "failed"
        assert TFEPhase.PARTIAL.value == "partial"

    def test_phase_count( self ):
        assert len( TFEPhase ) == 12


class TestTestRemediationContext:

    def _minimal( self, **overrides ):
        kwargs = dict(
            source_test_suite_job_id = "ts-abc12345",
            snapshot_path            = "test-suite/fake.json",
            snapshot                 = { "schema_version": "1.0" },
            suites_run               = [ "e2e" ],
            summary                  = { "all_passed": False },
            failures                 = [ { "classname": "a.b.C", "name": "test_x" } ],
            original_test_types      = [ "e2e" ],
            user_id                  = "u1",
            user_email               = "t@t.com",
            session_id               = "s1",
        )
        kwargs.update( overrides )
        return kwargs

    def test_minimal_valid( self ):
        ctx = TestRemediationContext( **self._minimal() )
        assert ctx.source_test_suite_job_id == "ts-abc12345"
        assert ctx.user_email == "t@t.com"
        assert len( ctx.failures ) == 1

    def test_default_pytest_args( self ):
        ctx = TestRemediationContext( **self._minimal() )
        assert ctx.original_pytest_args == []


class TestFailureCluster:

    def test_minimal_valid( self ):
        cluster = FailureCluster(
            cluster_id              = "C1",
            failure_indices         = [ 0, 1, 2 ],
            shared_error_signature  = "AssertionError",
        )
        assert cluster.cluster_id == "C1"
        assert cluster.failure_indices == [ 0, 1, 2 ]
        assert cluster.confidence == 0.5  # default
        assert cluster.hypothesis == ""
        assert cluster.affected_files_guess == []

    def test_confidence_bounds( self ):
        with pytest.raises( ValidationError ):
            FailureCluster(
                cluster_id="C1", failure_indices=[0], shared_error_signature="x",
                confidence=1.5,
            )


class TestTestDiagnosisResult:

    def test_extends_diagnosis_result( self ):
        diag = TestDiagnosisResult(
            cluster_id          = "C1",
            root_cause          = "Race in token refresh",
            error_category      = "code_bug",
            confidence          = 0.8,
            evidence            = [ "file.py:42 no mutex" ],
            affected_components = [ "src/auth/tokens.py" ],
            test_symptoms       = [ "401 after concurrent requests" ],
        )
        assert diag.cluster_id == "C1"
        assert diag.error_category == "code_bug"
        assert diag.is_transient is False  # inherited default
        assert len( diag.test_symptoms ) == 1


class TestTFEProposedFix:

    def test_minimal_valid( self ):
        fix = TFEProposedFix(
            cluster_id  = "C1",
            title       = "Add mutex",
            description = "Wrap refresh in lock",
            fix_type    = "code_patch",
            confidence  = 0.9,
        )
        assert fix.cluster_id == "C1"
        assert fix.risk_level == "low"   # default
        assert fix.estimated_effort == "minimal"
        assert fix.changes == []


class TestCreateInitialState:

    def test_initial_state_shape( self ):
        state = create_initial_state( "ts-abc", "test-suite/r.json" )
        assert state[ "source_test_suite_job_id" ] == "ts-abc"
        assert state[ "remediation_snapshot_path" ] == "test-suite/r.json"
        assert state[ "phase" ] == "loading"
        assert state[ "clusters" ] == []
        assert state[ "diagnoses" ] == {}
        assert state[ "proposed_fixes" ] == []
        assert state[ "fix_results" ] == []
        assert state[ "remediation_context" ] is None
        assert state[ "validation_run_job_id" ] is None
