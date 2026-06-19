"""
Unit tests for cosa.agents.prediction_engine.notification_category_classifier.

NotificationCategoryClassifier is a keyword/substring classifier mapping a notification
message to one of 6 categories + an uncategorized catch-all. Tests cover the real
public surface + every branch of classify():

    - each of the 6 categories lands on its expected best-match,
    - no-keyword message → ("uncategorized", 0.0) (the best_match_count==0 arm),
    - empty and whitespace-only input → early ("uncategorized", 0.0) guard,
    - confidence formula 0.5 + 0.1*matches and its 0.95 cap,
    - the debug-print arm (debug=True),
    - get_categories returns the 6-entry definition dict.

`quick_smoke_test` is coverage-excluded (house style); its cases are harvested here.

Authored by Rachel 🕊️ for the CoSA 100% coverage campaign (prediction_engine group).
"""

import pytest

from cosa.agents.prediction_engine.notification_category_classifier import (
    NotificationCategoryClassifier,
    NOTIFICATION_CATEGORIES,
    DEFAULT_CATEGORY,
)


@pytest.fixture
def classifier():
    """A default (non-debug) classifier instance."""
    return NotificationCategoryClassifier()


@pytest.mark.parametrize( "message, expected", [
    ( "Should I proceed with the refactor?",        "permission" ),
    ( "Are you sure you want to delete this file?", "confirmation" ),
    ( "Which approach should we use for caching?",  "approach" ),
    ( "What name should the new module have?",      "input" ),
    ( "Should I commit and push these changes?",    "workflow" ),
    ( "Do you want to update the session plan?",    "meta" ),
] )
def test_classify_lands_on_expected_category( classifier, message, expected ):
    """Each representative message classifies to its intended category."""
    category, confidence = classifier.classify( message )
    assert category == expected
    assert 0.0 < confidence <= 0.95


def test_classify_no_keyword_is_uncategorized( classifier ):
    """A message with no category keywords → uncategorized at 0.0 (best_match_count==0 arm)."""
    category, confidence = classifier.classify( "The sky is azure overhead." )
    assert category == DEFAULT_CATEGORY
    assert confidence == 0.0


def test_classify_empty_string_guard( classifier ):
    """Empty input short-circuits before scanning."""
    assert classifier.classify( "" ) == ( DEFAULT_CATEGORY, 0.0 )


def test_classify_whitespace_only_guard( classifier ):
    """Whitespace-only input is treated as empty."""
    assert classifier.classify( "    \t\n" ) == ( DEFAULT_CATEGORY, 0.0 )


def test_classify_confidence_single_match( classifier ):
    """One keyword match → 0.5 + 0.1 = 0.6."""
    # "permission" keyword 'go ahead' alone, avoiding other categories' keywords.
    category, confidence = classifier.classify( "Please go ahead." )
    assert category == "permission"
    assert confidence == pytest.approx( 0.6 )


def test_classify_confidence_caps_at_095( classifier ):
    """Many matches in one category saturate at the 0.95 cap (the min() arm)."""
    # Stuff the workflow category with >5 of its keywords.
    msg = "commit push merge deploy test run install build release branch"
    category, confidence = classifier.classify( msg )
    assert category == "workflow"
    assert confidence == 0.95


def test_classify_debug_arm_executes( capsys ):
    """debug=True exercises the debug-print branch without changing the verdict."""
    dbg = NotificationCategoryClassifier( debug=True )
    category, _ = dbg.classify( "Should I proceed?" )
    assert category == "permission"
    out = capsys.readouterr().out
    assert "NotificationClassifier" in out


def test_get_categories_returns_six_definitions( classifier ):
    """get_categories exposes the 6-category definition dict with keywords+description."""
    cats = classifier.get_categories()
    assert cats is NOTIFICATION_CATEGORIES
    assert len( cats ) == 6
    for definition in cats.values():
        assert "keywords" in definition and "description" in definition
