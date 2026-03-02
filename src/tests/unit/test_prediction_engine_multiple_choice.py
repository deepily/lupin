#!/usr/bin/env python3
"""
Unit tests for Slice 2 + 3: Multiple choice CBR majority vote prediction.

Tests for:
    - _parse_mc_decision_value() JSON parsing edge cases
    - _predict_multiple_choice() CBR majority vote logic (single + multi-select)
    - _tally_multi_select_votes() option frequency counting
    - _store_decision() answers-dict serialization
    - get_comparator() data-driven dispatch for multi-select

All tests use mocked dependencies — no live embedding store or database required.
"""

import json
import pytest
from unittest.mock import MagicMock, patch


# ===========================================================================
# TestParseMcDecisionValue — JSON parsing of multiple_choice decision values
# ===========================================================================

class TestParseMcDecisionValue:
    """Tests for _parse_mc_decision_value() static method."""

    def _parse( self, value ):
        """Helper to call the static method."""
        from cosa.agents.prediction_engine.prediction_engine import PredictionEngine
        return PredictionEngine._parse_mc_decision_value( value )

    def test_valid_answers_json( self ):
        """Parse valid JSON with answers key."""
        result = self._parse( json.dumps( { "answers": { "Database": "PostgreSQL" } } ) )
        assert result == { "answers": { "Database": "PostgreSQL" } }

    def test_raw_dict_json_no_answers_key( self ):
        """JSON dict without answers key returns None."""
        result = self._parse( json.dumps( { "value": "PostgreSQL" } ) )
        assert result is None

    def test_empty_string( self ):
        """Empty string returns None."""
        result = self._parse( "" )
        assert result is None

    def test_non_json_string( self ):
        """Non-JSON string returns None."""
        result = self._parse( "just a plain string" )
        assert result is None

    def test_none_input( self ):
        """None input returns None."""
        result = self._parse( None )
        assert result is None

    def test_multi_header_answers( self ):
        """Parse JSON with multiple headers in answers."""
        data = { "answers": { "Database": "PostgreSQL", "Cache": "Redis" } }
        result = self._parse( json.dumps( data ) )
        assert result == data


# ===========================================================================
# TestPredictMultipleChoiceSingle — CBR majority vote for MC predictions
# ===========================================================================

