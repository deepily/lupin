#!/usr/bin/env python3
"""
Unit tests for cosa.agents.notification_proxy.xml_models.

Three BaseXMLModel subclasses — ScriptMatcherResponse,
BatchScriptMatcherResponse, VerificationResponse. Pure Pydantic/XML logic,
no LLM. Tests exercise field coercion, confidence parsing, match detection,
batch answer extraction, the xmltodict normalization arms, and XML round-trips.
"""

import pytest
from pydantic import ValidationError

from cosa.agents.notification_proxy.xml_models import (
    ScriptMatcherResponse,
    BatchScriptMatcherResponse,
    VerificationResponse,
)


# ===========================================================================
# ScriptMatcherResponse
# ===========================================================================
class TestScriptMatcherResponse:

    def test_construct_and_fields( self ):
        r = ScriptMatcherResponse( matched_entry="2", answer="quantum", confidence="0.95", reasoning="why" )
        assert r.matched_entry == "2"
        assert r.answer        == "quantum"

    def test_none_coercion_on_optional_fields( self ):
        """None on optional fields (confidence/reasoning) coerces to '' (if-True);
        non-None required fields pass through (if-False)."""
        r = ScriptMatcherResponse( matched_entry="0", answer="a", confidence=None, reasoning=None )
        assert r.confidence == ""
        assert r.reasoning  == ""

    def test_none_on_required_field_raises( self ):
        """None on a required field (matched_entry) is passed through unchanged
        by the coercion guard → Pydantic str validation rejects it."""
        with pytest.raises( ValidationError ):
            ScriptMatcherResponse( matched_entry=None, answer="a" )

    def test_get_confidence_float_valid( self ):
        assert ScriptMatcherResponse( matched_entry="0", answer="a", confidence="0.5" ).get_confidence_float() == 0.5

    def test_get_confidence_float_clamps_high_and_low( self ):
        assert ScriptMatcherResponse( matched_entry="0", answer="a", confidence="9.9" ).get_confidence_float() == 1.0
        assert ScriptMatcherResponse( matched_entry="0", answer="a", confidence="-3" ).get_confidence_float() == 0.0

    def test_get_confidence_float_invalid_returns_zero( self ):
        assert ScriptMatcherResponse( matched_entry="0", answer="a", confidence="nope" ).get_confidence_float() == 0.0

    def test_is_match_true( self ):
        assert ScriptMatcherResponse( matched_entry="1", answer="x" ).is_match()

    def test_is_match_false_when_none_entry( self ):
        assert not ScriptMatcherResponse( matched_entry="none", answer="x" ).is_match()

    def test_is_match_false_when_empty_answer( self ):
        assert not ScriptMatcherResponse( matched_entry="1", answer="   " ).is_match()

    def test_get_answers_dict_empty_answer( self ):
        assert ScriptMatcherResponse( matched_entry="0", answer="" ).get_answers_dict() == {}

    def test_get_answers_dict_valid_json_object( self ):
        r = ScriptMatcherResponse( matched_entry="0", answer='{"budget":"no limit"}' )
        assert r.get_answers_dict() == { "budget": "no limit" }

    def test_get_answers_dict_non_dict_json_returns_empty( self ):
        """Valid JSON but not an object (a list) → {}."""
        r = ScriptMatcherResponse( matched_entry="0", answer="[1, 2, 3]" )
        assert r.get_answers_dict() == {}

    def test_get_answers_dict_invalid_json_returns_empty( self ):
        r = ScriptMatcherResponse( matched_entry="0", answer="{not json" )
        assert r.get_answers_dict() == {}

    def test_get_example_for_template( self ):
        ex = ScriptMatcherResponse.get_example_for_template()
        assert "index" in ex.matched_entry.lower()

    def test_xml_round_trip( self ):
        r = ScriptMatcherResponse( matched_entry="2", answer="quantum", confidence="0.9", reasoning="r" )
        xml = r.to_xml()
        assert "<matched_entry>2</matched_entry>" in xml
        parsed = ScriptMatcherResponse.from_xml( xml )
        assert parsed.matched_entry == "2"
        assert parsed.answer        == "quantum"


