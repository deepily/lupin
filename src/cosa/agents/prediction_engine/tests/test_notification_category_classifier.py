"""
Unit tests for prediction_engine/notification_category_classifier.py.

Coverage target: 100% lines + branches + functions on production logic.
quick_smoke_test() + __main__ guard are excluded by pyproject.toml
[tool.coverage.report].exclude_also, so they are not exercised.

Keyword classifier — pure string logic, no LLM / network / API to mock.
Assertions harvested from the in-module quick_smoke_test (D2 pipeline).
"""
import pytest

from cosa.agents.prediction_engine.notification_category_classifier import (
    NotificationCategoryClassifier,
    NOTIFICATION_CATEGORIES,
    DEFAULT_CATEGORY,
)


# --------------------------------------------------------------------------- #
# __init__
# --------------------------------------------------------------------------- #
def test_init_defaults():
    clf = NotificationCategoryClassifier()
    assert clf.debug is False
    assert clf.categories is NOTIFICATION_CATEGORIES


def test_init_debug_true():
    clf = NotificationCategoryClassifier( debug=True )
    assert clf.debug is True


# --------------------------------------------------------------------------- #
# classify — empty-input early return ( the `or` branch matrix )
# --------------------------------------------------------------------------- #
def test_classify_none_returns_uncategorized():
    # first operand `not question` True ( None ) → short-circuit
    clf = NotificationCategoryClassifier()
    assert clf.classify( None ) == ( DEFAULT_CATEGORY, 0.0 )


def test_classify_empty_string_returns_uncategorized():
    clf = NotificationCategoryClassifier()
    assert clf.classify( "" ) == ( DEFAULT_CATEGORY, 0.0 )


def test_classify_whitespace_only_returns_uncategorized():
    # first operand False ( "   " is truthy ), second operand `not strip()` True
    clf = NotificationCategoryClassifier()
    assert clf.classify( "   " ) == ( DEFAULT_CATEGORY, 0.0 )


# --------------------------------------------------------------------------- #
# classify — categorisation ( harvested expectations )
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize( "message,expected", [
    ( "Should I proceed with the refactor?",        "permission" ),
    ( "Are you sure you want to delete this file?", "confirmation" ),
    ( "Which approach should we use for caching?",  "approach" ),
    ( "What name should the new module have?",      "input" ),
    ( "Should I commit and push these changes?",    "workflow" ),
    ( "Do you want to update the session plan?",    "meta" ),
] )
def test_classify_known_categories( message, expected ):
    clf = NotificationCategoryClassifier()
    category, confidence = clf.classify( message )
    assert category == expected
    assert 0.5 <= confidence <= 0.95


def test_classify_no_keyword_match_returns_uncategorized():
    # non-empty, strips to non-empty, but matches zero keywords →
    # best_match_count == 0 branch → ( uncategorized, 0.0 )
    clf = NotificationCategoryClassifier()
    assert clf.classify( "xyzzy qwerty zzz" ) == ( DEFAULT_CATEGORY, 0.0 )


def test_classify_confidence_scales_with_match_count():
    # single keyword match → 0.5 + 0.1 = 0.6
    clf = NotificationCategoryClassifier()
    _, conf = clf.classify( "go ahead" )
    assert conf == pytest.approx( 0.6 )


def test_classify_confidence_capped_at_0_95():
    # craft a message hitting >=5 keywords in one category so 0.5 + n*0.1 > 0.95 → capped
    # workflow keywords: commit push merge deploy test run install build release branch
    clf = NotificationCategoryClassifier()
    msg = "commit push merge deploy test run install build"   # 8 workflow keyword hits
    category, conf = clf.classify( msg )
    assert category == "workflow"
    assert conf == 0.95


def test_classify_debug_branch_prints( capsys ):
    # debug=True + a matching message reaches the `if self.debug: print(...)` line
    clf = NotificationCategoryClassifier( debug=True )
    clf.classify( "Should I proceed?" )
    out = capsys.readouterr().out
    assert "NotificationClassifier" in out


def test_classify_no_debug_no_print( capsys ):
    # debug=False ( default ) → the print branch is the False arc
    clf = NotificationCategoryClassifier()
    clf.classify( "Should I proceed?" )
    out = capsys.readouterr().out
    assert out == ""


# --------------------------------------------------------------------------- #
# get_categories
# --------------------------------------------------------------------------- #
def test_get_categories_returns_six():
    clf = NotificationCategoryClassifier()
    cats = clf.get_categories()
    assert len( cats ) == 6
    assert set( cats.keys() ) == { "permission", "confirmation", "approach", "input", "workflow", "meta" }
    for definition in cats.values():
        assert "keywords" in definition
        assert "description" in definition