class TestPredictMultipleChoice:
    """Tests for _predict_multiple_choice() method (single-select)."""

    def setup_method( self ):
        """Reset singleton before each test."""
        from cosa.agents.prediction_engine.prediction_engine import PredictionEngine
        PredictionEngine.reset()

    def teardown_method( self ):
        """Reset singleton after each test."""
        from cosa.agents.prediction_engine.prediction_engine import PredictionEngine
        PredictionEngine.reset()

    def _make_engine( self ):
        """Create a PredictionEngine with mocked dependencies."""
        from cosa.agents.prediction_engine.prediction_engine import PredictionEngine

        engine = PredictionEngine( debug=True )

        # Mock embedding store
        engine._embedding_store    = MagicMock()
        engine._embedding_provider = MagicMock()

        return engine

    def test_cold_start_no_embedding( self ):
        """No embedding → cold_start."""
        engine = self._make_engine()

        result = engine._predict_multiple_choice( "Pick a DB", "approach", None )

        assert result.strategy == "cold_start"
        assert result.metadata[ "reason" ] == "no_embedding"

    def test_cold_start_no_store( self ):
        """No embedding store → cold_start."""
        engine = self._make_engine()
        engine._get_embedding_store = MagicMock( return_value=None )

        result = engine._predict_multiple_choice( "Pick a DB", "approach", [ 0.1 ] * 768 )

        assert result.strategy == "cold_start"
        assert result.metadata[ "reason" ] == "no_embedding_store"

    def test_cold_start_no_cases( self ):
        """No similar cases found → cold_start."""
        engine = self._make_engine()
        engine._embedding_store.find_similar.return_value = []

        result = engine._predict_multiple_choice( "Pick a DB", "approach", [ 0.1 ] * 768 )

        assert result.strategy == "cold_start"
        assert result.metadata[ "reason" ] == "no_similar_cases"

    def test_single_header_majority( self ):
        """Three cases with same header → majority vote winner."""
        engine = self._make_engine()

        engine._embedding_store.find_similar.return_value = [
            ( 95.0, { "decision_value": json.dumps( { "answers": { "Database": "PostgreSQL" } } ) } ),
            ( 90.0, { "decision_value": json.dumps( { "answers": { "Database": "PostgreSQL" } } ) } ),
            ( 85.0, { "decision_value": json.dumps( { "answers": { "Database": "MongoDB" } } ) } ),
        ]

        result = engine._predict_multiple_choice( "Which database?", "approach", [ 0.1 ] * 768 )

        assert result.strategy == "cbr_majority_vote"
        assert result.predicted_value == { "answers": { "Database": "PostgreSQL" } }
        assert result.confidence > 0

    def test_split_vote( self ):
        """Split vote (1 vs 1) resolves by dict ordering (first max wins)."""
        engine = self._make_engine()

        engine._embedding_store.find_similar.return_value = [
            ( 95.0, { "decision_value": json.dumps( { "answers": { "Database": "PostgreSQL" } } ) } ),
            ( 90.0, { "decision_value": json.dumps( { "answers": { "Database": "MongoDB" } } ) } ),
        ]

        result = engine._predict_multiple_choice( "Which database?", "approach", [ 0.1 ] * 768 )

        assert result.strategy == "cbr_majority_vote"
        # Winner is whichever max() picks — both have 1 vote
        assert result.predicted_value[ "answers" ][ "Database" ] in [ "PostgreSQL", "MongoDB" ]

    def test_multi_header( self ):
        """Multiple headers with majority vote per header."""
        engine = self._make_engine()

        engine._embedding_store.find_similar.return_value = [
            ( 95.0, { "decision_value": json.dumps( { "answers": { "Database": "PostgreSQL", "Cache": "Redis" } } ) } ),
            ( 90.0, { "decision_value": json.dumps( { "answers": { "Database": "PostgreSQL", "Cache": "Memcached" } } ) } ),
            ( 85.0, { "decision_value": json.dumps( { "answers": { "Database": "MongoDB", "Cache": "Redis" } } ) } ),
        ]

        result = engine._predict_multiple_choice( "Pick stack", "approach", [ 0.1 ] * 768 )

        assert result.predicted_value[ "answers" ][ "Database" ] == "PostgreSQL"  # 2/3
        assert result.predicted_value[ "answers" ][ "Cache" ] == "Redis"          # 2/3

    def test_confidence_calculation( self ):
        """Confidence = max_similarity * avg_consistency."""
        engine = self._make_engine()

        # All 3 agree on same answer → consistency = 1.0
        engine._embedding_store.find_similar.return_value = [
            ( 90.0, { "decision_value": json.dumps( { "answers": { "DB": "PG" } } ) } ),
            ( 80.0, { "decision_value": json.dumps( { "answers": { "DB": "PG" } } ) } ),
            ( 70.0, { "decision_value": json.dumps( { "answers": { "DB": "PG" } } ) } ),
        ]

        result = engine._predict_multiple_choice( "Pick", "approach", [ 0.1 ] * 768 )

        # max_similarity = 90/100 = 0.9, consistency = 3/3 = 1.0
        expected_confidence = 0.9 * 1.0
        assert abs( result.confidence - expected_confidence ) < 0.01

    def test_invalid_decision_values_gracefully_ignored( self ):
        """Non-JSON decision values are skipped, valid ones still work."""
        engine = self._make_engine()

        engine._embedding_store.find_similar.return_value = [
            ( 95.0, { "decision_value": "not json at all" } ),
            ( 90.0, { "decision_value": json.dumps( { "answers": { "DB": "PG" } } ) } ),
            ( 85.0, { "decision_value": json.dumps( { "value": "wrong format" } ) } ),
        ]

        result = engine._predict_multiple_choice( "Pick DB", "approach", [ 0.1 ] * 768 )

        assert result.strategy == "cbr_majority_vote"
        assert result.predicted_value == { "answers": { "DB": "PG" } }
        assert result.metadata[ "valid_cases" ] == 1

    def test_all_invalid_decision_values( self ):
        """All invalid decision values → cold_start (no valid MC cases)."""
        engine = self._make_engine()

        engine._embedding_store.find_similar.return_value = [
            ( 95.0, { "decision_value": "not json" } ),
            ( 90.0, { "decision_value": "" } ),
        ]

        result = engine._predict_multiple_choice( "Pick DB", "approach", [ 0.1 ] * 768 )

        assert result.strategy == "cold_start"
        assert result.metadata[ "reason" ] == "no_valid_mc_cases"

    def test_predicted_value_format( self ):
        """predicted_value is a dict with "answers" key."""
        engine = self._make_engine()

        engine._embedding_store.find_similar.return_value = [
            ( 95.0, { "decision_value": json.dumps( { "answers": { "Framework": "FastAPI" } } ) } ),
        ]

        result = engine._predict_multiple_choice( "Pick framework", "approach", [ 0.1 ] * 768 )

        assert isinstance( result.predicted_value, dict )
        assert "answers" in result.predicted_value
        assert result.predicted_value[ "answers" ][ "Framework" ] == "FastAPI"


