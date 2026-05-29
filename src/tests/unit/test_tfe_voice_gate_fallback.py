"""
Unit tests for WG-9 TFE voice-gate timeout fallback policies.

Covers `_apply_voice_gate_timeout_policy` for the four configured modes:
    stall  → re-raises VoiceGateTimeoutError (preserves prior behavior)
    top_1  → returns single highest-confidence proposal
    top_n  → returns top-N highest-confidence (N from config)
    none   → returns []

Also asserts confidence-tie ordering preserves input order.

Created: 2026-04-28 (WG-9)
"""

import pytest

from cosa.agents.test_fix_expediter.config import TestFixExpediterConfig
from cosa.agents.test_fix_expediter.orchestrator import TFEOrchestrator
from cosa.agents.test_fix_expediter.state import (
    TFEProposedFix,
    TestRemediationContext,
    VoiceGateTimeoutError,
)


# ──────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────

def _make_proposals():
    """Return 4 proposals with descending+tied confidences for ordering tests."""
    return [
        TFEProposedFix(
            cluster_id  = "C1", title="A", description="a", fix_type="config_change",
            confidence  = 0.90, risk_level="low", estimated_effort="minimal",
        ),
        TFEProposedFix(
            cluster_id  = "C2", title="B", description="b", fix_type="config_change",
            confidence  = 0.70, risk_level="low", estimated_effort="minimal",
        ),
        TFEProposedFix(
            cluster_id  = "C3", title="C", description="c", fix_type="config_change",
            confidence  = 0.70, risk_level="low", estimated_effort="minimal",
        ),
        TFEProposedFix(
            cluster_id  = "C4", title="D", description="d", fix_type="config_change",
            confidence  = 0.50, risk_level="low", estimated_effort="minimal",
        ),
    ]


def _make_orch( **overrides ):
    """Construct an orchestrator with overridable config, no diagnoses needed."""
    config = TestFixExpediterConfig( **overrides )
    ctx = TestRemediationContext(
        source_test_suite_job_id = "ts-test",
        snapshot_path            = "p",
        snapshot                 = { "schema_version": "1.0" },
        suites_run               = [ "unit" ],
        summary                  = { "all_passed": False, "total_failed": 1 },
        failures                 = [],
        original_test_types      = [ "unit" ],
        user_id                  = "u1",
        user_email               = "t@t.com",
        session_id               = "s1",
    )
    return TFEOrchestrator(
        remediation_context = ctx,
        config              = config,
        user_id             = "u1",
        user_email          = "t@t.com",
        session_id          = "s1",
        job_id              = "tfe-wg9",
        dry_run             = False,
        debug               = False,
    )


# ──────────────────────────────────────────────────────────────────────────
# Tests
# ──────────────────────────────────────────────────────────────────────────

def test_policy_stall_reraises():
    orch = _make_orch( voice_gate_timeout_policy = "stall" )
    proposals = _make_proposals()
    with pytest.raises( VoiceGateTimeoutError ):
        orch._apply_voice_gate_timeout_policy( proposals )


def test_policy_none_returns_empty():
    orch = _make_orch( voice_gate_timeout_policy = "none" )
    proposals = _make_proposals()
    selected = orch._apply_voice_gate_timeout_policy( proposals )
    assert selected == []


def test_policy_top_1_returns_highest_confidence():
    orch = _make_orch( voice_gate_timeout_policy = "top_1" )
    proposals = _make_proposals()
    selected = orch._apply_voice_gate_timeout_policy( proposals )
    assert len( selected ) == 1
    assert selected[ 0 ].cluster_id == "C1"  # 0.90 is the highest


def test_policy_top_n_with_n_2():
    orch = _make_orch(
        voice_gate_timeout_policy    = "top_n",
        voice_gate_auto_ratify_top_n = 2,
    )
    proposals = _make_proposals()
    selected = orch._apply_voice_gate_timeout_policy( proposals )
    assert len( selected ) == 2
    # 0.90 then the first 0.70 (input-order tiebreak: C2 before C3)
    assert [ p.cluster_id for p in selected ] == [ "C1", "C2" ]


def test_policy_top_n_with_n_larger_than_proposals():
    orch = _make_orch(
        voice_gate_timeout_policy    = "top_n",
        voice_gate_auto_ratify_top_n = 99,
    )
    proposals = _make_proposals()
    selected = orch._apply_voice_gate_timeout_policy( proposals )
    assert len( selected ) == 4  # capped at proposal count


def test_policy_top_n_with_zero_falls_back_to_one():
    orch = _make_orch(
        voice_gate_timeout_policy    = "top_n",
        voice_gate_auto_ratify_top_n = 0,
    )
    proposals = _make_proposals()
    selected = orch._apply_voice_gate_timeout_policy( proposals )
    assert len( selected ) == 1  # zero clamped to 1


def test_policy_unknown_falls_back_to_stall():
    orch = _make_orch( voice_gate_timeout_policy = "unrecognized_value" )
    proposals = _make_proposals()
    with pytest.raises( VoiceGateTimeoutError ):
        orch._apply_voice_gate_timeout_policy( proposals )


def test_policy_default_is_stall():
    """Untouched config defaults to 'stall' — preserves current production behavior."""
    config = TestFixExpediterConfig()
    assert config.voice_gate_timeout_policy == "stall"
    assert config.voice_gate_auto_ratify_top_n == 1


def test_tie_preserves_input_order():
    """Two proposals at confidence=0.7: input order C2, C3 is preserved."""
    orch = _make_orch(
        voice_gate_timeout_policy    = "top_n",
        voice_gate_auto_ratify_top_n = 3,
    )
    proposals = _make_proposals()
    selected = orch._apply_voice_gate_timeout_policy( proposals )
    assert [ p.cluster_id for p in selected ] == [ "C1", "C2", "C3" ]
