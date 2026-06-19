#!/usr/bin/env python3
"""
XML response models for Notification Proxy Agent.

Defines Pydantic BaseXMLModel subclasses for:
    - ScriptMatcherResponse: LLM fuzzy-matching of incoming questions to Q&A script entries
    - VerificationResponse: LLM scoring of expected vs actual answers for semantic equivalence

References:
    - src/cosa/agents/runtime_argument_expeditor/xml_models.py (ExpeditorResponse pattern)
    - src/conf/notification-proxy-scripts/ (Q&A script format)
"""

import json
import xmltodict
from pydantic import Field, field_validator, model_validator

from cosa.agents.io_models.utils.util_xml_pydantic import BaseXMLModel


class ScriptMatcherResponse( BaseXMLModel ):
    """
    XML response from Phi-4 for Q&A script matching.

    Used by ALL response types (OPEN_ENDED, OPEN_ENDED_BATCH, MULTIPLE_CHOICE, YES_NO).
    The LLM fuzzy-matches an incoming notification question to a Q&A script entry
    and returns the scripted answer inside this XML structure.

    Requires:
        - LLM returns valid XML with <response> root tag

    Ensures:
        - matched_entry contains index ("0", "1", ...) or "none"
        - answer contains the scripted answer text
        - For batch: answer contains JSON dict of header->answer mappings
        - confidence is a string "0.0" to "1.0"
    """

    matched_entry : str = Field( ..., description="Index of matched script entry, or 'none'" )
    answer        : str = Field( ..., description="The answer to return (or JSON for batch)" )
    confidence    : str = Field( default="0.0", description="Match confidence 0.0-1.0" )
    reasoning     : str = Field( default="", description="Why this entry was chosen" )

    @field_validator( "*", mode="before" )
    @classmethod
    def _coerce_none_to_empty_string( cls, v, info ):
        """
        Coerce None values to empty strings for optional string fields.

        Requires:
            - v is the field value (may be None from xmltodict)
            - info.field_name identifies the field

        Ensures:
            - Returns "" for None values on optional fields (confidence, reasoning)
            - Passes through non-None values and required fields unchanged
        """
        if v is None and info.field_name not in ( "matched_entry", "answer" ):
            return ""
        return v

    @classmethod
    def get_example_for_template( cls ):
        """
        Get example instance for prompt templates.

        Requires:
            - None

        Ensures:
            - Returns ScriptMatcherResponse with placeholder values for template injection
        """
        return cls(
            matched_entry = "[index of best-matching script entry, or 'none']",
            answer        = "[the answer text from the matched script entry]",
            confidence    = "[confidence score between 0.0 and 1.0]",
            reasoning     = "[brief explanation of why this entry matches]"
        )

    def get_confidence_float( self ):
        """
        Parse confidence string to float, clamped to [0.0, 1.0].

        Requires:
            - self.confidence is a string

        Ensures:
            - Returns float in [0.0, 1.0]
            - Returns 0.0 on parse failure
        """
        try:
            return max( 0.0, min( 1.0, float( self.confidence ) ) )
        except ( ValueError, TypeError ):
            return 0.0

    def is_match( self ):
        """
        Check if the LLM found a matching script entry.

        Requires:
            - self.matched_entry and self.answer are strings

        Ensures:
            - Returns True if matched_entry is not "none" and answer is non-empty
            - Returns False otherwise
        """
        return self.matched_entry.strip().lower() != "none" and self.answer.strip() != ""

    def get_answers_dict( self ):
        """
        Parse batch answer JSON string to dict.

        Used for OPEN_ENDED_BATCH responses where the answer field
        contains a JSON object mapping headers to answer values.

        Requires:
            - self.answer is a string (possibly JSON)

        Ensures:
            - Returns dict if answer is valid JSON object
            - Returns empty dict on parse failure or non-dict JSON
        """
        if not self.answer or not self.answer.strip():
            return {}
        try:
            parsed = json.loads( self.answer )
            return parsed if isinstance( parsed, dict ) else {}
        except ( json.JSONDecodeError, TypeError ):
            return {}

    @classmethod
    def quick_smoke_test( cls, debug=False ):
        """
        Quick smoke test for ScriptMatcherResponse.

        Args:
            debug: Enable debug output

        Returns:
            True if all tests pass
        """
        if debug: print( f"Testing {cls.__name__}..." )

        try:
            # Test base functionality
            if not super().quick_smoke_test( debug=False ):
                return False

            # Test creation with all fields
            response = cls(
                matched_entry = "2",
                answer        = "quantum computing breakthroughs 2026",
                confidence    = "0.95",
                reasoning     = "Keyword 'topic' matches entry 2"
            )
            assert response.matched_entry == "2"
            assert response.answer == "quantum computing breakthroughs 2026"

            # Test is_match
            assert response.is_match()
            no_match = cls(
                matched_entry = "none",
                answer        = "",
                confidence    = "0.0",
                reasoning     = "No match found"
            )
            assert not no_match.is_match()

            # Test get_confidence_float
            assert response.get_confidence_float() == 0.95
            assert no_match.get_confidence_float() == 0.0

            # Test get_answers_dict for batch
            batch = cls(
                matched_entry = "0",
                answer        = '{"budget": "no limit", "audience": "academic"}',
                confidence    = "0.9",
                reasoning     = "Batch match"
            )
            answers = batch.get_answers_dict()
            assert answers[ "budget" ] == "no limit"
            assert answers[ "audience" ] == "academic"

            # Test get_answers_dict with non-JSON
            non_json = cls(
                matched_entry = "0",
                answer        = "plain text answer",
                confidence    = "0.8",
                reasoning     = "Single answer"
            )
            assert non_json.get_answers_dict() == {}

            # Test XML round-trip
            xml_str = response.to_xml()
            assert "<matched_entry>2</matched_entry>" in xml_str
            parsed = cls.from_xml( xml_str )
            assert parsed.matched_entry == response.matched_entry
            assert parsed.answer == response.answer

            # Test template example
            example = cls.get_example_for_template()
            assert "index" in example.matched_entry.lower()

            # Test None coercion
            none_response = cls(
                matched_entry = "0",
                answer        = "test",
                confidence    = None,
                reasoning     = None
            )
            assert none_response.confidence == ""
            assert none_response.reasoning == ""

            if debug: print( f"✓ {cls.__name__} smoke test PASSED" )
            return True

        except Exception as e:
            if debug: print( f"✗ {cls.__name__} smoke test FAILED: {e}" )
            return False


