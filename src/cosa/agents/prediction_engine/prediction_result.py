"""
PredictionResult dataclass — the return type of PredictionEngine.predict().

Encapsulates prediction outcome, confidence, strategy used, and metadata
for both UI rendering (hint dict) and database logging.
"""

from dataclasses import dataclass, field
from typing import Optional, Dict, Any


@dataclass
class PredictionResult:
    """
    Encapsulates a prediction for a notification response.

    Requires:
        - response_type is a valid response type string
        - category is a non-empty string
        - strategy is a valid strategy constant from config.py

    Ensures:
        - predicted_value is None for cold_start predictions
        - confidence is 0.0 for cold_start predictions
        - to_hint_dict() returns a JSON-serializable dict for WebSocket push
        - to_log_dict() returns a dict suitable for prediction_log insertion
    """

    response_type      : str
    category           : str
    strategy           : str
    predicted_value    : Optional[Any]            = None
    confidence         : float                    = 0.0
    similar_case_count : int                      = 0
    predicted_qualifier: Optional[str]            = None
    metadata           : Optional[Dict[str, Any]] = field( default_factory=dict )

    @property
    def is_cold_start( self ) -> bool:
        """True when no prediction could be made (insufficient data)."""
        return self.predicted_value is None and self.confidence == 0.0

    def to_hint_dict( self ) -> Optional[Dict[str, Any]]:
        """
        Convert to a lightweight dict for WebSocket push to the UI.

        Requires:
            - self is a valid PredictionResult

        Ensures:
            - Returns None if cold_start (no hint to show)
            - Returns dict with keys: predicted_value, confidence, strategy, category
            - All values are JSON-serializable
        """
        if self.is_cold_start:
            return None

        hint = {
            "predicted_value" : self.predicted_value,
            "confidence"      : round( self.confidence, 3 ),
            "strategy"        : self.strategy,
            "category"        : self.category,
        }

        if self.predicted_qualifier:
            hint[ "predicted_qualifier" ] = self.predicted_qualifier

        return hint

    def to_log_dict( self ) -> Dict[str, Any]:
        """
        Convert to a dict for prediction_log database insertion.

        Requires:
            - self is a valid PredictionResult

        Ensures:
            - Returns dict with all fields needed for PredictionLog row
            - predicted_value wrapped in JSONB-compatible format
        """
        return {
            "response_type"         : self.response_type,
            "category"              : self.category,
            "predicted_value"       : self._wrap_predicted_value(),
            "prediction_confidence" : self.confidence,
            "prediction_strategy"   : self.strategy,
            "similar_case_count"    : self.similar_case_count,
        }

    def _wrap_predicted_value( self ) -> Optional[Dict[str, Any]]:
        """
        Wrap predicted_value in a JSONB-compatible dict format.

        Ensures:
            - None remains None
            - Strings wrapped as {"value": str}
            - Dicts passed through as-is
            - predicted_qualifier included when present
        """
        if self.predicted_value is None:
            return None

        if isinstance( self.predicted_value, dict ):
            result = self.predicted_value
        else:
            result = { "value": self.predicted_value }

        if self.predicted_qualifier:
            result[ "qualifier" ] = self.predicted_qualifier

        return result


def quick_smoke_test():
    """Quick smoke test for PredictionResult."""
    import cosa.utils.util as cu

    cu.print_banner( "PredictionResult Smoke Test", prepend_nl=True )

    try:
        # Test 1: Cold start
        print( "Testing cold start result..." )
        cold = PredictionResult(
            response_type="yes_no",
            category="permission",
            strategy="cold_start"
        )
        assert cold.is_cold_start
        assert cold.to_hint_dict() is None
        log = cold.to_log_dict()
        assert log[ "prediction_confidence" ] == 0.0
        print( "✓ Cold start result works correctly" )

        # Test 2: Active prediction
        print( "Testing active prediction..." )
        active = PredictionResult(
            response_type      = "yes_no",
            category           = "permission",
            strategy           = "cbr_majority_vote",
            predicted_value    = "yes",
            confidence         = 0.85,
            similar_case_count = 5
        )
        assert not active.is_cold_start
        hint = active.to_hint_dict()
        assert hint[ "predicted_value" ] == "yes"
        assert hint[ "confidence" ] == 0.85
        log = active.to_log_dict()
        assert log[ "predicted_value" ] == { "value": "yes" }
        print( "✓ Active prediction works correctly" )

        # Test 3: Dict predicted value
        print( "Testing dict predicted value..." )
        mc = PredictionResult(
            response_type   = "multiple_choice",
            category        = "approach",
            strategy        = "option_embedding_scoring",
            predicted_value = { "answers": { "Database": "PostgreSQL" } },
            confidence      = 0.72
        )
        assert mc.to_log_dict()[ "predicted_value" ] == { "answers": { "Database": "PostgreSQL" } }
        print( "✓ Dict predicted value passes through correctly" )

        # Test 4: Wrap with qualifier
        print( "Testing wrap with qualifier..." )
        qualified = PredictionResult(
            response_type       = "yes_no",
            category            = "permission",
            strategy            = "cbr_majority_vote",
            predicted_value     = "yes",
            confidence          = 0.9,
            predicted_qualifier = "only the old files"
        )
        wrapped = qualified._wrap_predicted_value()
        assert wrapped == { "value": "yes", "qualifier": "only the old files" }
        print( "✓ Wrap with qualifier works correctly" )

        # Test 5: Wrap without qualifier (backward compatible)
        print( "Testing wrap without qualifier..." )
        no_qual = PredictionResult(
            response_type   = "yes_no",
            category        = "permission",
            strategy        = "cbr_majority_vote",
            predicted_value = "no",
            confidence      = 0.8
        )
        wrapped = no_qual._wrap_predicted_value()
        assert wrapped == { "value": "no" }
        assert "qualifier" not in wrapped
        print( "✓ Wrap without qualifier is backward compatible" )

        print( "\n✓ All PredictionResult smoke tests passed!" )

    except Exception as e:
        print( f"\n✗ Smoke test failed: {e}" )
        cu.print_stack_trace( e, caller="prediction_result.quick_smoke_test()" )


if __name__ == "__main__":
    quick_smoke_test()
