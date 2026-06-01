#!/usr/bin/env python3
"""
Unit tests for cosa.agents.decision_proxy.xml_models.

Exercises the four Pydantic models — construction, defaults, and the
field-constraint validation (confidence bounds, trust-level bounds) that
the production contract enforces. Real Pydantic validation is kept in the
loop deliberately (it catches bad mock/payload shapes).
"""

from datetime import datetime

import pytest
from pydantic import ValidationError

from cosa.agents.decision_proxy.xml_models import (
    ClassificationResult,
    TrustDecision,
    RatificationRequest,
    DecisionSummary,
)


# ----------------------------------------------------------------------------
# ClassificationResult
# ----------------------------------------------------------------------------
def test_classification_result_defaults():
    """
    Ensures:
        - method defaults to "keyword"
        - supplied category/confidence are retained
    """
    r = ClassificationResult( category="testing", confidence=0.5 )
    assert r.category == "testing"
    assert r.confidence == 0.5
    assert r.method == "keyword"


def test_classification_result_custom_method():
    r = ClassificationResult( category="deploy", confidence=1.0, method="llm" )
    assert r.method == "llm"


@pytest.mark.parametrize( "bad_confidence", [ -0.01, 1.01 ] )
def test_classification_result_confidence_out_of_bounds_rejected( bad_confidence ):
    """
    Ensures:
        - confidence outside [0.0, 1.0] raises ValidationError
    """
    with pytest.raises( ValidationError ):
        ClassificationResult( category="x", confidence=bad_confidence )


# ----------------------------------------------------------------------------
# TrustDecision
# ----------------------------------------------------------------------------
def test_trust_decision_minimal_and_defaults():
    """
    Ensures:
        - all optional fields fall back to their declared defaults
    """
    d = TrustDecision(
        notification_id="abc",
        category="testing",
        question="Should I run the full test suite?",
        action="shadow",
        confidence=0.8,
        trust_level=1,
    )
    assert d.domain == "swe"
    assert d.sender_id == ""
    assert d.decision_value is None
    assert d.reason == ""
    assert d.timestamp is None


def test_trust_decision_full_payload():
    ts = datetime( 2026, 2, 14, 10, 30, 0 )
    d = TrustDecision(
        notification_id="abc",
        domain="devops",
        category="deploy",
        question="q",
        sender_id="swe.coder@lupin.deepily.ai",
        action="act",
        decision_value="yes",
        confidence=0.9,
        trust_level=3,
        reason="earned trust",
        timestamp=ts,
    )
    assert d.domain == "devops"
    assert d.decision_value == "yes"
    assert d.timestamp == ts


@pytest.mark.parametrize( "bad_level", [ 0, 6 ] )
def test_trust_decision_trust_level_out_of_bounds_rejected( bad_level ):
    """
    Ensures:
        - trust_level outside [1, 5] raises ValidationError
    """
    with pytest.raises( ValidationError ):
        TrustDecision(
            notification_id="a",
            category="c",
            question="q",
            action="act",
            confidence=0.5,
            trust_level=bad_level,
        )


@pytest.mark.parametrize( "bad_confidence", [ -0.5, 1.5 ] )
def test_trust_decision_confidence_out_of_bounds_rejected( bad_confidence ):
    with pytest.raises( ValidationError ):
        TrustDecision(
            notification_id="a",
            category="c",
            question="q",
            action="act",
            confidence=bad_confidence,
            trust_level=1,
        )


# ----------------------------------------------------------------------------
# RatificationRequest
# ----------------------------------------------------------------------------
def test_ratification_request_defaults():
    r = RatificationRequest( decision_id="id1", approved=True )
    assert r.approved is True
    assert r.feedback == ""


def test_ratification_request_with_feedback():
    r = RatificationRequest( decision_id="id2", approved=False, feedback="rejected: too risky" )
    assert r.approved is False
    assert r.feedback == "rejected: too risky"


# ----------------------------------------------------------------------------
# DecisionSummary
# ----------------------------------------------------------------------------
def test_decision_summary_defaults():
    s = DecisionSummary()
    assert s.total_pending == 0
    assert s.by_category == {}
    assert s.by_trust_level == {}
    assert s.oldest_pending is None


def test_decision_summary_populated():
    oldest = datetime( 2026, 1, 1, 0, 0, 0 )
    s = DecisionSummary(
        total_pending=3,
        by_category={ "testing": 2, "deploy": 1 },
        by_trust_level={ 1: 3 },
        oldest_pending=oldest,
    )
    assert s.total_pending == 3
    assert s.by_category[ "testing" ] == 2
    assert s.by_trust_level[ 1 ] == 3
    assert s.oldest_pending == oldest
