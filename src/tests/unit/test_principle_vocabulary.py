"""
The 14 approved dimension headings and the 60 old dimension names they replace.

The expected values are literals copied from the approved draft,
io/tmp/principle-learner-briefs/2026.11.19-ph1-dimension-vocabulary-draft.md.
So a change to the module cannot also change what the test expects.
"""

from collections import Counter

import pytest

from cosa.agents.principle_learner import vocabulary
from cosa.agents.principle_learner.extractor_prompt import PROMPT_VERSION, SYSTEM_PROMPT

APPROVED = [
    "Keep changes small and in scope", "Fix the real cause", "Tests must earn their keep", "Evidence before decisions",
    "Review and release gates", "Spend, limits and fleet capacity", "Settings live in one place", "Scripted, repeatable operations",
    "Tidy documents and old work", "How to ask me", "Save my attention", "Interface, alerts and interruptions",
    "Security and exposure", "Timing and deferral",
]

# old names per heading, counted from the draft's placement table
PER_HEADING = {
    "Keep changes small and in scope"     : 5,
    "Fix the real cause"                  : 4,
    "Tests must earn their keep"          : 4,
    "Evidence before decisions"           : 5,
    "Review and release gates"            : 4,
    "Spend, limits and fleet capacity"    : 6,
    "Settings live in one place"          : 3,
    "Scripted, repeatable operations"     : 5,
    "Tidy documents and old work"         : 3,
    "How to ask me"                       : 6,
    "Save my attention"                   : 4,
    "Interface, alerts and interruptions" : 4,
    "Security and exposure"               : 4,
    "Timing and deferral"                 : 3,
}


def test_the_vocabulary_is_the_fourteen_approved_headings_in_order_and_dated():
    assert list( vocabulary.HEADINGS ) == APPROVED and len( set( vocabulary.HEADINGS ) ) == 14
    assert vocabulary.VOCABULARY_VERSION == "2026.11.19"


def test_sixty_old_names_map_onto_exactly_the_fourteen_headings():
    assert len( vocabulary.LEGACY_HEADINGS ) == 60
    assert set( vocabulary.LEGACY_HEADINGS.values() ) == set( APPROVED )
    assert sum( PER_HEADING.values() ) == 60
    assert Counter( vocabulary.LEGACY_HEADINGS.values() ) == PER_HEADING


@pytest.mark.parametrize( "old, heading", [
    ( "dead_code_handling", "Fix the real cause" ),
    ( "research_scope", "Evidence before decisions" ),
    ( "validation_target_choice", "Evidence before decisions" ),
    ( "timeout", "Spend, limits and fleet capacity" ),
    ( "infrastructure_reproducibility", "Scripted, repeatable operations" ),
    ( "playback_interruption", "Interface, alerts and interruptions" ),
] )
def test_named_placements_from_the_draft_hold( old, heading ):
    assert vocabulary.LEGACY_HEADINGS[ old ] == heading and vocabulary.heading_for( old ) == heading


def test_is_heading_matches_exactly_and_nothing_else():
    assert vocabulary.is_heading( "Fix the real cause" )
    assert not vocabulary.is_heading( "fix the real cause" )
    assert not vocabulary.is_heading( "fix_depth" )
    assert not vocabulary.is_heading( None )


def test_heading_for_keeps_a_heading_maps_an_old_name_and_never_guesses_an_unknown_one():
    assert vocabulary.heading_for( "How to ask me" ) == "How to ask me"
    assert vocabulary.heading_for( "question_deduplication" ) == "How to ask me"
    assert vocabulary.heading_for( "ask.approval_needs_link" ) is None
    assert vocabulary.heading_for( None ) is None


def test_the_headings_block_numbers_every_heading_once_in_order():
    lines = vocabulary.headings_block().split( "\n" )
    assert lines[ 0 ] == "1. Keep changes small and in scope" and lines[ -1 ] == "14. Timing and deferral" and len( lines ) == 14


def test_the_extractor_prompt_carries_every_heading_and_a_new_prompt_version():
    assert PROMPT_VERSION == "extractor-v2-vocab-2026.11.19"
    for number, heading in enumerate( APPROVED, start=1 ): assert f"\n{number}. {heading}" in SYSTEM_PROMPT
    assert "must be one of the owner's headings" in SYSTEM_PROMPT


def test_shown_dimension_and_same_heading_read_old_names_as_their_heading_and_compare_unknown_names_exactly():
    assert vocabulary.shown_dimension( "fix_depth" ) == "Fix the real cause"
    assert vocabulary.shown_dimension( "ask.x" ) == "ask.x" and vocabulary.shown_dimension( None ) is None
    assert vocabulary.same_heading( "fix_depth", "Fix the real cause" ) and vocabulary.same_heading( "fix_depth", "scope_completeness_expectation" )
    assert not vocabulary.same_heading( "fix_depth", "How to ask me" )
    assert vocabulary.same_heading( "ask.x", "ask.x" ) and not vocabulary.same_heading( "ask.x", "ask.y" )