class BatchScriptMatcherResponse( BaseXMLModel ):
    """
    XML response from Phi-4 for batch Q&A script matching (OPEN_ENDED_BATCH).

    Uses nested <entry> elements instead of a JSON blob inside a single <answer> tag,
    which Phi-4 can generate reliably. Each entry maps a batch question header to its
    matched script answer.

    XML structure:
        <response>
          <entries>
            <entry>
              <header>Budget</header>
              <matched_index>1</matched_index>
              <answer>no limit</answer>
            </entry>
            <entry>
              <header>Audience</header>
              <matched_index>2</matched_index>
              <answer>academic</answer>
            </entry>
          </entries>
          <confidence>0.9</confidence>
          <reasoning>Matched all batch questions to script entries</reasoning>
        </response>

    Requires:
        - LLM returns valid XML with <response> root tag
        - Each <entry> has <header>, <matched_index>, and <answer> child elements

    Ensures:
        - entries is a list of dicts with header, matched_index, answer keys
        - get_answers_dict() returns {header: answer} mapping
        - to_xml() generates nested <entries><entry>...</entry></entries> structure

    References:
        - CodeResponse pattern in src/cosa/agents/io_models/xml_models.py (List[str] with custom to_xml)
    """

    entries    : list = Field( ..., description="List of entry dicts with header, matched_index, answer" )
    confidence : str  = Field( default="0.0", description="Overall match confidence 0.0-1.0" )
    reasoning  : str  = Field( default="", description="Overall reasoning for matches" )

    @model_validator( mode='before' )
    @classmethod
    def normalize_xmltodict_entries( cls, data ):
        """
        Normalize xmltodict output for nested <entries><entry>...</entry></entries>.

        xmltodict produces:
            - Single entry:  {'entries': {'entry': {'header': '...', ...}}}
            - Multiple entries: {'entries': {'entry': [{'header': '...'}, ...]}}

        Requires:
            - data is a dict (from xmltodict or direct construction)

        Ensures:
            - data['entries'] is always a list of dicts
            - Passes through non-dict data unchanged
        """
        if not isinstance( data, dict ):
            return data

        entries_raw = data.get( "entries" )
        if entries_raw is None:
            # Allow direct construction with entries as a list
            return data

        if isinstance( entries_raw, dict ):
            # xmltodict wrapping — extract the <entry> elements
            entry_val = entries_raw.get( "entry" )
            if entry_val is None:
                data[ "entries" ] = []
            elif isinstance( entry_val, list ):
                data[ "entries" ] = entry_val
            elif isinstance( entry_val, dict ):
                # Single entry — wrap in list
                data[ "entries" ] = [ entry_val ]
            else:
                data[ "entries" ] = []

        # Already a list (direct construction) — pass through
        return data

    @field_validator( "confidence", "reasoning", mode="before" )
    @classmethod
    def _coerce_none_to_empty_string( cls, v ):
        """
        Coerce None values to empty strings for optional fields.

        Requires:
            - v is the field value (may be None from xmltodict)

        Ensures:
            - Returns "" for None values
            - Passes through non-None values unchanged
        """
        if v is None:
            return ""
        return v

    def get_answers_dict( self ):
        """
        Convert entries list to {header: answer} mapping.

        Requires:
            - self.entries is a list of dicts with 'header' and 'answer' keys

        Ensures:
            - Returns dict mapping header strings to answer strings
            - Skips entries missing header or answer
        """
        result = {}
        for entry in self.entries:
            header = entry.get( "header", "" )
            answer = entry.get( "answer", "" )
            if header:
                result[ header ] = answer if answer is not None else ""
        return result

    def get_confidence_float( self ):
        """
        Parse confidence string to float, clamped to [0.0, 1.0].

        Requires:
            - self.confidence is a string

        Ensures:
            - Returns float in [0.0, 1.0]
            - Returns 0.0 on parse failure
        """
        try:
            return max( 0.0, min( 1.0, float( self.confidence ) ) )
        except ( ValueError, TypeError ):
            return 0.0

    def is_match( self ):
        """
        Check if any entries were matched.

        Requires:
            - self.entries is a list

        Ensures:
            - Returns True if at least one entry has a non-empty answer
            - Returns False otherwise
        """
        return any(
            entry.get( "answer", "" ).strip() != ""
            for entry in self.entries
        )

    def to_xml( self, root_tag='response', pretty=True ):
        """
        Generate XML with proper nested <entries><entry>...</entry></entries> structure.

        Overrides BaseXMLModel.to_xml() to handle nested entry elements
        that xmltodict.unparse() would not produce correctly from a flat list.

        Requires:
            - self.entries is a list of dicts

        Ensures:
            - Returns XML string with nested <entry> elements inside <entries>

        Args:
            root_tag: Root XML element name (default: 'response')
            pretty: Whether to format XML with indentation (default: True)

        Returns:
            Formatted XML string
        """
        data = {
            "entries"    : { "entry" : self.entries },
            "confidence" : self.confidence,
            "reasoning"  : self.reasoning,
        }
        return xmltodict.unparse( { root_tag : data }, pretty=pretty )

    @classmethod
    def get_example_for_template( cls ):
        """
        Get example instance for prompt templates.

        Requires:
            - None

        Ensures:
            - Returns BatchScriptMatcherResponse with placeholder entries for template injection
        """
        return cls(
            entries = [
                {
                    "header"        : "[header from batch question 1]",
                    "matched_index" : "[index of best-matching script entry, or 'none']",
                    "answer"        : "[the answer text from the matched script entry]",
                },
                {
                    "header"        : "[header from batch question 2]",
                    "matched_index" : "[index of best-matching script entry, or 'none']",
                    "answer"        : "[the answer text from the matched script entry]",
                },
            ],
            confidence = "[confidence score between 0.0 and 1.0]",
            reasoning  = "[brief explanation of how questions were matched to entries]",
        )

    @classmethod
    def quick_smoke_test( cls, debug=False ):
        """
        Quick smoke test for BatchScriptMatcherResponse.

        Args:
            debug: Enable debug output

        Returns:
            True if all tests pass
        """
        if debug: print( f"Testing {cls.__name__}..." )

        try:
            # Test base functionality
            if not super().quick_smoke_test( debug=False ):
                return False

            # Test creation with entries
            response = cls(
                entries = [
                    { "header" : "Budget",   "matched_index" : "1", "answer" : "no limit" },
                    { "header" : "Audience", "matched_index" : "2", "answer" : "academic" },
                ],
                confidence = "0.9",
                reasoning  = "Matched all batch questions",
            )
            assert len( response.entries ) == 2
            assert response.entries[ 0 ][ "header" ] == "Budget"

            # Test get_answers_dict
            answers = response.get_answers_dict()
            assert answers[ "Budget" ] == "no limit"
            assert answers[ "Audience" ] == "academic"
            assert len( answers ) == 2

            # Test is_match
            assert response.is_match()

            # Test empty entries
            empty = cls( entries=[], confidence="0.0", reasoning="No matches" )
            assert not empty.is_match()
            assert empty.get_answers_dict() == {}

            # Test get_confidence_float
            assert response.get_confidence_float() == 0.9

            # Test XML round-trip
            xml_str = response.to_xml()
            assert "<entries>" in xml_str
            assert "<entry>" in xml_str
            assert "<header>Budget</header>" in xml_str
            parsed = cls.from_xml( xml_str )
            assert len( parsed.entries ) == 2
            assert parsed.get_answers_dict()[ "Budget" ] == "no limit"

            # Test single-entry xmltodict normalization (single entry = dict, not list)
            single_xml = (
                "<response>"
                "<entries><entry>"
                "<header>Topic</header>"
                "<matched_index>0</matched_index>"
                "<answer>quantum</answer>"
                "</entry></entries>"
                "<confidence>0.8</confidence>"
                "<reasoning>Single match</reasoning>"
                "</response>"
            )
            single = cls.from_xml( single_xml )
            assert len( single.entries ) == 1
            assert single.get_answers_dict()[ "Topic" ] == "quantum"

            # Test template example
            example = cls.get_example_for_template()
            assert len( example.entries ) == 2

            if debug: print( f"✓ {cls.__name__} smoke test PASSED" )
            return True

        except Exception as e:
            if debug: print( f"✗ {cls.__name__} smoke test FAILED: {e}" )
            import traceback
            traceback.print_exc()
            return False


