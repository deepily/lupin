#!/usr/bin/env python3
"""
Unit tests for the multiple-choice predictor's question headers.

The prediction must use the new question's own headers, never a neighbouring case's.

All tests use mocked dependencies; no live embedding store or database is required.
"""

import json
from unittest.mock import MagicMock

import pytest


# Real stored row, prediction_log id 2a72eaa6 (dev DB, read 2026-11-06, taken from
# io/decision-proxy/2026-11-06-mc-predictions-20-sample.jsonl). PAST_ANSWERS is the answers dict
# a similar past case stored; ACTUAL_VALUE is what the user then answered to the NEW question,
# under that question's own header "Rename vs freeze".
REAL_PAST_ANSWERS = {
    "Guard"       : "I would say to raise it and die loudly but it would also set the cap to something that is parameterizable at runtime AND not likely say, 24K to start with.",
    "P1 freeze"   : "Pin the strings first (Recommended)",
    "M3 fallback" : "Hire legal annotators (Recommended)",
    "Review tier" : "This is something I want to canonize as soon as possible because we need standardized language around these small fixes that don't get proper criticism And think along the lines of swe driven plan critique before implementation. What are your thoughts?",
    "O-1 Exclusion" : "Keep filename-based (Recommended)",
}
REAL_ACTUAL_VALUE = json.loads(
    "{\"answers\":{\"Rename vs freeze\":\"Sam I need you to hold I have to attend to something else right now "
    "Don't do anything on this front Well you can re-ask me set a timer for 20 minutes from now\"}}"
)


def _options( *questions ):
    """Build an options structure from ( header, [labels], multi_select ) triples."""
    return {
        "questions": [
            {
                "header"       : header,
                "multi_select" : multi_select,
                "options"      : [ { "label": label, "description": "" } for label in labels ]
            }
            for header, labels, multi_select in questions
        ]
    }


def _case( answers, similarity=90.0 ):
    """Build one find_similar hit carrying the given answers dict."""
    return ( similarity, { "decision_value": json.dumps( { "answers": answers } ) } )


