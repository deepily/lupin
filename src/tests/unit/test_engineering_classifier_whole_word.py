#!/usr/bin/env python3
"""
Whole-word keyword matching in EngineeringClassifier.

The false hits below are the ones the bug row named. A raw substring test matched
"pip" in "pipeline" and "test" in "latest". It also matched "ship" in "relationship"
and "clean" in "cleanly".
"""

import pytest

from cosa.agents.swe_team.proxy.engineering_classifier import EngineeringClassifier, keyword_in_text


@pytest.fixture
def classifier():
    return EngineeringClassifier( debug=False )


@pytest.mark.parametrize( "question, wrong_category", [
    ( "Should we rebuild the pipeline?",                     "deps"        ),
    ( "Is this the latest build?",                          "testing"     ),
    ( "What is the relationship between these services?",   "deployment"  ),
    ( "The job exits cleanly on empty input, keep it?",     "destructive" ),
])
def test_substring_false_hit_is_not_classified( classifier, question, wrong_category ):
    category, confidence = classifier.classify( question )
    assert category == "general"
    assert confidence == pytest.approx( 0.3 )


@pytest.mark.parametrize( "question, expected", [
    ( "Should we pip install this?",             "deps"        ),
    ( "Run the test suite now?",                 "testing"     ),
    ( "Ship it?",                                "deployment"  ),
    ( "Clean the build directory?",              "destructive" ),
    ( "OK to run rm -rf on the cache?",          "destructive" ),
    ( "Bump requirements.txt?",                  "deps"        ),
])
def test_whole_word_and_phrase_still_match( classifier, question, expected ):
    category, _ = classifier.classify( question )
    assert category == expected


MAYA_ACCEPTANCE_WORDS = [
    ( "deployments",   "deployment"  ),
    ( "deployer",      "deployment"  ),
    ( "containers",    "deployment"  ),
    ( "containerized", "deployment"  ),
    ( "dockerfile",    "deployment"  ),
    ( "dockerized",    "deployment"  ),
    ( "rollbacks",     "deployment"  ),
    ( "truncated",     "destructive" ),
    ( "truncates",     "destructive" ),
    ( "purges",        "destructive" ),
    ( "wipes",         "destructive" ),
    ( "nukes",         "destructive" ),
    ( "cleanup",       "destructive" ),
    ( "cleanups",      "destructive" ),
]


@pytest.mark.parametrize( "word, expected", MAYA_ACCEPTANCE_WORDS )
def test_capped_words_the_substring_match_caught_still_match( classifier, word, expected ):
    category, _ = classifier.classify( f"Check the {word}?" )
    assert category == expected


@pytest.mark.parametrize( "question, expected", [
    ( "I deleted the old bucket, continue?",   "destructive" ),
    ( "We are removing the old table, ok?",    "destructive" ),
    ( "The old rows were dropped, continue?",  "destructive" ),
    ( "It was deployed to prod, roll forward?", "deployment" ),
])
def test_inflected_forms_follow_the_suffix_rule( classifier, question, expected ):
    category, _ = classifier.classify( question )
    assert category == expected


def test_short_keyword_takes_only_a_plural():
    assert keyword_in_text( "pip", "two pips" )
    assert not keyword_in_text( "pip", "the pipes" )


def test_keyword_in_text_boundaries():
    assert keyword_in_text( "pip", "use pip." )
    assert not keyword_in_text( "pip", "the pipeline" )
    assert not keyword_in_text( "test", "latest" )
    assert not keyword_in_text( "test", "test_utils" )
    assert keyword_in_text( "rm -rf", "run rm -rf now" )
    assert not keyword_in_text( "rm -rf", "run rm -rfx now" )
