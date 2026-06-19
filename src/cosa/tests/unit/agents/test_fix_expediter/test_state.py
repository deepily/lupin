#!/usr/bin/env python3
"""
Unit tests for cosa.agents.test_fix_expediter.state

Targets: TFEPhase enum, the Pydantic models (TestRemediationContext aliased to
avoid pytest "Test*"-class collection, FailureCluster, TestDiagnosisResult
aliased likewise, TFEProposedFix), the TFEState TypedDict via
create_initial_state, the TFE_PHASE_ORDINALS map, and the
VoiceGateTimeoutError / StalledException carriers.

Pure data models — no external boundaries to mock. quick_smoke_test + __main__
are coverage-excluded by repo config.

Created 2026-05-31 by Clayton 😎 (CoSA coverage campaign, agents Tier-2, TFE lane).
"""

import pytest
from pydantic import ValidationError

from cosa.agents.test_fix_expediter.state import (
    TFEPhase,
    FailureCluster,
    TFEProposedFix,
    TFEState,
    create_initial_state,
    TFE_PHASE_ORDINALS,
    VoiceGateTimeoutError,
    StalledException,
)
# Alias the "Test*"-named production models so pytest does not try to collect
# them as test classes (PytestCollectionWarning).
from cosa.agents.test_fix_expediter.state import TestRemediationContext as _RemediationContext
from cosa.agents.test_fix_expediter.state import TestDiagnosisResult as _DiagnosisResult


class TestTFEPhase:
    """TFEPhase enum surface — representative values + total count."""

    def test_values_and_count( self ):
        assert TFEPhase.LOADING.value              == "loading"
        assert TFEPhase.CLUSTERING.value           == "clustering"
        assert TFEPhase.WAITING_CONFIRMATION.value == "waiting_confirmation"
        assert TFEPhase.PARTIAL.value              == "partial"
        assert TFEPhase.SKIPPED.value              == "skipped"
        assert len( TFEPhase ) == 12


class TestRemediationContextModel:
    """TestRemediationContext (aliased) validates + applies the default args list."""

    def test_validates_and_defaults( self ):
        ctx = _RemediationContext(
            source_test_suite_job_id = "ts-abc12345",
            snapshot_path            = "test-suite/x.json",
            snapshot                 = { "schema_version": "1.0" },
            suites_run               = [ "e2e" ],
            summary                  = { "all_passed": False },
            failures                 = [ { "name": "test_bar" } ],
            original_test_types      = [ "e2e" ],
            user_id                  = "u1",
            user_email               = "t@t.com",
            session_id               = "s1",
        )
        assert ctx.user_email           == "t@t.com"
        assert ctx.original_pytest_args == []          # default_factory list
        assert len( ctx.failures )      == 1


class TestFailureClusterModel:
    """FailureCluster defaults + confidence bound enforcement."""

    def test_defaults( self ):
        c = FailureCluster( cluster_id="C1", failure_indices=[ 0, 1 ], shared_error_signature="AssertionError" )
        assert c.hypothesis           == ""
        assert c.affected_files_guess == []
        assert c.confidence           == 0.5

    def test_confidence_out_of_range_rejected( self ):
        with pytest.raises( ValidationError ):
            FailureCluster( cluster_id="C1", failure_indices=[ 0 ], shared_error_signature="x", confidence=1.5 )


class TestDiagnosisResultModel:
    """TestDiagnosisResult (aliased) extends BFE DiagnosisResult with TFE fields."""

    def test_extends_with_cluster_and_symptoms( self ):
        d = _DiagnosisResult(
            cluster_id          = "C1",
            root_cause          = "Race condition",
            error_category      = "code_bug",
            confidence          = 0.8,
            evidence            = [ "tokens.py:42 lacks mutex" ],
            affected_components = [ "src/cosa/auth/tokens.py" ],
            test_symptoms       = [ "AssertionError: Expected 200 got 401" ],
        )
        assert d.cluster_id    == "C1"
        assert d.error_category == "code_bug"
        assert d.test_symptoms == [ "AssertionError: Expected 200 got 401" ]

    def test_test_symptoms_defaults_empty( self ):
        d = _DiagnosisResult(
            cluster_id="C2", root_cause="r", error_category="config_error",
            confidence=0.5, evidence=[], affected_components=[],
        )
        assert d.test_symptoms == []


class TestTFEProposedFixModel:
    """TFEProposedFix required cluster_id + defaults + confidence bounds."""

    def test_defaults( self ):
        f = TFEProposedFix(
            cluster_id="C1", title="Add mutex", description="lock the refresh",
            fix_type="code_patch", confidence=0.85,
        )
        assert f.risk_level       == "low"
        assert f.estimated_effort == "minimal"
        assert f.changes          == []

    def test_confidence_bound_rejected( self ):
        with pytest.raises( ValidationError ):
            TFEProposedFix(
                cluster_id="C1", title="t", description="d", fix_type="retry", confidence=-0.2,
            )


class TestCreateInitialState:
    """create_initial_state returns a fully-initialized TFEState at LOADING."""

    def test_initial_state( self ):
        state = create_initial_state( "ts-abc12345", "test-suite/remediation.json" )
        assert state[ "source_test_suite_job_id" ]  == "ts-abc12345"
        assert state[ "remediation_snapshot_path" ] == "test-suite/remediation.json"
        assert state[ "remediation_context" ]       is None
        assert state[ "clusters" ]                  == []
        assert state[ "diagnoses" ]                 == {}
        assert state[ "proposed_fixes" ]            == []
        assert state[ "selected_fixes" ]            == []
        assert state[ "fix_results" ]               == []
        assert state[ "files_changed_by_cluster" ]  == {}
        assert state[ "branch_name" ]               is None
        assert state[ "commit_hashes" ]             == []
        assert state[ "pr_url" ]                    is None
        assert state[ "validation_run_job_id" ]     is None
        assert state[ "phase" ]                     == "loading"
        assert state[ "error" ]                     is None
        # constructed dict satisfies the TFEState TypedDict shape
        assert isinstance( state, dict )


class TestPhaseOrdinals:
    """TFE_PHASE_ORDINALS maps the 7 active phases to monotonically rising ints."""

    def test_ordinals( self ):
        assert TFE_PHASE_ORDINALS[ TFEPhase.LOADING ]      == 0
        assert TFE_PHASE_ORDINALS[ TFEPhase.CLUSTERING ]   == 1
        assert TFE_PHASE_ORDINALS[ TFEPhase.RESUBMITTING ] == 6
        assert len( TFE_PHASE_ORDINALS ) == 7


class TestExceptionCarriers:
    """VoiceGateTimeoutError + StalledException carry phase/checkpoint payloads."""

    def test_voice_gate_timeout_default_message( self ):
        e = VoiceGateTimeoutError( phase="proposing" )
        assert e.phase == "proposing"
        assert "Voice gate timeout at proposing" in str( e )

    def test_voice_gate_timeout_custom_message( self ):
        e = VoiceGateTimeoutError( phase="fixing", message="no answer in 300s" )
        assert e.phase == "fixing"
        assert str( e ) == "no answer in 300s"

    def test_stalled_exception_default_message( self ):
        cp = { "phase_ordinal": 3, "phase_name": "proposing" }
        e  = StalledException( checkpoint=cp, phase="proposing" )
        assert e.checkpoint is cp
        assert e.phase == "proposing"
        assert "Stalled at proposing" in str( e )

    def test_stalled_exception_custom_message( self ):
        e = StalledException( checkpoint={}, phase="fixing", message="clean yield" )
        assert str( e ) == "clean yield"
