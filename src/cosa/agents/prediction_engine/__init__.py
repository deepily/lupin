"""
Prediction Engine — Universal Decision Proxy for notification response prediction.

Provides prediction hints for all notification response types (yes_no, multiple_choice,
open_ended, open_ended_batch), tracks accuracy, and builds toward autonomous responses.

Usage:
    from cosa.agents.prediction_engine import get_prediction_engine

    engine = get_prediction_engine( config_mgr=config_mgr )
    result = engine.predict( notification_dict )
    engine.record_outcome( notification_id, result, actual_value, response_type )
"""

from cosa.agents.prediction_engine.prediction_engine import (
    PredictionEngine,
    get_prediction_engine,
)
from cosa.agents.prediction_engine.prediction_result import PredictionResult

__all__ = [
    "PredictionEngine",
    "get_prediction_engine",
    "PredictionResult",
]