class TestMultipleChoiceQuestionHeaders:
    """_predict_multiple_choice() keys its answer by the new question's headers."""

    def setup_method( self ):
        from cosa.agents.prediction_engine.prediction_engine import PredictionEngine
        PredictionEngine.reset()

    def teardown_method( self ):
        from cosa.agents.prediction_engine.prediction_engine import PredictionEngine
        PredictionEngine.reset()

    def _engine( self, cases ):
        from cosa.agents.prediction_engine.prediction_engine import PredictionEngine
        engine = PredictionEngine( debug=True )
        engine._embedding_store    = MagicMock()
        engine._embedding_provider = MagicMock()
        engine._embedding_store.find_similar.return_value = cases
        return engine

    def _predict( self, engine, options ):
        return engine._predict_multiple_choice( "Which?", "planning", [ 0.1 ] * 768, options=options )

    def test_real_row_answers_new_header_and_overlaps_actual( self ):
        """A real stored row yields the actual answer's header, so the comparator can compare."""
        from cosa.agents.prediction_engine.accuracy_comparators import compare_multiple_choice_single

        engine  = self._engine( [ _case( REAL_PAST_ANSWERS ) ] )
        options = _options( ( "Rename vs freeze", [ "Pin the strings first (Recommended)", "Rename now" ], False ) )

        result = self._predict( engine, options )

        assert result.strategy == "cbr_majority_vote"
        assert result.predicted_value == { "answers": { "Rename vs freeze": "Pin the strings first (Recommended)" } }
        match, detail = compare_multiple_choice_single( result.predicted_value, REAL_ACTUAL_VALUE )
        assert detail[ "mismatches" ][ 0 ][ "predicted" ] == "Pin the strings first (Recommended)"
        assert detail[ "total" ] == 1

    def test_real_row_before_fix_shape_never_overlapped( self ):
        """Control: the past case's own headers share no key with the actual, which was the defect."""
        assert set( REAL_PAST_ANSWERS ).isdisjoint( REAL_ACTUAL_VALUE[ "answers" ] )

    def test_no_past_header_leaks_into_prediction( self ):
        """Every key of the prediction is one of the new question's headers."""
        engine  = self._engine( [ _case( REAL_PAST_ANSWERS ) ] )
        options = _options( ( "Rename vs freeze", [ "Pin the strings first (Recommended)" ], False ) )

        answers = self._predict( engine, options ).predicted_value[ "answers" ]

        assert set( answers ) == { "Rename vs freeze" }

    def test_same_header_still_votes_directly( self ):
        """A shared header takes the past answer stored under it."""
        engine  = self._engine( [ _case( { "Action": "Push" } ), _case( { "Action": "Push" } ), _case( { "Action": "Done" } ) ] )
        options = _options( ( "Action", [ "Push", "Done" ], False ) )

        assert self._predict( engine, options ).predicted_value == { "answers": { "Action": "Push" } }

    def test_two_new_headers_claim_distinct_past_answers( self ):
        """Two new headers each take one past answer, and a past answer is not reused."""
        engine  = self._engine( [ _case( { "Old1": "Red", "Old2": "Red" } ) ] )
        options = _options( ( "NewA", [ "Red" ], False ), ( "NewB", [ "Red" ], False ) )

        result = self._predict( engine, options )

        assert result.predicted_value == { "answers": { "NewA": "Red", "NewB": "Red" } }

    def test_exact_header_is_claimed_before_label_match( self ):
        """An exact-header match is not borrowed by an earlier new header."""
        engine  = self._engine( [ _case( { "NewB": "Red" } ) ] )
        options = _options( ( "NewA", [ "Red" ], False ), ( "NewB", [ "Red" ], False ) )

        # NewB matches exactly; NewA has nothing left to borrow, so there is no evidence for it.
        result = self._predict( engine, options )

        assert result.strategy == "cold_start"
        assert result.metadata[ "reason" ] == "no_evidence_for_question_headers"

    def test_multi_select_list_filtered_to_offered_labels( self ):
        """A list answer keeps only labels the new header offers."""
        engine  = self._engine( [ _case( { "Old": [ "A", "Z" ] } ), _case( { "Old": [ "A", "Z" ] } ) ] )
        options = _options( ( "New", [ "A", "B" ], True ) )

        result = self._predict( engine, options )

        assert result.predicted_value == { "answers": { "New": [ "A" ] } }

    def test_list_answer_with_no_offered_label_is_skipped( self ):
        """A list answer sharing no label with the new header cannot speak for it."""
        engine  = self._engine( [ _case( { "Old": [ "Z" ] } ) ] )
        options = _options( ( "New", [ "A", "B" ], True ) )

        result = self._predict( engine, options )

        assert result.strategy == "cold_start"
        assert result.metadata[ "reason" ] == "no_valid_mc_cases"

    def test_string_answer_not_offered_is_skipped( self ):
        """A string answer the new header does not offer is ignored."""
        engine  = self._engine( [ _case( { "Old": "something typed by hand" } ) ] )
        options = _options( ( "New", [ "A", "B" ], False ) )

        result = self._predict( engine, options )

        assert result.strategy == "cold_start"
        assert result.metadata[ "reason" ] == "no_valid_mc_cases"

    def test_one_header_without_evidence_makes_whole_prediction_cold_start( self ):
        """If any new header has no evidence, nothing is predicted."""
        engine  = self._engine( [ _case( { "Old": "A" } ) ] )
        options = _options( ( "New1", [ "A" ], False ), ( "New2", [ "Q" ], False ) )

        result = self._predict( engine, options )

        assert result.strategy == "cold_start"
        assert result.predicted_value is None

    def test_exact_header_multi_select_invalid_label_is_constrained( self ):
        """A same-header list holding an unoffered label is trimmed and flagged."""
        engine  = self._engine( [ _case( { "New": [ "A", "Z" ] } ), _case( { "New": [ "A", "Z" ] } ) ] )
        options = _options( ( "New", [ "A", "B" ], True ) )

        result = self._predict( engine, options )

        assert result.predicted_value == { "answers": { "New": [ "A" ] } }
        assert result.metadata[ "constrained" ] is True

    def test_exact_header_multi_select_all_invalid_is_cold_start( self ):
        """A same-header list answer with no offered label leaves nothing to predict."""
        engine  = self._engine( [ _case( { "New": [ "Z" ] } ), _case( { "New": [ "Z" ] } ) ] )
        options = _options( ( "New", [ "A", "B" ], True ) )

        result = self._predict( engine, options )

        assert result.strategy == "cold_start"
        assert result.metadata[ "reason" ] == "no_valid_options_after_filtering"

    def test_no_options_keeps_past_headers( self ):
        """Without an options structure the new headers are unknown, so past headers pass through."""
        engine = self._engine( [ _case( { "Old": "A" } ) ] )

        result = engine._predict_multiple_choice( "Which?", "planning", [ 0.1 ] * 768, options=None )

        assert result.predicted_value == { "answers": { "Old": "A" } }


class TestRemapAnswersToQuestion:
    """_remap_answers_to_question() on its own."""

    def _remap( self, answers, valid_options ):
        from cosa.agents.prediction_engine.prediction_engine import PredictionEngine
        return PredictionEngine._remap_answers_to_question( answers, valid_options )

    def test_empty_answers_give_empty_result( self ):
        """A cancelled case (no answers) contributes nothing."""
        assert self._remap( {}, { "H": { "labels": { "A" }, "multi_select": False } } ) == {}

    def test_exact_header_kept_as_stored( self ):
        """An exact-header answer is kept as stored; validation handles it later."""
        out = self._remap( { "H": "not offered" }, { "H": { "labels": { "A" }, "multi_select": False } } )
        assert out == { "H": "not offered" }