# ===========================================================================
# TestStoreDecisionMultipleChoice — LanceDB storage for MC actual values
# ===========================================================================

class TestStoreDecisionMultipleChoice:
    """Tests for _store_decision() answers-dict serialization."""

    def setup_method( self ):
        """Reset singleton before each test."""
        from cosa.agents.prediction_engine.prediction_engine import PredictionEngine
        PredictionEngine.reset()

    def teardown_method( self ):
        """Reset singleton after each test."""
        from cosa.agents.prediction_engine.prediction_engine import PredictionEngine
        PredictionEngine.reset()

    def _make_engine( self ):
        """Create a PredictionEngine with mocked dependencies."""
        from cosa.agents.prediction_engine.prediction_engine import PredictionEngine

        engine = PredictionEngine( debug=True )

        engine._embedding_store    = MagicMock()
        engine._embedding_provider = MagicMock()
        engine._embedding_provider.generate_embedding.return_value = [ 0.1 ] * 768

        return engine

    def _make_prediction_result( self, original_message="Test question" ):
        """Create a minimal PredictionResult with original_message in metadata."""
        from cosa.agents.prediction_engine.prediction_result import PredictionResult

        return PredictionResult(
            response_type  = "multiple_choice",
            category       = "approach",
            strategy       = "cold_start",
            metadata       = { "original_message": original_message }
        )

    def test_answers_dict_serialized_as_json( self ):
        """Dict with answers key is serialized as JSON string."""
        engine = self._make_engine()
        result = self._make_prediction_result()

        actual_value = { "answers": { "Database": "PostgreSQL" } }
        engine._store_decision( "test-id-1", result, actual_value, "multiple_choice" )

        call_args = engine._embedding_store.add_decision.call_args
        decision_value = call_args.kwargs[ "decision_value" ]
        parsed = json.loads( decision_value )
        assert parsed == { "answers": { "Database": "PostgreSQL" } }

    def test_value_dict_preserved( self ):
        """Dict with value key (not answers) stores value string."""
        engine = self._make_engine()
        result = self._make_prediction_result()

        actual_value = { "value": "yes" }
        engine._store_decision( "test-id-2", result, actual_value, "yes_no" )

        call_args = engine._embedding_store.add_decision.call_args
        decision_value = call_args.kwargs[ "decision_value" ]
        assert decision_value == "yes"

    def test_string_preserved( self ):
        """Plain string actual_value is stored as-is."""
        engine = self._make_engine()
        result = self._make_prediction_result()

        engine._store_decision( "test-id-3", result, "yes", "yes_no" )

        call_args = engine._embedding_store.add_decision.call_args
        decision_value = call_args.kwargs[ "decision_value" ]
        assert decision_value == "yes"


# ===========================================================================
# TestTallyMultiSelectVotes — multi-select option frequency counting
# ===========================================================================

