"""
Unit tests for prediction_engine/xml_models.py ( OpenEndedSynthesisResponse ).

Coverage target: 100% lines + branches + functions on production logic.
The module-level quick_smoke_test() + the classmethod quick_smoke_test() + the
__main__ guard are all excluded from the denominator by
pyproject.toml [tool.coverage.report].exclude_also ( "def quick_smoke_test"
matches both the module fn and the classmethod ), so they are NOT exercised.

Pure Pydantic model logic; no LLM / network / API boundaries to mock.
"""
import pytest
from pydantic import ValidationError

from cosa.agents.prediction_engine.xml_models import OpenEndedSynthesisResponse


# --------------------------------------------------------------------------- #
# construction + field defaults
# --------------------------------------------------------------------------- #
def test_construct_with_all_fields():
    r = OpenEndedSynthesisResponse( predicted_answer="yes, proceed", reasoning="pattern", confidence="0.85" )
    assert r.predicted_answer == "yes, proceed"
    assert r.reasoning        == "pattern"
    assert r.confidence       == "0.85"


def test_optional_fields_default():
    r = OpenEndedSynthesisResponse( predicted_answer="x" )
    assert r.reasoning  == ""
    assert r.confidence == "0.0"


# --------------------------------------------------------------------------- #
# _coerce_none_to_empty_string validator ( the `and` branch matrix )
# --------------------------------------------------------------------------- #
def test_coerce_none_optional_field_becomes_empty_string():
    # v is None AND field != predicted_answer → "" ( reasoning + confidence )
    r = OpenEndedSynthesisResponse( predicted_answer="test", reasoning=None, confidence=None )
    assert r.reasoning  == ""
    assert r.confidence == ""


def test_coerce_none_required_field_is_left_as_none_and_rejected():
    # v is None AND field == predicted_answer → validator returns v ( None ),
    # then Pydantic rejects None for the required str field → ValidationError.
    # This exercises the False edge of the `and` ( right operand evaluated, field check fails ).
    with pytest.raises( ValidationError ):
        OpenEndedSynthesisResponse( predicted_answer=None )


def test_coerce_non_none_value_passes_through():
    # v is not None → left operand False, short-circuit → return v unchanged
    r = OpenEndedSynthesisResponse( predicted_answer="kept", reasoning="kept2", confidence="0.5" )
    assert r.predicted_answer == "kept"
    assert r.reasoning        == "kept2"


# --------------------------------------------------------------------------- #
# get_confidence_float
# --------------------------------------------------------------------------- #
def test_get_confidence_float_parses_valid():
    r = OpenEndedSynthesisResponse( predicted_answer="x", confidence="0.85" )
    assert r.get_confidence_float() == 0.85


def test_get_confidence_float_clamps_high():
    r = OpenEndedSynthesisResponse( predicted_answer="x", confidence="1.5" )
    assert r.get_confidence_float() == 1.0


def test_get_confidence_float_clamps_low():
    r = OpenEndedSynthesisResponse( predicted_answer="x", confidence="-0.5" )
    assert r.get_confidence_float() == 0.0


def test_get_confidence_float_non_numeric_returns_zero():
    # float("[placeholder]") raises ValueError → caught → 0.0
    r = OpenEndedSynthesisResponse( predicted_answer="x", confidence="[not a number]" )
    assert r.get_confidence_float() == 0.0


def test_get_confidence_float_empty_string_returns_zero():
    r = OpenEndedSynthesisResponse( predicted_answer="x", reasoning=None, confidence=None )
    # confidence coerced to "" → float("") raises ValueError → 0.0
    assert r.get_confidence_float() == 0.0


# --------------------------------------------------------------------------- #
# to_xml
# --------------------------------------------------------------------------- #
def test_to_xml_default_root_tag():
    r = OpenEndedSynthesisResponse( predicted_answer="yes, proceed", reasoning="consistent", confidence="0.85" )
    xml_str = r.to_xml()
    assert "<open_ended_synthesis_response>" in xml_str
    assert "<predicted_answer>yes, proceed</predicted_answer>" in xml_str


def test_to_xml_round_trips_via_from_xml():
    r = OpenEndedSynthesisResponse( predicted_answer="yes, proceed", reasoning="consistent", confidence="0.85" )
    parsed = OpenEndedSynthesisResponse.from_xml( r.to_xml(), root_tag="open_ended_synthesis_response" )
    assert parsed.predicted_answer == "yes, proceed"
    assert parsed.reasoning        == "consistent"
    assert parsed.confidence       == "0.85"


def test_to_xml_custom_root_tag_and_not_pretty():
    r = OpenEndedSynthesisResponse( predicted_answer="x" )
    xml_str = r.to_xml( root_tag="custom_root", pretty=False )
    assert "<custom_root>" in xml_str


# --------------------------------------------------------------------------- #
# get_example_for_template
# --------------------------------------------------------------------------- #
def test_get_example_for_template_has_placeholders():
    ex = OpenEndedSynthesisResponse.get_example_for_template()
    assert ex.predicted_answer.startswith( "[your" )
    assert ex.reasoning.startswith( "[brief" )
    assert ex.confidence.startswith( "[confidence" )
    # placeholder confidence is non-numeric → parses to 0.0
    assert ex.get_confidence_float() == 0.0