class VerificationResponse( BaseXMLModel ):
    """
    XML response from Phi-4 for answer verification scoring.

    Used by smoke tests and integration tests to compare expected vs actual
    answers using semantic equivalence instead of exact string matching.

    Requires:
        - LLM compares expected vs actual answers

    Ensures:
        - match is "true" or "false"
        - confidence is a string "0.0" to "1.0"
    """

    match      : str = Field( ..., description="'true' if answers are semantically equivalent, 'false' otherwise" )
    confidence : str = Field( default="0.0", description="Confidence 0.0-1.0" )
    reasoning  : str = Field( default="", description="Why match or no match" )

    @field_validator( "*", mode="before" )
    @classmethod
    def _coerce_none_to_empty_string( cls, v, info ):
        """
        Coerce None values to empty strings for optional string fields.

        Requires:
            - v is the field value (may be None from xmltodict)
            - info.field_name identifies the field

        Ensures:
            - Returns "" for None values on optional fields (confidence, reasoning)
            - Passes through non-None values and required fields unchanged
        """
        if v is None and info.field_name != "match":
            return ""
        return v

    @classmethod
    def get_example_for_template( cls ):
        """
        Get example instance for prompt templates.

        Requires:
            - None

        Ensures:
            - Returns VerificationResponse with placeholder values for template injection
        """
        return cls(
            match      = "[true if answers are semantically equivalent, false otherwise]",
            confidence = "[confidence score between 0.0 and 1.0]",
            reasoning  = "[brief explanation of comparison result]"
        )

    def is_match( self ):
        """
        Check if the answers were judged semantically equivalent.

        Requires:
            - self.match is a string

        Ensures:
            - Returns True if match is "true" (case-insensitive, stripped)
            - Returns False otherwise
        """
        return self.match.strip().lower() == "true"

    def get_confidence_float( self ):
        """
        Parse confidence string to float, clamped to [0.0, 1.0].

        Requires:
            - self.confidence is a string

        Ensures:
            - Returns float in [0.0, 1.0]
            - Returns 0.0 on parse failure
        """
        try:
            return max( 0.0, min( 1.0, float( self.confidence ) ) )
        except ( ValueError, TypeError ):
            return 0.0

    @classmethod
    def quick_smoke_test( cls, debug=False ):
        """
        Quick smoke test for VerificationResponse.

        Args:
            debug: Enable debug output

        Returns:
            True if all tests pass
        """
        if debug: print( f"Testing {cls.__name__}..." )

        try:
            # Test base functionality
            if not super().quick_smoke_test( debug=False ):
                return False

            # Test creation with all fields
            response = cls(
                match      = "true",
                confidence = "0.95",
                reasoning  = "Both answers mean the same thing"
            )
            assert response.match == "true"

            # Test is_match
            assert response.is_match()
            no_match = cls(
                match      = "false",
                confidence = "0.85",
                reasoning  = "Answers differ in meaning"
            )
            assert not no_match.is_match()

            # Test get_confidence_float
            assert response.get_confidence_float() == 0.95
            bad_conf = cls( match="true", confidence="invalid" )
            assert bad_conf.get_confidence_float() == 0.0

            # Test XML round-trip
            xml_str = response.to_xml()
            assert "<match>true</match>" in xml_str
            parsed = cls.from_xml( xml_str )
            assert parsed.match == response.match
            assert parsed.confidence == response.confidence

            # Test template example
            example = cls.get_example_for_template()
            assert "true" in example.match.lower()

            # Test None coercion
            none_response = cls(
                match      = "true",
                confidence = None,
                reasoning  = None
            )
            assert none_response.confidence == ""
            assert none_response.reasoning == ""

            if debug: print( f"✓ {cls.__name__} smoke test PASSED" )
            return True

        except Exception as e:
            if debug: print( f"✗ {cls.__name__} smoke test FAILED: {e}" )
            return False


def quick_smoke_test():
    """Module-level smoke test following CoSA convention."""
    result1 = ScriptMatcherResponse.quick_smoke_test( debug=True )
    result2 = BatchScriptMatcherResponse.quick_smoke_test( debug=True )
    result3 = VerificationResponse.quick_smoke_test( debug=True )
    return result1 and result2 and result3


if __name__ == "__main__":
    success = quick_smoke_test()
    exit( 0 if success else 1 )
