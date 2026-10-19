"""
Unit tests for extract_tagged_xml and the two dispatcher functions that call it.

Twin refactor slice xml-extract-tag: calculator and crud_for_dataframes each carried a copy.
"""

import pytest

from cosa.agents.io_models.utils.util_xml_pydantic import extract_tagged_xml
from cosa.agents.calculator.dispatcher import extract_calc_intent_xml
from cosa.crud_for_dataframes.dispatcher import extract_intent_xml


class TestExtractTaggedXml:

    @pytest.mark.parametrize( "raw", [ None, "", "   \n " ] )
    def test_empty_or_blank_raises( self, raw ):
        with pytest.raises( ValueError, match = "^Empty response from LLM$" ):
            extract_tagged_xml( raw, "intent" )

    def test_clean_block_is_returned_as_is( self ):
        assert extract_tagged_xml( "<intent><op>read</op></intent>", "intent" ) == "<intent><op>read</op></intent>"

    def test_fenced_block_loses_the_fence( self ):
        assert extract_tagged_xml( "```xml\n<intent>a</intent>\n```", "intent" ) == "<intent>a</intent>"

    def test_preamble_and_trailing_prose_are_dropped( self ):
        raw = "Sure, here it is:\n<intent>\n  <op>x</op>\n</intent>\nHope that helps."
        assert extract_tagged_xml( raw, "intent" ) == "<intent>\n  <op>x</op>\n</intent>"

    def test_space_before_the_closing_bracket_of_the_open_tag_is_allowed( self ):
        assert extract_tagged_xml( "<intent >a</intent>", "intent" ) == "<intent >a</intent>"

    def test_first_block_wins( self ):
        assert extract_tagged_xml( "<intent>1</intent><intent>2</intent>", "intent" ) == "<intent>1</intent>"

    def test_the_tag_is_what_selects_the_block( self ):
        raw = "<intent>a</intent><calc_intent>b</calc_intent>"
        assert extract_tagged_xml( raw, "calc_intent" ) == "<calc_intent>b</calc_intent>"

    def test_missing_block_error_names_the_tag_and_quotes_the_first_100_chars( self ):
        raw = "x" * 150
        with pytest.raises( ValueError ) as exc:
            extract_tagged_xml( raw, "intent" )
        assert str( exc.value ) == "No <intent>...</intent> block found in LLM response. Response starts with: " + "x" * 100


class TestDispatcherWrappers:
    """Pin each wrapper to the tag it must ask for."""

    def test_calc_wrapper_asks_for_calc_intent( self ):
        raw = "<intent>no</intent>\n```xml\n<calc_intent>yes</calc_intent>\n```"
        assert extract_calc_intent_xml( raw ) == "<calc_intent>yes</calc_intent>"
        with pytest.raises( ValueError, match = "No <calc_intent>...</calc_intent> block" ):
            extract_calc_intent_xml( "<intent>no</intent>" )

    def test_crud_wrapper_asks_for_intent( self ):
        raw = "<calc_intent>no</calc_intent>\n<intent>yes</intent>"
        assert extract_intent_xml( raw ) == "<intent>yes</intent>"
        with pytest.raises( ValueError, match = "No <intent>...</intent> block" ):
            extract_intent_xml( "<calc_intent>no</calc_intent>" )