# ===========================================================================
# BatchScriptMatcherResponse
# ===========================================================================
class TestBatchScriptMatcherResponse:

    def test_construct_with_list_entries( self ):
        """Direct construction: entries already a list → normalize passthrough."""
        r = BatchScriptMatcherResponse(
            entries    = [ { "header": "Budget", "matched_index": "1", "answer": "no limit" } ],
            confidence = "0.9",
        )
        assert len( r.entries ) == 1

    def test_none_coercion_confidence_reasoning( self ):
        r = BatchScriptMatcherResponse( entries=[], confidence=None, reasoning=None )
        assert r.confidence == ""
        assert r.reasoning  == ""

    def test_normalize_non_dict_input_raises( self ):
        """A non-dict top-level input is returned unchanged by the normalizer
        (the `not isinstance(data, dict)` arm) → Pydantic then rejects it."""
        with pytest.raises( ValidationError ):
            BatchScriptMatcherResponse.model_validate( [ "not", "a", "dict" ] )

    def test_normalize_missing_entries_key_raises( self ):
        """dict without 'entries' → entries_raw is None → returned as-is →
        required-field validation fails."""
        with pytest.raises( ValidationError ):
            BatchScriptMatcherResponse.model_validate( { "confidence": "0.5" } )

    def test_normalize_xmltodict_single_entry_dict( self ):
        """xmltodict single <entry> → dict → wrapped into a one-item list."""
        r = BatchScriptMatcherResponse.model_validate(
            { "entries": { "entry": { "header": "Topic", "answer": "quantum" } } }
        )
        assert len( r.entries ) == 1
        assert r.entries[ 0 ][ "header" ] == "Topic"

    def test_normalize_xmltodict_multiple_entries_list( self ):
        r = BatchScriptMatcherResponse.model_validate(
            { "entries": { "entry": [ { "header": "A", "answer": "1" }, { "header": "B", "answer": "2" } ] } }
        )
        assert len( r.entries ) == 2

    def test_normalize_xmltodict_entry_none( self ):
        """<entries> present but no <entry> child → entries become []."""
        r = BatchScriptMatcherResponse.model_validate( { "entries": { "other": "x" } } )
        assert r.entries == []

    def test_normalize_xmltodict_entry_unexpected_type( self ):
        """entry of an unexpected scalar type → entries become []."""
        r = BatchScriptMatcherResponse.model_validate( { "entries": { "entry": "scalar" } } )
        assert r.entries == []

    def test_get_answers_dict_maps_headers( self ):
        r = BatchScriptMatcherResponse( entries=[
            { "header": "Budget",   "answer": "no limit" },
            { "header": "Audience", "answer": "academic" },
        ] )
        assert r.get_answers_dict() == { "Budget": "no limit", "Audience": "academic" }

    def test_get_answers_dict_skips_headerless_and_coerces_none_answer( self ):
        r = BatchScriptMatcherResponse( entries=[
            { "header": "",    "answer": "ignored" },
            { "header": "Has", "answer": None },
        ] )
        out = r.get_answers_dict()
        assert "" not in out
        assert out[ "Has" ] == ""

    def test_get_confidence_float( self ):
        assert BatchScriptMatcherResponse( entries=[], confidence="0.7" ).get_confidence_float() == 0.7
        assert BatchScriptMatcherResponse( entries=[], confidence="bad" ).get_confidence_float() == 0.0

    def test_is_match_true_and_false( self ):
        assert BatchScriptMatcherResponse( entries=[ { "header": "A", "answer": "x" } ] ).is_match()
        assert not BatchScriptMatcherResponse( entries=[ { "header": "A", "answer": "  " } ] ).is_match()
        assert not BatchScriptMatcherResponse( entries=[] ).is_match()

    def test_to_xml_nested_structure_and_round_trip( self ):
        r = BatchScriptMatcherResponse(
            entries    = [ { "header": "Budget", "matched_index": "1", "answer": "no limit" } ],
            confidence = "0.9",
            reasoning  = "matched",
        )
        xml = r.to_xml()
        assert "<entries>" in xml
        assert "<entry>" in xml
        assert "<header>Budget</header>" in xml
        parsed = BatchScriptMatcherResponse.from_xml( xml )
        assert parsed.get_answers_dict()[ "Budget" ] == "no limit"

    def test_get_example_for_template( self ):
        ex = BatchScriptMatcherResponse.get_example_for_template()
        assert len( ex.entries ) == 2


# ===========================================================================
# VerificationResponse
# ===========================================================================
class TestVerificationResponse:

    def test_construct_and_fields( self ):
        r = VerificationResponse( match="true", confidence="0.95", reasoning="same" )
        assert r.match == "true"

    def test_none_coercion_optional( self ):
        r = VerificationResponse( match="true", confidence=None, reasoning=None )
        assert r.confidence == ""
        assert r.reasoning  == ""

    def test_none_on_required_match_raises( self ):
        with pytest.raises( ValidationError ):
            VerificationResponse( match=None )

    def test_is_match_true_false( self ):
        assert VerificationResponse( match="TRUE" ).is_match()
        assert not VerificationResponse( match="false" ).is_match()

    def test_get_confidence_float_valid_and_invalid( self ):
        assert VerificationResponse( match="true", confidence="0.95" ).get_confidence_float() == 0.95
        assert VerificationResponse( match="true", confidence="invalid" ).get_confidence_float() == 0.0

    def test_get_confidence_float_clamps( self ):
        assert VerificationResponse( match="true", confidence="2" ).get_confidence_float() == 1.0
        assert VerificationResponse( match="true", confidence="-1" ).get_confidence_float() == 0.0

    def test_get_example_for_template( self ):
        ex = VerificationResponse.get_example_for_template()
        assert "true" in ex.match.lower()

    def test_xml_round_trip( self ):
        r = VerificationResponse( match="true", confidence="0.9", reasoning="r" )
        xml = r.to_xml()
        assert "<match>true</match>" in xml
        parsed = VerificationResponse.from_xml( xml )
        assert parsed.match == "true"
