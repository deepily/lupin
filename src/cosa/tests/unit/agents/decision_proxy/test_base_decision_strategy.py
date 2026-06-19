#!/usr/bin/env python3
"""
Unit tests for cosa.agents.decision_proxy.base_decision_strategy.

Covers DecisionResult (construction, repr) and BaseDecisionStrategy's
concrete behaviour: the abstract-instantiation guard, the default
available/can_handle properties, and the evaluate() pipeline across all
gate outcomes (the act/suggest branch that produces a value vs. the
shadow/defer branch that leaves value=None).
"""

import pytest

from cosa.agents.decision_proxy.base_decision_strategy import (
    DecisionResult,
    BaseDecisionStrategy,
)


# ----------------------------------------------------------------------------
# DecisionResult
# ----------------------------------------------------------------------------
def test_decision_result_defaults():
    r = DecisionResult( action="shadow" )
    assert r.action == "shadow"
    assert r.value is None
    assert r.category == "unknown"
    assert r.confidence == 0.0
    assert r.trust_level == 1
    assert r.reason == ""


def test_decision_result_all_fields():
    r = DecisionResult(
        action="act",
        value="v",
        category="testing",
        confidence=0.85,
        trust_level=3,
        reason="because",
    )
    assert r.value == "v"
    assert r.category == "testing"
    assert r.trust_level == 3
    assert r.reason == "because"


def test_decision_result_repr_contains_key_fields():
    r = DecisionResult( action="act", category="testing", confidence=0.85, trust_level=3 )
    text = repr( r )
    assert "DecisionResult" in text
    assert "act" in text
    assert "testing" in text
    assert "0.85" in text


# ----------------------------------------------------------------------------
# BaseDecisionStrategy
# ----------------------------------------------------------------------------
def test_cannot_instantiate_abstract_strategy():
    with pytest.raises( TypeError ):
        BaseDecisionStrategy()


class _Strategy( BaseDecisionStrategy ):
    """Concrete strategy whose gate decision is injectable for branch coverage."""

    def __init__( self, gate_action="shadow" ):
        self._gate_action = gate_action

    @property
    def name( self ):
        return "test-strategy"

    def classify( self, question, sender_id="", context=None ):
        return ( "testing", 0.9 )

    def gate( self, category, trust_level, confidence ):
        return self._gate_action

    def decide( self, question, category, context=None ):
        return "decided-value"


def test_name_property():
    assert _Strategy().name == "test-strategy"


def test_available_defaults_true():
    assert _Strategy().available is True


def test_can_handle_defaults_true():
    assert _Strategy().can_handle( { "any": "payload" } ) is True


def test_evaluate_shadow_leaves_value_none():
    """
    Ensures:
        - gate() == "shadow" → decide() is NOT called, value stays None
        - classification metadata is threaded into the result
    """
    r = _Strategy( gate_action="shadow" ).evaluate( "Should I?", sender_id="s@x" )
    assert r.action == "shadow"
    assert r.value is None
    assert r.category == "testing"
    assert r.confidence == 0.9
    assert r.trust_level == 1
    assert "shadow" in r.reason
    assert "testing" in r.reason


def test_evaluate_defer_leaves_value_none():
    r = _Strategy( gate_action="defer" ).evaluate( "Should I?" )
    assert r.action == "defer"
    assert r.value is None


def test_evaluate_act_sets_value():
    """
    Ensures:
        - gate() == "act" → decide() runs and value is populated
    """
    r = _Strategy( gate_action="act" ).evaluate( "Should I?" )
    assert r.action == "act"
    assert r.value == "decided-value"


def test_evaluate_suggest_sets_value():
    r = _Strategy( gate_action="suggest" ).evaluate( "Should I?" )
    assert r.action == "suggest"
    assert r.value == "decided-value"
