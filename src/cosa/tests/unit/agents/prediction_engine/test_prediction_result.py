"""
Unit tests for cosa.agents.prediction_engine.prediction_result.PredictionResult.

PredictionResult is the dataclass return type of PredictionEngine.predict(). Tests
cover the real public surface + every branch:

    - is_cold_start (both AND operands),
    - to_hint_dict: cold_start→None, active dict shape + confidence rounding,
      and the predicted_qualifier inclusion arc,
    - to_log_dict field mapping,
    - _wrap_predicted_value: None passthrough, dict passthrough, scalar wrapping,
      and the qualifier-merge arc on each.

`quick_smoke_test` is coverage-excluded (house style); its assertions are harvested here.

Authored by Rachel 🕊️ for the CoSA 100% coverage campaign (prediction_engine group).
"""

from cosa.agents.prediction_engine.prediction_result import PredictionResult


def test_is_cold_start_true_when_no_value_and_zero_confidence():
    """Cold start = no predicted_value AND zero confidence."""
    r = PredictionResult( response_type="yes_no", category="permission", strategy="cold_start" )
    assert r.is_cold_start is True
    assert r.to_hint_dict() is None


def test_is_cold_start_false_when_value_present():
    """A present predicted_value defeats cold_start (first AND operand False)."""
    r = PredictionResult(
        response_type="yes_no", category="permission", strategy="cbr_majority_vote",
        predicted_value="yes", confidence=0.0,
    )
    assert r.is_cold_start is False


def test_is_cold_start_false_when_confidence_nonzero():
    """A non-zero confidence defeats cold_start (second AND operand False)."""
    r = PredictionResult(
        response_type="yes_no", category="permission", strategy="cbr_majority_vote",
        predicted_value=None, confidence=0.5,
    )
    assert r.is_cold_start is False


def test_to_hint_dict_active_shape_and_rounding():
    """Active prediction → dict with rounded confidence and core keys."""
    r = PredictionResult(
        response_type="yes_no", category="permission", strategy="cbr_majority_vote",
        predicted_value="yes", confidence=0.853791, similar_case_count=5,
    )
    hint = r.to_hint_dict()
    assert hint == {
        "predicted_value" : "yes",
        "confidence"      : 0.854,
        "strategy"        : "cbr_majority_vote",
        "category"        : "permission",
    }


def test_to_hint_dict_includes_qualifier_when_present():
    """predicted_qualifier is surfaced into the hint when set."""
    r = PredictionResult(
        response_type="yes_no", category="permission", strategy="cbr_majority_vote",
        predicted_value="yes", confidence=0.9, predicted_qualifier="only the old files",
    )
    hint = r.to_hint_dict()
    assert hint[ "predicted_qualifier" ] == "only the old files"


def test_to_log_dict_field_mapping():
    """to_log_dict maps the engine fields onto prediction_log column names."""
    r = PredictionResult(
        response_type="yes_no", category="permission", strategy="cbr_majority_vote",
        predicted_value="yes", confidence=0.8, similar_case_count=3,
    )
    log = r.to_log_dict()
    assert log == {
        "response_type"         : "yes_no",
        "category"              : "permission",
        "predicted_value"       : { "value": "yes" },
        "prediction_confidence" : 0.8,
        "prediction_strategy"   : "cbr_majority_vote",
        "similar_case_count"    : 3,
    }


def test_wrap_predicted_value_none_passthrough():
    """None predicted_value wraps to None."""
    r = PredictionResult( response_type="yes_no", category="c", strategy="cold_start" )
    assert r._wrap_predicted_value() is None


def test_wrap_predicted_value_dict_passthrough():
    """A dict predicted_value passes through unwrapped."""
    r = PredictionResult(
        response_type="multiple_choice", category="approach", strategy="option_embedding_scoring",
        predicted_value={ "answers": { "Database": "PostgreSQL" } }, confidence=0.72,
    )
    assert r._wrap_predicted_value() == { "answers": { "Database": "PostgreSQL" } }


def test_wrap_predicted_value_scalar_wrapped():
    """A scalar predicted_value is wrapped as {'value': ...}."""
    r = PredictionResult(
        response_type="yes_no", category="permission", strategy="cbr_majority_vote",
        predicted_value="no", confidence=0.8,
    )
    assert r._wrap_predicted_value() == { "value": "no" }


def test_wrap_predicted_value_scalar_with_qualifier():
    """Scalar + qualifier merges the qualifier into the wrapped dict."""
    r = PredictionResult(
        response_type="yes_no", category="permission", strategy="cbr_majority_vote",
        predicted_value="yes", confidence=0.9, predicted_qualifier="only the March ones",
    )
    assert r._wrap_predicted_value() == { "value": "yes", "qualifier": "only the March ones" }


def test_wrap_predicted_value_dict_with_qualifier():
    """Dict + qualifier merges the qualifier into the existing dict."""
    r = PredictionResult(
        response_type="multiple_choice", category="approach", strategy="option_embedding_scoring",
        predicted_value={ "answers": { "DB": "PG" } }, confidence=0.7, predicted_qualifier="prod only",
    )
    wrapped = r._wrap_predicted_value()
    assert wrapped[ "qualifier" ] == "prod only"
    assert wrapped[ "answers" ] == { "DB": "PG" }
