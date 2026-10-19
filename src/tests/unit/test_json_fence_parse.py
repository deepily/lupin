"""
Unit tests for the JSON fence-strip helpers.

Twin refactor slice json-fence-parse: the helpers replace three copies in deep_research/prompts
(clarification, planning, subagent) and two in presentation_generator/prompts (narrative, outline).
"""

import pytest

from cosa.agents.io_models.utils.json_object_recovery import (
    strip_json_fence, parse_fenced_json, extract_json_metadata
)
from cosa.agents.deep_research.prompts.clarification import parse_clarification_response
from cosa.agents.deep_research.prompts.planning import parse_planning_response
from cosa.agents.deep_research.prompts.subagent import parse_subagent_response
from cosa.agents.presentation_generator.prompts.narrative import extract_narrative_metadata
from cosa.agents.presentation_generator.prompts.outline import extract_outline_metadata


class TestStripJsonFence:

    @pytest.mark.parametrize( "raw, expected", [
        ( '{"a": 1}',                    '{"a": 1}' ),
        ( '  {"a": 1}  ',                '{"a": 1}' ),
        ( '```json\n{"a": 1}\n```',      '{"a": 1}' ),
        ( '```\n{"a": 1}\n```',          '{"a": 1}' ),
        ( '```json\n{"a": 1}',           '{"a": 1}' ),
        ( '{"a": 1}\n```',               '{"a": 1}' ),
        ( '',                            '' ),
    ] )
    def test_strips_markers_and_whitespace( self, raw, expected ):
        assert strip_json_fence( raw ) == expected

    def test_prose_after_closing_fence_is_kept( self ):
        """The plain strip does not drop trailing prose; recover_json_object does that."""
        assert strip_json_fence( '```json\n{"a": 1}\n```\nNote.' ) == '{"a": 1}\n```\nNote.'


class TestDoubleLeadingMarker:
    """```json directly followed by a bare ``` is where the two old behaviours differ."""

    EDGE = '```json```{"total_slides": 3}```'

    def test_default_mode_removes_both_leading_markers( self ):
        assert strip_json_fence( self.EDGE ) == '{"total_slides": 3}'

    def test_single_leading_mode_keeps_the_second_marker( self ):
        assert strip_json_fence( self.EDGE, single_leading = True ) == '```{"total_slides": 3}'

    def test_single_leading_mode_still_strips_a_lone_bare_fence( self ):
        assert strip_json_fence( '```\n{"a": 1}\n```', single_leading = True ) == '{"a": 1}'

    def test_deep_research_parsers_use_the_default_mode( self ):
        assert parse_planning_response( self.EDGE )      == { "total_slides": 3 }
        assert parse_clarification_response( self.EDGE ) == { "total_slides": 3 }
        assert parse_subagent_response( self.EDGE )      == { "total_slides": 3 }
        assert parse_fenced_json( self.EDGE, "x" )       == { "total_slides": 3 }

    def test_presentation_extractors_use_the_single_leading_mode( self ):
        """The old if/elif body returned {} here; the helper must keep doing so."""
        assert extract_outline_metadata( self.EDGE )   == {}
        assert extract_narrative_metadata( self.EDGE ) == {}
        assert extract_json_metadata( self.EDGE, { "total_slides": 0 } ) == {}


class TestParseFencedJson:

    def test_returns_parsed_document( self ):
        assert parse_fenced_json( '```json\n{"a": [1, 2]}\n```', "x" ) == { "a": [ 1, 2 ] }

    def test_error_message_carries_label_and_cause( self ):
        with pytest.raises( ValueError ) as exc:
            parse_fenced_json( "not json", "planning" )
        assert str( exc.value ).startswith( "Could not parse planning response as JSON: " )
        assert "Expecting value" in str( exc.value )


class TestExtractJsonMetadata:

    DEFAULTS = { "n": 0, "note": "" }

    def test_present_keys_win_over_defaults( self ):
        assert extract_json_metadata( '```json\n{"n": 7, "note": "hi", "other": 1}\n```', self.DEFAULTS ) == { "n": 7, "note": "hi" }

    def test_missing_keys_take_the_default_in_order( self ):
        out = extract_json_metadata( '{"note": "x"}', self.DEFAULTS )
        assert out == { "n": 0, "note": "x" }
        assert list( out ) == [ "n", "note" ]

    def test_invalid_json_gives_empty_dict( self ):
        assert extract_json_metadata( "nope", self.DEFAULTS ) == {}

    def test_valid_json_that_is_not_an_object_raises( self ):
        """Pins the old behaviour: a list has no .get, and the original code did not catch that."""
        with pytest.raises( AttributeError ):
            extract_json_metadata( "[1, 2]", self.DEFAULTS )


class TestCallSitesStillBehaveTheSame:
    """Pin each of the five converted functions to the literal output its old body gave."""

    @pytest.mark.parametrize( "fn, label", [
        ( parse_clarification_response, "clarification" ),
        ( parse_planning_response,      "planning" ),
        ( parse_subagent_response,      "subagent" ),
    ] )
    def test_deep_research_parsers( self, fn, label ):
        assert fn( '```json\n{"k": "v"}\n```' ) == { "k": "v" }
        with pytest.raises( ValueError, match = f"^Could not parse {label} response as JSON" ):
            fn( "garbage" )

    def test_narrative_metadata( self ):
        assert extract_narrative_metadata( '```json\n{"total_proposed_slides": 9, "narrative_assessment": "ok"}\n```' ) == {
            "total_proposed_slides": 9, "narrative_assessment": "ok" }
        assert extract_narrative_metadata( "{}" ) == { "total_proposed_slides": 0, "narrative_assessment": "" }
        assert extract_narrative_metadata( "garbage" ) == {}

    def test_outline_metadata( self ):
        assert extract_outline_metadata( '```\n{"total_slides": 4, "narrative_coherence_note": "n"}\n```' ) == {
            "total_slides": 4, "narrative_coherence_note": "n" }
        assert extract_outline_metadata( "{}" ) == { "total_slides": 0, "narrative_coherence_note": "" }
        assert extract_outline_metadata( "garbage" ) == {}