class TestTallyMultiSelectVotes:
    """Tests for _tally_multi_select_votes() method."""

    def setup_method( self ):
        """Reset singleton before each test."""
        from cosa.agents.prediction_engine.prediction_engine import PredictionEngine
        PredictionEngine.reset()

    def teardown_method( self ):
        """Reset singleton after each test."""
        from cosa.agents.prediction_engine.prediction_engine import PredictionEngine
        PredictionEngine.reset()

    def _make_engine( self ):
        """Create a PredictionEngine with mocked dependencies."""
        from cosa.agents.prediction_engine.prediction_engine import PredictionEngine

        engine = PredictionEngine( debug=True )
        engine._embedding_store    = MagicMock()
        engine._embedding_provider = MagicMock()
        return engine

    def test_unanimous_options_included( self ):
        """All options chosen by all cases are included."""
        engine = self._make_engine()

        header_counts = { "Features": { "Auth": 3, "Caching": 3 } }
        predicted, consistency = engine._tally_multi_select_votes( header_counts, 3 )

        assert "Auth" in predicted[ "Features" ]
        assert "Caching" in predicted[ "Features" ]
        assert consistency == 1.0

    def test_50_percent_threshold_boundary( self ):
        """Options at exactly 50% inclusion rate are included."""
        engine = self._make_engine()

        # 2 out of 4 cases = exactly 50%
        header_counts = { "Features": { "Auth": 4, "Caching": 2, "Logging": 1 } }
        predicted, consistency = engine._tally_multi_select_votes( header_counts, 4 )

        assert "Auth" in predicted[ "Features" ]
        assert "Caching" in predicted[ "Features" ]
        assert "Logging" not in predicted[ "Features" ]

    def test_no_option_meets_threshold_fallback( self ):
        """When no option meets 50% threshold, highest-count option is fallback."""
        engine = self._make_engine()

        # All options below 50%: 2/5, 1/5, 1/5
        header_counts = { "Features": { "Auth": 2, "Caching": 1, "Logging": 1 } }
        predicted, consistency = engine._tally_multi_select_votes( header_counts, 5 )

        assert predicted[ "Features" ] == [ "Auth" ]
        assert consistency > 0

    def test_multiple_headers( self ):
        """Multiple headers each tallied independently."""
        engine = self._make_engine()

        header_counts = {
            "Features" : { "Auth": 3, "Caching": 3 },
            "Database" : { "PostgreSQL": 3, "MongoDB": 1 },
        }
        predicted, consistency = engine._tally_multi_select_votes( header_counts, 3 )

        assert "Auth" in predicted[ "Features" ]
        assert "Caching" in predicted[ "Features" ]
        assert predicted[ "Database" ] == [ "PostgreSQL" ]

    def test_results_are_sorted( self ):
        """Selected options are returned in sorted order."""
        engine = self._make_engine()

        header_counts = { "Features": { "Caching": 3, "Auth": 3, "Logging": 3 } }
        predicted, _ = engine._tally_multi_select_votes( header_counts, 3 )

        assert predicted[ "Features" ] == [ "Auth", "Caching", "Logging" ]


# ===========================================================================
# TestPredictMultipleChoiceMultiSelect — multi-select CBR integration
# ===========================================================================

