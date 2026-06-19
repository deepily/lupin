"""
Unit tests for cosa.agents.prediction_engine.xml_models.OpenEndedSynthesisResponse.

OpenEndedSynthesisResponse is a BaseXMLModel (Pydantic) carrying an LLM-synthesized
open-ended prediction. Tests cover the real public surface:

    - field defaults (reasoning="", confidence="0.0") and the required predicted_answer,
    - the `_coerce_none_to_empty_string` validator's THREE arcs: non-None passthrough,
      None on a non-predicted_answer field → "", and None on predicted_answer →
      ValidationError (the field-name guard's False arm),
    - get_confidence_float: in-range parse, upper/lower clamping, and the
      non-numeric → 0.0 except arc,
    - to_xml default root tag + from_xml round-trip,
    - get_example_for_template placeholders.

The module-level/classmethod `quick_smoke_test` is coverage-excluded (house style);
its assertions are harvested into the real tests below.

Authored by Rachel 🕊️ for the CoSA 100% coverage campaign (prediction_engine group).
"""

import pytest
from pydantic import ValidationError

from cosa.agents.prediction_engine.xml_models import OpenEndedSynthesisResponse


def test_defaults_and_required_field():
    """reasoning/confidence default; predicted_answer is required."""
    resp = OpenEndedSynthesisResponse( predicted_answer="go ahead" )
    assert resp.predicted_answer == "go ahead"
    assert resp.reasoning == ""
    assert resp.confidence == "0.0"


def test_missing_predicted_answer_raises():
    """predicted_answer has no default → omission is a ValidationError."""
    with pytest.raises( ValidationError ):
        OpenEndedSynthesisResponse( reasoning="x" )


def test_none_coerced_to_empty_on_optional_fields():
    """xmltodict yields None for empty tags; optional str fields coerce None→''."""
    resp = OpenEndedSynthesisResponse( predicted_answer="yes", reasoning=None, confidence=None )
    assert resp.reasoning == ""
    assert resp.confidence == ""


def test_none_predicted_answer_is_not_coerced_and_raises():
    """The validator's field-name guard EXCLUDES predicted_answer → None stays None → invalid."""
    with pytest.raises( ValidationError ):
        OpenEndedSynthesisResponse( predicted_answer=None )


def test_non_none_value_passes_through_validator():
    """The validator returns v unchanged when v is not None (the first-branch False arm)."""
    resp = OpenEndedSynthesisResponse( predicted_answer="p", reasoning="because", confidence="0.5" )
    assert resp.reasoning == "because"


def test_get_confidence_float_in_range():
    """A numeric-string confidence parses to the same float."""
    resp = OpenEndedSynthesisResponse( predicted_answer="p", confidence="0.85" )
    assert resp.get_confidence_float() == 0.85


def test_get_confidence_float_clamps_above_one():
    """Values above 1.0 clamp down to 1.0 (the min() arm)."""
    resp = OpenEndedSynthesisResponse( predicted_answer="p", confidence="1.7" )
    assert resp.get_confidence_float() == 1.0


def test_get_confidence_float_clamps_below_zero():
    """Negative values clamp up to 0.0 (the max() arm)."""
    resp = OpenEndedSynthesisResponse( predicted_answer="p", confidence="-0.3" )
    assert resp.get_confidence_float() == 0.0


def test_get_confidence_float_non_numeric_returns_zero():
    """A non-numeric confidence (e.g. placeholder text) hits the except → 0.0."""
    resp = OpenEndedSynthesisResponse( predicted_answer="p", confidence="not-a-number" )
    assert resp.get_confidence_float() == 0.0


def test_to_xml_uses_default_root_tag():
    """to_xml() serializes under <open_ended_synthesis_response> with the field values."""
    resp = OpenEndedSynthesisResponse( predicted_answer="yes, proceed", reasoning="r", confidence="0.9" )
    xml = resp.to_xml()
    assert "<open_ended_synthesis_response>" in xml
    assert "<predicted_answer>yes, proceed</predicted_answer>" in xml


def test_xml_round_trip():
    """from_xml( to_xml(x) ) reconstructs all fields."""
    resp = OpenEndedSynthesisResponse( predicted_answer="yes, proceed", reasoning="consistent", confidence="0.85" )
    parsed = OpenEndedSynthesisResponse.from_xml( resp.to_xml(), root_tag="open_ended_synthesis_response" )
    assert parsed.predicted_answer == "yes, proceed"
    assert parsed.reasoning == "consistent"
    assert parsed.confidence == "0.85"


def test_get_example_for_template_has_placeholders():
    """The template example carries descriptive placeholder text in every field."""
    example = OpenEndedSynthesisResponse.get_example_for_template()
    assert example.predicted_answer.startswith( "[your" )
    assert example.reasoning.startswith( "[brief" )
    assert example.confidence.startswith( "[confidence" )
    # Placeholder confidence is non-numeric → parses to 0.0.
    assert example.get_confidence_float() == 0.0
