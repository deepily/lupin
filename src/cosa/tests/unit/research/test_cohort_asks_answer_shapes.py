"""
cohort_asks reads each stored answer shape that lupin_db_dev holds.

The three literals below were read from scored prediction_log rows on lupin_db_dev, read-only.
All 2,411 scored multiple-choice rows held the answers shape and none held a value key.
"""

import json
import pytest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

from cosa.research.preference_replay.cohorts import answer_source_of, cohort_asks

YES_NO_STORED          = { "value": "yes" }
OPEN_ENDED_STORED      = { "value": "[cancelled]" }
MULTIPLE_CHOICE_STORED = { "answers": { "Script Review": "Approve script" } }


class _Session:
    """Answers session.get with a notification and no prediction_decisions row."""

    def get( self, model, key ):
        if model.__name__ == "Notification":
            return SimpleNamespace( title="t", message="m", sender_id="s", created_at=datetime( 2026, 11, 1, tzinfo=timezone.utc ),
                                    recipient_id="r", response_options=None, response_value=None )
        return None


def _row( response_type, stored ):
    return SimpleNamespace( notification_id="n1", category="c", response_type=response_type, responded_at=None, asked_at=None,
                            predicted_at=datetime( 2026, 11, 10, tzinfo=timezone.utc ), actual_value=stored,
                            predicted_value=stored, accuracy_match=True )


def _asks( response_type, stored ):
    with patch( "cosa.research.preference_replay.cohorts.scored_rows", return_value=[ _row( response_type, stored ) ] ):
        return cohort_asks( _Session(), response_type, vectors={} )


def test_a_multiple_choice_row_with_only_answers_is_built_and_its_decision_value_is_the_dict_as_json_text():
    asks = _asks( "multiple_choice", MULTIPLE_CHOICE_STORED )
    assert len( asks ) == 1
    assert asks[ 0 ][ "decision_value" ] == '{"answers": {"Script Review": "Approve script"}}'
    assert asks[ 0 ][ "actual_value" ] == MULTIPLE_CHOICE_STORED


def test_a_multiple_choice_row_with_two_answers_stored_out_of_order_gets_sorted_json_text():
    stored = { "answers": { "Zeta Review": "Reject", "Alpha Review": "Approve" } }
    assert _asks( "multiple_choice", stored )[ 0 ][ "decision_value" ] == '{"answers": {"Alpha Review": "Approve", "Zeta Review": "Reject"}}'


def test_a_yes_no_row_keeps_its_value_as_the_decision_value():
    assert _asks( "yes_no", YES_NO_STORED )[ 0 ][ "decision_value" ] == "yes"


def test_an_open_ended_row_keeps_its_value_as_the_decision_value():
    assert _asks( "open_ended", OPEN_ENDED_STORED )[ 0 ][ "decision_value" ] == "[cancelled]"


@pytest.mark.parametrize( "value,expected", [
    ( { "source": "ui" },                  "human" ),
    ( json.dumps( { "source": "ui" } ),    "human" ),
    ( { "source": "timeout_default" },     "unknown" ),
    ( { "value": "yes" },                  "unknown" ),
    ( None,                                "unknown" ),
] )
def test_an_answer_is_human_only_when_its_source_is_ui( value, expected ):
    assert answer_source_of( value ) == expected


class _MarkedSession:
    """Answers session.get with a UI-answered notification whose ask may carry the marker."""

    def __init__( self, options ):
        self.options = options

    def get( self, model, key ):
        if model.__name__ == "Notification":
            return SimpleNamespace( title="t", message="m", sender_id="s", created_at=datetime( 2026, 11, 1, tzinfo=timezone.utc ),
                                    recipient_id="r", response_options=self.options, response_value={ "value": "yes", "source": "ui" } )
        return None


@pytest.mark.parametrize( "options,expected", [ ( { "review_card": True }, "review_card" ), ( None, "human" ), ( { "review_card": False }, "human" ) ] )
def test_a_cohort_ask_takes_its_answer_source_from_the_ask_options_and_not_from_the_ui_source( options, expected ):
    with patch( "cosa.research.preference_replay.cohorts.scored_rows", return_value=[ _row( "yes_no", YES_NO_STORED ) ] ):
        asks = cohort_asks( _MarkedSession( options ), "yes_no", vectors={} )
    assert [ ask[ "answer_source" ] for ask in asks ] == [ expected ]
