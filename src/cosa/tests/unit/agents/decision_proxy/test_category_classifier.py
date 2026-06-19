#!/usr/bin/env python3
"""
Unit tests for cosa.agents.decision_proxy.category_classifier.

CategoryClassifier is an abstract interface. Tests verify the ABC contract
(cannot instantiate directly; subclasses must implement both abstract
methods) and that a conforming concrete subclass works as specified.
"""

import pytest

from cosa.agents.decision_proxy.category_classifier import CategoryClassifier


def test_cannot_instantiate_abstract_base():
    """
    Ensures:
        - instantiating the ABC directly raises TypeError
    """
    with pytest.raises( TypeError ):
        CategoryClassifier()


class _ConcreteClassifier( CategoryClassifier ):
    """Minimal conforming implementation for contract testing."""

    def classify( self, question, sender_id="", context=None ):
        return ( "general", 0.42 )

    def get_categories( self ):
        return { "general": { "keywords": [], "cap_level": 1, "description": "fallback" } }


def test_partial_subclass_still_abstract():
    """
    Ensures:
        - a subclass missing one abstract method cannot be instantiated
    """

    class _Partial( CategoryClassifier ):
        def classify( self, question, sender_id="", context=None ):
            return ( "x", 0.0 )

    with pytest.raises( TypeError ):
        _Partial()


def test_concrete_classify_returns_category_confidence_tuple():
    c = _ConcreteClassifier()
    category, confidence = c.classify( "Should I deploy?", sender_id="s@x" )
    assert category == "general"
    assert confidence == 0.42


def test_concrete_get_categories_returns_dict():
    c = _ConcreteClassifier()
    cats = c.get_categories()
    assert "general" in cats
    assert cats[ "general" ][ "cap_level" ] == 1
