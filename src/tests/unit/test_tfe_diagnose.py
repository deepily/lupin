"""
Unit tests for TFE Phase 1 diagnose.

Session 1cfcdf73 (2026-04-10): Step 11 implementation tests. Mocks the
Claude Agent SDK delegate so tests are offline-safe.
"""

import json
from unittest.mock import AsyncMock, patch

import pytest

from cosa.agents.test_fix_expediter.config import TestFixExpediterConfig
from cosa.agents.test_fix_expediter.orchestrator import TFEOrchestrator
from cosa.agents.test_fix_expediter.state import (
    FailureCluster,
    TestDiagnosisResult,
    TestRemediationContext,
    TFEPhase,
)


# ─────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────


def _make_ctx():
    return TestRemediationContext(
        source_test_suite_job_id = "ts-test",
        snapshot_path            = "p",
        snapshot                 = { "schema_version": "1.0" },
        suites_run               = [ "unit" ],
        summary                  = { "all_passed": False },
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


def _make_orchestrator( **overrides ):
    ctx = overrides.pop( "ctx", _make_ctx() )
    config_kwargs = { "max_diagnosis_iterations": 3, "min_diagnosis_confidence": 0.65 }
    config_kwargs.update( overrides.pop( "config", {} ) )
    config = TestFixExpediterConfig( **config_kwargs )

    return TFEOrchestrator(
        remediation_context = ctx,
        config              = config,
        user_id             = "u1",
        user_email          = "t@t.com",
        session_id          = "s1",
        job_id              = "tfe-smoke",
        dry_run             = True,
        debug               = False,
    )


def _diagnosis_response(
    cluster_id: str,
    confidence: float = 0.85,
    category: str = "code_bug",
) -> str:
    """Build a valid JSON response string for a diagnosis."""
    payload = {
        "cluster_id"          : cluster_id,
        "root_cause"          : f"Simulated root cause for {cluster_id}",
        "error_category"      : category,
        "confidence"          : confidence,
        "evidence"            : [ "file.py:42" ],
        "affected_components" : [ "src/foo.py" ],
        "is_transient"        : False,
        "test_symptoms"       : [ "assert 401 == 200" ],
    }
    return f"```json\n{json.dumps( payload )}\n```"


# ─────────────────────────────────────────────────────────────────────────
# JSON parser tests
# ─────────────────────────────────────────────────────────────────────────


class TestParseDiagnosisResult:

    def test_clean_json( self ):
        orch = _make_orchestrator()
        raw = _diagnosis_response( "C1", confidence=0.8 )
        result = orch._parse_diagnosis_result( raw, "C1" )
        assert result.cluster_id == "C1"
        assert result.confidence == 0.8
        assert result.error_category == "code_bug"

    def test_json_with_prose_prefix( self ):
        orch = _make_orchestrator()
        raw = (
            "Here is my analysis. After reading tokens.py, I believe:\n\n"
            + _diagnosis_response( "C2", confidence=0.7 )
        )
        result = orch._parse_diagnosis_result( raw, "C2" )
        assert result.cluster_id == "C2"
        assert result.confidence == 0.7

    def test_missing_cluster_id_populated( self ):
        """Parser injects cluster_id if the LLM omits it."""
        orch = _make_orchestrator()
        payload = {
            "root_cause": "x",
            "error_category": "code_bug",
            "confidence": 0.5,
            "evidence": [],
            "affected_components": [],
            "test_symptoms": [],
        }
        raw = json.dumps( payload )
        result = orch._parse_diagnosis_result( raw, "C3" )
        assert result.cluster_id == "C3"

    def test_invalid_json_fallback( self ):
        orch = _make_orchestrator()
        result = orch._parse_diagnosis_result( "no json here at all", "C4" )
        assert result.cluster_id == "C4"
        assert result.confidence == 0.1
        assert result.error_category == "unknown"

    def test_malformed_json_fallback( self ):
        orch = _make_orchestrator()
        result = orch._parse_diagnosis_result( "{broken: syntax}", "C5" )
        assert result.cluster_id == "C5"
        assert result.confidence == 0.1

    def test_extract_last_json_object_backward_walk( self ):
        text = 'prose {nested} more prose {"key": "value"} trailing'
        extracted = TFEOrchestrator._extract_last_json_object( text )
        assert extracted == '{"key": "value"}'

    def test_extract_last_json_object_no_match( self ):
        assert TFEOrchestrator._extract_last_json_object( "no braces" ) is None


class TestFallbackDiagnosis:

    def test_fallback_shape( self ):
        fb = TFEOrchestrator._fallback_diagnosis( "C1", "reason text" )
        assert fb.cluster_id == "C1"
        assert fb.root_cause == "reason text"
        assert fb.confidence == 0.1
        assert fb.error_category == "unknown"
        assert fb.is_transient is False
        assert fb.evidence == [ "Failed to parse structured diagnosis" ]


# ─────────────────────────────────────────────────────────────────────────
# Per-cluster diagnosis loop tests
# ─────────────────────────────────────────────────────────────────────────


class TestDiagnoseCluster:

    @pytest.mark.asyncio
    async def test_single_iteration_high_confidence( self ):
        orch = _make_orchestrator()
        cluster = FailureCluster(
            cluster_id="C1", failure_indices=[ 0 ],
            shared_error_signature="sig",
        )
        with patch.object(
            orch, "_delegate_to_lead_diagnosis", new=AsyncMock(
                return_value=_diagnosis_response( "C1", confidence=0.85 )
            )
        ) as mock_delegate:
            result = await orch._diagnose_cluster( cluster )

        assert result.confidence == 0.85
        assert mock_delegate.call_count == 1   # stopped on first high-conf

    @pytest.mark.asyncio
    async def test_iterates_until_confidence_met( self ):
        orch = _make_orchestrator()
        cluster = FailureCluster(
            cluster_id="C1", failure_indices=[ 0 ],
            shared_error_signature="sig",
        )
        # Iteration 1: low, 2: medium, 3: above threshold
        responses = [
            _diagnosis_response( "C1", confidence=0.3 ),
            _diagnosis_response( "C1", confidence=0.5 ),
            _diagnosis_response( "C1", confidence=0.75 ),
        ]
        with patch.object(
            orch, "_delegate_to_lead_diagnosis", new=AsyncMock( side_effect=responses )
        ) as mock_delegate:
            result = await orch._diagnose_cluster( cluster )

        assert result.confidence == 0.75
        assert mock_delegate.call_count == 3

    @pytest.mark.asyncio
    async def test_exhausts_iterations_returns_best( self ):
        orch = _make_orchestrator()   # max_iters=3
        cluster = FailureCluster(
            cluster_id="C1", failure_indices=[ 0 ],
            shared_error_signature="sig",
        )
        # All 3 iterations below threshold; iter 2 is best
        responses = [
            _diagnosis_response( "C1", confidence=0.4 ),
            _diagnosis_response( "C1", confidence=0.6 ),   # best
            _diagnosis_response( "C1", confidence=0.5 ),
        ]
        with patch.object(
            orch, "_delegate_to_lead_diagnosis", new=AsyncMock( side_effect=responses )
        ) as mock_delegate:
            result = await orch._diagnose_cluster( cluster )

        assert mock_delegate.call_count == 3
        assert result.confidence == 0.6   # best attempt

    @pytest.mark.asyncio
    async def test_sdk_returns_none_fallback( self ):
        orch = _make_orchestrator()
        cluster = FailureCluster(
            cluster_id="C1", failure_indices=[ 0 ],
            shared_error_signature="sig",
        )
        with patch.object(
            orch, "_delegate_to_lead_diagnosis", new=AsyncMock( return_value=None )
        ):
            result = await orch._diagnose_cluster( cluster )

        assert result.cluster_id == "C1"
        assert result.confidence == 0.1
        assert result.error_category == "unknown"

    @pytest.mark.asyncio
    async def test_cancellation_breaks_loop( self ):
        orch = _make_orchestrator()
        cluster = FailureCluster(
            cluster_id="C1", failure_indices=[ 0 ],
            shared_error_signature="sig",
        )
        responses = [
            _diagnosis_response( "C1", confidence=0.3 ),
        ]
        call_count = [ 0 ]

        async def mock_delegate( prompt ):
            call_count[ 0 ] += 1
            if call_count[ 0 ] == 1:
                orch.request_stop()
            return responses[ 0 ] if call_count[ 0 ] == 1 else None

        with patch.object( orch, "_delegate_to_lead_diagnosis", side_effect=mock_delegate ):
            result = await orch._diagnose_cluster( cluster )

        # One call succeeded, then cancellation halted the loop
        assert call_count[ 0 ] == 1
        # Best we have
        assert result.confidence == 0.3


# ─────────────────────────────────────────────────────────────────────────
# run_phase1_diagnose tests
# ─────────────────────────────────────────────────────────────────────────


class TestPhase1Diagnose:

    @pytest.mark.asyncio
    async def test_runs_each_cluster( self ):
        orch = _make_orchestrator()
        # Phase 0 first to populate clusters
        await orch.run_phase0_cluster()
        assert len( orch.clusters ) >= 1

        call_ids = []
        async def mock_diag( cluster ):
            call_ids.append( cluster.cluster_id )
            return TestDiagnosisResult(
                cluster_id=cluster.cluster_id,
                root_cause="test",
                error_category="code_bug",
                confidence=0.8,
                test_symptoms=[],
            )

        with patch.object( orch, "_diagnose_cluster", side_effect=mock_diag ):
            diagnoses = await orch.run_phase1_diagnose()

        assert len( diagnoses ) == len( orch.clusters )
        for c in orch.clusters:
            assert c.cluster_id in diagnoses
        assert orch.current_phase == TFEPhase.DIAGNOSING

    @pytest.mark.asyncio
    async def test_empty_clusters_empty_diagnoses( self ):
        orch = _make_orchestrator()
        # Don't run Phase 0 — clusters is still []
        diagnoses = await orch.run_phase1_diagnose()
        assert diagnoses == {}
        assert orch.current_phase == TFEPhase.DIAGNOSING

    @pytest.mark.asyncio
    async def test_fallback_when_sdk_unavailable( self ):
        orch = _make_orchestrator()
        await orch.run_phase0_cluster()
        assert len( orch.clusters ) >= 1

        with patch(
            "cosa.agents.test_fix_expediter.orchestrator.SDK_AVAILABLE", False
        ):
            diagnoses = await orch.run_phase1_diagnose()

        assert len( diagnoses ) == len( orch.clusters )
        for d in diagnoses.values():
            assert d.confidence == 0.1
            assert d.error_category == "unknown"
            assert "SDK not installed" in d.root_cause

    @pytest.mark.asyncio
    async def test_cancellation_halts_mid_run( self ):
        orch = _make_orchestrator()
        await orch.run_phase0_cluster()
        # Force K=2 clusters by using a fixture with 2 distinct classes
        orch.clusters = [
            FailureCluster( cluster_id="C1", failure_indices=[ 0 ], shared_error_signature="a" ),
            FailureCluster( cluster_id="C2", failure_indices=[ 1 ], shared_error_signature="b" ),
        ]

        call_order = []
        async def mock_diag( cluster ):
            call_order.append( cluster.cluster_id )
            if cluster.cluster_id == "C1":
                orch.request_stop()
            return TestDiagnosisResult(
                cluster_id=cluster.cluster_id, root_cause="x",
                error_category="code_bug", confidence=0.8,
            )

        with patch.object( orch, "_diagnose_cluster", side_effect=mock_diag ):
            diagnoses = await orch.run_phase1_diagnose()

        # C1 was processed; C2 halted
        assert "C1" in call_order
        assert "C2" not in call_order
        assert len( diagnoses ) == 1
        assert "C1" in diagnoses
