#!/usr/bin/env python3
"""
Unit tests for Slice 1.5: Qualified yes/no prediction.

Tests for:
    - _extract_qualifier() edge cases
    - _predict_yes_no() qualifier selection from winning-side cases
    - compare_yes_no() predicted_qualifier tracking
    - _wrap_predicted_value() qualifier inclusion

All tests use mocked dependencies — no live embedding store or database required.
"""

import pytest
from unittest.mock import MagicMock, patch


# ===========================================================================
# TestExtractQualifier — edge cases for _extract_qualifier()
# ===========================================================================

class TestExtractQualifier:
    """Tests for _extract_qualifier() helper in accuracy_comparators."""

    def test_simple_qualifier( self ):
        """Extract qualifier from standard format."""
        from cosa.agents.prediction_engine.accuracy_comparators import _extract_qualifier

        result = _extract_qualifier( "yes [comment: only the March ones]" )
        assert result == "only the March ones"

    def test_no_qualifier( self ):
        """Return None when no qualifier present."""
        from cosa.agents.prediction_engine.accuracy_comparators import _extract_qualifier

        result = _extract_qualifier( "yes" )
        assert result is None

    def test_empty_string( self ):
        """Return None for empty string."""
        from cosa.agents.prediction_engine.accuracy_comparators import _extract_qualifier

        result = _extract_qualifier( "" )
        assert result is None

    def test_none_input( self ):
        """Return None for None input."""
        from cosa.agents.prediction_engine.accuracy_comparators import _extract_qualifier

        result = _extract_qualifier( None )
        assert result is None

    def test_missing_closing_bracket( self ):
        """Handle missing closing bracket gracefully."""
        from cosa.agents.prediction_engine.accuracy_comparators import _extract_qualifier

        result = _extract_qualifier( "yes [comment: only the old files" )
        assert result == "only the old files"

    def test_case_insensitive_marker( self ):
        """Marker lookup is case-insensitive."""
        from cosa.agents.prediction_engine.accuracy_comparators import _extract_qualifier

        result = _extract_qualifier( "yes [Comment: uppercase marker]" )
        assert result == "uppercase marker"

    def test_no_value_with_qualifier( self ):
        """Qualifier on 'no' value."""
        from cosa.agents.prediction_engine.accuracy_comparators import _extract_qualifier

        result = _extract_qualifier( "no [comment: check with team first]" )
        assert result == "check with team first"

    def test_empty_qualifier( self ):
        """Empty comment returns empty string which is falsy."""
        from cosa.agents.prediction_engine.accuracy_comparators import _extract_qualifier

        result = _extract_qualifier( "yes [comment: ]" )
        assert result == ""


# ===========================================================================
# TestPredictYesNoQualifier — qualifier selection from winning-side cases
# ===========================================================================

class TestPredictYesNoQualifier:
    """Tests for _predict_yes_no() qualifier retrieval logic."""

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

    def test_qualifier_from_highest_similarity_winning_case( self ):
        """Qualifier comes from highest-similarity winning-side case."""
        engine = self._make_engine()

        # Similar cases: (similarity_pct, record_dict)
        engine._embedding_store.find_similar.return_value = [
            ( 95.0, { "decision_value": "yes [comment: only the old files]" } ),
            ( 90.0, { "decision_value": "yes [comment: just the backups]" } ),
            ( 85.0, { "decision_value": "no" } ),
        ]

        result = engine._predict_yes_no( "Delete the backups?", "permission", [ 0.1 ] * 768 )

        assert result.predicted_value == "yes"
        assert result.predicted_qualifier == "only the old files"
        assert result.metadata[ "qualifier_similarity" ] == 0.95

    def test_qualifier_only_from_winning_side( self ):
        """Qualifiers on losing-side cases are ignored."""
        engine = self._make_engine()

        engine._embedding_store.find_similar.return_value = [
            ( 95.0, { "decision_value": "no [comment: not today]" } ),
            ( 90.0, { "decision_value": "yes" } ),
            ( 85.0, { "decision_value": "yes" } ),
        ]

        result = engine._predict_yes_no( "Proceed?", "permission", [ 0.1 ] * 768 )

        assert result.predicted_value == "yes"
        assert result.predicted_qualifier is None

    def test_no_qualifiers_anywhere( self ):
        """No qualifiers in any case → None."""
        engine = self._make_engine()

        engine._embedding_store.find_similar.return_value = [
            ( 95.0, { "decision_value": "yes" } ),
            ( 90.0, { "decision_value": "yes" } ),
        ]

        result = engine._predict_yes_no( "Continue?", "workflow", [ 0.1 ] * 768 )

        assert result.predicted_value == "yes"
        assert result.predicted_qualifier is None
        assert result.metadata[ "qualifier_similarity" ] is None

    def test_hint_dict_includes_qualifier( self ):
        """to_hint_dict() includes predicted_qualifier when present."""
        engine = self._make_engine()

        engine._embedding_store.find_similar.return_value = [
            ( 92.0, { "decision_value": "yes [comment: after review]" } ),
        ]

        result = engine._predict_yes_no( "Deploy?", "permission", [ 0.1 ] * 768 )
        hint   = result.to_hint_dict()

        assert hint[ "predicted_qualifier" ] == "after review"

    def test_hint_dict_omits_qualifier_when_absent( self ):
        """to_hint_dict() omits predicted_qualifier when None."""
        engine = self._make_engine()

        engine._embedding_store.find_similar.return_value = [
            ( 92.0, { "decision_value": "no" } ),
        ]

        result = engine._predict_yes_no( "Skip?", "workflow", [ 0.1 ] * 768 )
        hint   = result.to_hint_dict()

        assert "predicted_qualifier" not in hint

    def test_empty_qualifier_is_ignored( self ):
        """Empty qualifier string (falsy) should not be selected."""
        engine = self._make_engine()

        engine._embedding_store.find_similar.return_value = [
            ( 95.0, { "decision_value": "yes [comment: ]" } ),
            ( 90.0, { "decision_value": "yes" } ),
        ]

        result = engine._predict_yes_no( "Proceed?", "permission", [ 0.1 ] * 768 )

        assert result.predicted_value == "yes"
        # Empty string from _extract_qualifier is falsy, so skipped
        assert result.predicted_qualifier is None