class TestPredictMultipleChoiceMultiSelect:
    """Tests for _predict_multiple_choice() with multi-select seeded data."""

    def setup_method( self ):
        """Reset singleton before each test."""
        from cosa.agents.prediction_engine.prediction_engine import PredictionEngine
        PredictionEngine.reset()

    def teardown_method( self ):
        """Reset singleton after each test."""
        from cosa.agents.prediction_engine.prediction_engine import PredictionEngine
        PredictionEngine.reset()

    def _make_engine( self ):
        """Create a PredictionEngine with mocked dependencies."""
        from cosa.agents.prediction_engine.prediction_engine import PredictionEngine

        engine = PredictionEngine( debug=True )
        engine._embedding_store    = MagicMock()
        engine._embedding_provider = MagicMock()
        return engine

    def test_multi_select_predict_returns_lists( self ):
        """Multi-select seeded data produces list values in predicted_value."""
        engine = self._make_engine()

        engine._embedding_store.find_similar.return_value = [
            ( 95.0, { "decision_value": json.dumps( { "answers": { "Features": [ "Auth", "Caching" ] } } ) } ),
            ( 90.0, { "decision_value": json.dumps( { "answers": { "Features": [ "Auth", "Caching" ] } } ) } ),
            ( 85.0, { "decision_value": json.dumps( { "answers": { "Features": [ "Auth", "Logging" ] } } ) } ),
        ]

        result = engine._predict_multiple_choice( "Which features?", "approach", [ 0.1 ] * 768 )

        assert result.strategy == "cbr_majority_vote"
        features = result.predicted_value[ "answers" ][ "Features" ]
        assert isinstance( features, list )
        assert "Auth" in features  # 3/3 = 100%
        assert "Caching" in features  # 2/3 = 67%
        assert result.metadata[ "multi_select" ] is True

    def test_multi_select_below_threshold_excluded( self ):
        """Options below 50% threshold are excluded from prediction."""
        engine = self._make_engine()

        engine._embedding_store.find_similar.return_value = [
            ( 95.0, { "decision_value": json.dumps( { "answers": { "Features": [ "Auth", "Caching" ] } } ) } ),
            ( 90.0, { "decision_value": json.dumps( { "answers": { "Features": [ "Auth" ] } } ) } ),
            ( 85.0, { "decision_value": json.dumps( { "answers": { "Features": [ "Auth" ] } } ) } ),
        ]

        result = engine._predict_multiple_choice( "Which features?", "approach", [ 0.1 ] * 768 )

        features = result.predicted_value[ "answers" ][ "Features" ]
        assert "Auth" in features      # 3/3 = 100%
        assert "Caching" not in features  # 1/3 = 33% < 50%

    def test_single_select_still_works( self ):
        """Single-select data (string values) still produces string predictions."""
        engine = self._make_engine()

        engine._embedding_store.find_similar.return_value = [
            ( 95.0, { "decision_value": json.dumps( { "answers": { "Database": "PostgreSQL" } } ) } ),
            ( 90.0, { "decision_value": json.dumps( { "answers": { "Database": "PostgreSQL" } } ) } ),
        ]

        result = engine._predict_multiple_choice( "Which database?", "approach", [ 0.1 ] * 768 )

        assert result.strategy == "cbr_majority_vote"
        assert result.predicted_value[ "answers" ][ "Database" ] == "PostgreSQL"
        assert result.metadata[ "multi_select" ] is False


# ===========================================================================
# TestGetComparatorDispatch — data-driven comparator dispatch
# ===========================================================================

class TestGetComparatorDispatch:
    """Tests for get_comparator() data-driven dispatch."""

    def test_single_select_actual_returns_single_comparator( self ):
        """Single-select actual_value → compare_multiple_choice_single."""
        from cosa.agents.prediction_engine.accuracy_comparators import (
            get_comparator, compare_multiple_choice_single
        )

        comp = get_comparator( "multiple_choice", actual_value={ "answers": { "DB": "PG" } } )
        assert comp is compare_multiple_choice_single

    def test_multi_select_actual_returns_multi_comparator( self ):
        """Multi-select actual_value → compare_multiple_choice_multi."""
        from cosa.agents.prediction_engine.accuracy_comparators import (
            get_comparator, compare_multiple_choice_multi
        )

        comp = get_comparator( "multiple_choice", actual_value={ "answers": { "Features": [ "A", "B" ] } } )
        assert comp is compare_multiple_choice_multi

    def test_no_actual_value_backward_compat( self ):
        """No actual_value → compare_multiple_choice_single (backward compat)."""
        from cosa.agents.prediction_engine.accuracy_comparators import (
            get_comparator, compare_multiple_choice_single
        )

        comp = get_comparator( "multiple_choice" )
        assert comp is compare_multiple_choice_single

    def test_yes_no_unaffected_by_actual_value( self ):
        """yes_no type is unaffected by actual_value parameter."""
        from cosa.agents.prediction_engine.accuracy_comparators import (
            get_comparator, compare_yes_no
        )

        comp = get_comparator( "yes_no", actual_value={ "value": "yes" } )
        assert comp is compare_yes_no
