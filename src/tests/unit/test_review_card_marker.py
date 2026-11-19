"""
The review-card marker and the answer source it decides.

The marker is `review_card: true` in the ask's response_options. Every filter reads it from the ask alone.
So these tests pose the stored answer with and without a copy of the marker and expect the same label.
"""
import json

import pytest

from cosa.agents.prediction_engine.review_card import REVIEW_CARD_KEY, REVIEW_CARD_SOURCE, is_review_card
from cosa.research.preference_replay.cohorts import answer_source_of


@pytest.mark.parametrize( "options,expected", [
    ( { "review_card": True },                       True ),
    ( json.dumps( { "review_card": True } ),         True ),
    ( { "review_card": True, "questions": [] },      True ),
    ( { "review_card": False },                      False ),
    ( { "review_card": "true" },                     False ),
    ( { "review_card": 1 },                          False ),
    ( { "questions": [] },                           False ),
    ( json.dumps( { "review_card": False } ),        False ),
    ( json.dumps( [ "review_card" ] ),               False ),
    ( [ { "review_card": True } ],                   False ),
    ( None,                                          False ),
] )
def test_only_an_object_with_the_key_exactly_true_is_a_review_card( options, expected ):
    assert is_review_card( options ) is expected


def test_the_key_and_the_source_are_the_names_the_ruling_gave():
    assert REVIEW_CARD_KEY == "review_card" and REVIEW_CARD_SOURCE == "review_card"


@pytest.mark.parametrize( "value", [ { "source": "ui" }, { "value": "yes", "source": "ui", "marker": "review_card" },
                                     json.dumps( { "source": "ui" } ), None ] )
def test_a_marked_ask_is_never_labelled_human_whatever_the_stored_answer_says( value ):
    assert answer_source_of( value, { "review_card": True } ) == "review_card"


def test_the_label_depends_on_the_ask_and_not_on_a_copy_in_the_answer():
    copied = { "value": "yes", "source": "ui", "marker": "review_card" }
    assert answer_source_of( copied, None ) == "human", "a copy on the answer decides nothing"
    assert answer_source_of( copied, { "questions": [] } ) == "human"
    assert answer_source_of( { "value": "yes", "source": "ui" }, { "review_card": True } ) == "review_card"


def test_an_unmarked_ask_keeps_the_old_labels():
    assert answer_source_of( { "source": "ui" } ) == "human"
    assert answer_source_of( { "source": "timeout_default" }, { "review_card": False } ) == "unknown"