# ===========================================================================
# TestCompareYesNoQualifier — qualifier tracking in accuracy comparison
# ===========================================================================

class TestCompareYesNoQualifier:
    """Tests for compare_yes_no() predicted_qualifier tracking."""

    def test_both_qualifiers_present( self ):
        """Both predicted and actual qualifiers appear in detail."""
        from cosa.agents.prediction_engine.accuracy_comparators import compare_yes_no

        match, detail = compare_yes_no(
            { "value": "yes", "qualifier": "only the March ones" },
            { "value": "yes [comment: only the old ones]" }
        )

        assert match is True
        assert detail[ "predicted_qualifier" ] == "only the March ones"
        assert detail[ "actual_qualifier" ] == "only the old ones"

    def test_only_predicted_qualifier( self ):
        """Only predicted qualifier in detail when actual has none."""
        from cosa.agents.prediction_engine.accuracy_comparators import compare_yes_no

        match, detail = compare_yes_no(
            { "value": "no", "qualifier": "check with team" },
            { "value": "no" }
        )

        assert match is True
        assert detail[ "predicted_qualifier" ] == "check with team"
        assert "actual_qualifier" not in detail

    def test_only_actual_qualifier( self ):
        """Only actual qualifier in detail when predicted has none."""
        from cosa.agents.prediction_engine.accuracy_comparators import compare_yes_no

        match, detail = compare_yes_no(
            { "value": "yes" },
            { "value": "yes [comment: only the old ones]" }
        )

        assert match is True
        assert "predicted_qualifier" not in detail
        assert detail[ "actual_qualifier" ] == "only the old ones"

    def test_neither_qualifier( self ):
        """No qualifier keys in detail when neither has qualifiers."""
        from cosa.agents.prediction_engine.accuracy_comparators import compare_yes_no

        match, detail = compare_yes_no(
            { "value": "yes" },
            { "value": "yes" }
        )

        assert match is True
        assert "predicted_qualifier" not in detail
        assert "actual_qualifier" not in detail


# ===========================================================================
# TestWrapPredictedValueQualifier — qualifier inclusion in wrapped dict
# ===========================================================================

class TestWrapPredictedValueQualifier:
    """Tests for _wrap_predicted_value() qualifier handling."""

    def test_wrap_with_qualifier( self ):
        """Qualifier included in wrapped dict."""
        from cosa.agents.prediction_engine.prediction_result import PredictionResult

        result = PredictionResult(
            response_type       = "yes_no",
            category            = "permission",
            strategy            = "cbr_majority_vote",
            predicted_value     = "yes",
            confidence          = 0.9,
            predicted_qualifier = "only the old files"
        )

        wrapped = result._wrap_predicted_value()
        assert wrapped == { "value": "yes", "qualifier": "only the old files" }

    def test_wrap_without_qualifier( self ):
        """No qualifier key in wrapped dict when qualifier is None."""
        from cosa.agents.prediction_engine.prediction_result import PredictionResult

        result = PredictionResult(
            response_type   = "yes_no",
            category        = "permission",
            strategy        = "cbr_majority_vote",
            predicted_value = "no",
            confidence      = 0.8
        )

        wrapped = result._wrap_predicted_value()
        assert wrapped == { "value": "no" }
        assert "qualifier" not in wrapped
