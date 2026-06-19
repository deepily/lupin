"""
Unit tests for prediction_engine/prediction_result.py ( PredictionResult dataclass ).

Coverage target: 100% lines + branches + functions on production logic.
The module-level quick_smoke_test() + __main__ guard are excluded from the
denominator by pyproject.toml [tool.coverage.report].exclude_also, so they
are intentionally NOT exercised here — only the dataclass behaviour is.

Assertions harvested from the in-module quick_smoke_test (D2 harvest pipeline).
Pure dataclass logic; no LLM / network / API boundaries to mock.
"""
import pytest

from cosa.agents.prediction_engine.prediction_result import PredictionResult


# --------------------------------------------------------------------------- #
# construction / defaults
# --------------------------------------------------------------------------- #
def test_defaults():
    r = PredictionResult( response_type="yes_no", category="permission", strategy="cold_start" )
    assert r.predicted_value     is None
    assert r.confidence          == 0.0
    assert r.similar_case_count  == 0
    assert r.predicted_qualifier is None
    assert r.metadata            == {}


def test_metadata_default_factory_is_independent():
    # field(default_factory=dict) → each instance gets its own dict
    a = PredictionResult( response_type="yes_no", category="c", strategy="s" )
    b = PredictionResult( response_type="yes_no", category="c", strategy="s" )
    a.metadata[ "k" ] = "v"
    assert b.metadata == {}


# --------------------------------------------------------------------------- #
# is_cold_start
# --------------------------------------------------------------------------- #
def test_is_cold_start_true_when_no_value_and_zero_confidence():
    r = PredictionResult( response_type="yes_no", category="permission", strategy="cold_start" )
    assert r.is_cold_start is True


def test_is_cold_start_false_when_value_present():
    r = PredictionResult( response_type="yes_no", category="c", strategy="s",
                          predicted_value="yes", confidence=0.0 )
    assert r.is_cold_start is False


def test_is_cold_start_false_when_confidence_nonzero():
    # value None but confidence != 0 → not cold start ( right operand of `and` is False )
    r = PredictionResult( response_type="yes_no", category="c", strategy="s",
                          predicted_value=None, confidence=0.5 )
    assert r.is_cold_start is False


# --------------------------------------------------------------------------- #
# to_hint_dict
# --------------------------------------------------------------------------- #
def test_to_hint_dict_returns_none_on_cold_start():
    r = PredictionResult( response_type="yes_no", category="permission", strategy="cold_start" )
    assert r.to_hint_dict() is None


def test_to_hint_dict_rounds_confidence_and_omits_qualifier():
    r = PredictionResult( response_type="yes_no", category="permission", strategy="cbr_majority_vote",
                          predicted_value="yes", confidence=0.123456, similar_case_count=5 )
    hint = r.to_hint_dict()
    assert hint == {
        "predicted_value" : "yes",
        "confidence"      : 0.123,   # rounded to 3 places
        "strategy"        : "cbr_majority_vote",
        "category"        : "permission",
    }
    assert "predicted_qualifier" not in hint


def test_to_hint_dict_includes_qualifier_when_present():
    r = PredictionResult( response_type="yes_no", category="permission", strategy="cbr_majority_vote",
                          predicted_value="yes", confidence=0.9, predicted_qualifier="only old files" )
    hint = r.to_hint_dict()
    assert hint[ "predicted_qualifier" ] == "only old files"


# --------------------------------------------------------------------------- #
# to_log_dict
# --------------------------------------------------------------------------- #
def test_to_log_dict_full_shape():
    r = PredictionResult( response_type="yes_no", category="permission", strategy="cbr_majority_vote",
                          predicted_value="yes", confidence=0.85, similar_case_count=5 )
    log = r.to_log_dict()
    assert log == {
        "response_type"         : "yes_no",
        "category"              : "permission",
        "predicted_value"       : { "value": "yes" },
        "prediction_confidence" : 0.85,
        "prediction_strategy"   : "cbr_majority_vote",
        "similar_case_count"    : 5,
    }


def test_to_log_dict_cold_start_wraps_none():
    r = PredictionResult( response_type="yes_no", category="permission", strategy="cold_start" )
    log = r.to_log_dict()
    assert log[ "predicted_value" ]       is None
    assert log[ "prediction_confidence" ] == 0.0


# --------------------------------------------------------------------------- #
# _wrap_predicted_value
# --------------------------------------------------------------------------- #
def test_wrap_none_returns_none():
    r = PredictionResult( response_type="yes_no", category="c", strategy="cold_start" )
    assert r._wrap_predicted_value() is None


def test_wrap_scalar_value():
    r = PredictionResult( response_type="yes_no", category="c", strategy="s", predicted_value="no" )
    assert r._wrap_predicted_value() == { "value": "no" }


def test_wrap_dict_value_passes_through():
    payload = { "answers": { "Database": "PostgreSQL" } }
    r = PredictionResult( response_type="multiple_choice", category="approach",
                          strategy="option_embedding_scoring", predicted_value=payload )
    assert r._wrap_predicted_value() == payload


def test_wrap_scalar_with_qualifier():
    r = PredictionResult( response_type="yes_no", category="c", strategy="s",
                          predicted_value="yes", predicted_qualifier="only the old files" )
    assert r._wrap_predicted_value() == { "value": "yes", "qualifier": "only the old files" }


def test_wrap_dict_with_qualifier_adds_qualifier_key():
    r = PredictionResult( response_type="multiple_choice", category="c", strategy="s",
                          predicted_value={ "a": 1 }, predicted_qualifier="q" )
    assert r._wrap_predicted_value() == { "a": 1, "qualifier": "q" }


def test_wrap_scalar_without_qualifier_has_no_qualifier_key():
    r = PredictionResult( response_type="yes_no", category="c", strategy="s", predicted_value="no" )
    wrapped = r._wrap_predicted_value()
    assert "qualifier" not in wrapped
