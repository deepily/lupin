"""
Unit tests for the code-line behaviour shared by the code-carrying XML response models.

Twin refactor slice xml-models-code-lines: CodeResponse, CodeBrainstormResponse and
IterativeDebuggingFullResponse carried the same three methods.
CodeResponse and IterativeDebuggingFullResponse also shared to_xml.
FuzzyFileMatchResponse and TFEResumeMatchResponse shared the comma-list getter.
"""

import pytest

from cosa.agents.io_models.xml_models import (
    CodeResponse, CalendarResponse, IterativeDebuggingFullResponse, CodeBrainstormResponse,
    FuzzyFileMatchResponse, TFEResumeMatchResponse
)

CODE_MODELS = [ CodeResponse, IterativeDebuggingFullResponse ]
BASE        = dict( thoughts = "t", returns = "r", example = "e", explanation = "x" )


def _make( cls, code ):
    extra = { "question": "q" } if cls is CalendarResponse else {}
    if cls is CodeBrainstormResponse:
        extra = { "brainstorm": { "idea1": "a", "idea2": "b", "idea3": "c" }, "evaluation": "ev" }
    return cls( code = code, **BASE, **extra )


class TestFunctionName:

    @pytest.mark.parametrize( "cls", [ CodeResponse, CalendarResponse, IterativeDebuggingFullResponse, CodeBrainstormResponse ] )
    def test_first_def_wins_and_none_without_one( self, cls ):
        assert _make( cls, [ "import os", "  def  alpha ( x ):", "def beta():" ] ).get_function_name() == "alpha"
        assert _make( cls, [ "x = 1", "return x" ] ).get_function_name() is None


class TestProcessXmlData:

    @pytest.mark.parametrize( "cls", [ CodeResponse, CalendarResponse, IterativeDebuggingFullResponse, CodeBrainstormResponse ] )
    @pytest.mark.parametrize( "code_dict, expected", [
        ( { "line": [ "a", None, 3 ] }, [ "a", "", "3" ] ),
        ( { "line": "solo" },          [ "solo" ] ),
        ( { "line": None },            [ "" ] ),
    ] )
    def test_xmltodict_code_structure_becomes_a_list_of_strings( self, cls, code_dict, expected ):
        assert _make( cls, code_dict ).code == expected

    @pytest.mark.parametrize( "cls", [ CodeResponse, CalendarResponse, IterativeDebuggingFullResponse, CodeBrainstormResponse ] )
    def test_a_code_dict_without_line_tags_gives_an_empty_list_which_validation_rejects( self, cls ):
        assert cls._extract_lines_from_dict( { "other": "text" } ) == []
        with pytest.raises( ValueError ):
            _make( cls, { "other": "text" } )

    @pytest.mark.parametrize( "cls", [ CodeResponse, IterativeDebuggingFullResponse, CodeBrainstormResponse ] )
    def test_a_plain_list_is_untouched_and_non_dict_input_passes_through( self, cls ):
        assert _make( cls, [ "a", "b" ] ).code == [ "a", "b" ]
        assert cls.process_xml_data( "not a dict" ) == "not a dict"

    def test_the_helper_is_a_classmethod_on_each_model( self ):
        for cls in ( CodeResponse, IterativeDebuggingFullResponse, CodeBrainstormResponse ):
            assert cls._extract_lines_from_dict( { "line": [ "z" ] } ) == [ "z" ]


class TestToXml:

    def test_code_response_field_order( self ):
        xml = _make( CodeResponse, [ "l1", "l2" ] ).to_xml()
        assert [ xml.index( f"<{t}>" ) for t in ( "thoughts", "code", "returns", "example", "explanation" ) ] == sorted(
               xml.index( f"<{t}>" ) for t in ( "thoughts", "code", "returns", "example", "explanation" ) )
        assert "<code><line>l1</line><line>l2</line></code>" in xml.replace( "\n", "" ).replace( "\t", "" ).replace( "  ", "" )

    def test_iterative_debugging_puts_example_before_returns( self ):
        xml = _make( IterativeDebuggingFullResponse, [ "l" ] ).to_xml()
        assert xml.index( "<example>" ) < xml.index( "<returns>" )

    def test_calendar_response_leads_with_question( self ):
        xml = _make( CalendarResponse, [ "l" ] ).to_xml()
        assert xml.index( "<question>" ) < xml.index( "<thoughts>" ) < xml.index( "<code>" ) < xml.index( "<returns>" )

    def test_root_tag_and_pretty_arguments( self ):
        r = _make( CodeResponse, [ "l" ] )
        assert r.to_xml( root_tag = "answer" ).startswith( '<?xml version="1.0" encoding="utf-8"?>\n<answer>' )
        assert "\t" not in r.to_xml( pretty = False )

    def test_exact_output_for_code_response( self ):
        assert _make( CodeResponse, [ "l1" ] ).to_xml() == (
            '<?xml version="1.0" encoding="utf-8"?>\n<response>\n\t<thoughts>t</thoughts>\n\t<code>\n\t\t<line>l1</line>\n\t</code>\n'
            '\t<returns>r</returns>\n\t<example>e</example>\n\t<explanation>x</explanation>\n</response>' )

    def test_exact_output_for_iterative_debugging( self ):
        assert _make( IterativeDebuggingFullResponse, [ "l1" ] ).to_xml() == (
            '<?xml version="1.0" encoding="utf-8"?>\n<response>\n\t<thoughts>t</thoughts>\n\t<code>\n\t\t<line>l1</line>\n\t</code>\n'
            '\t<example>e</example>\n\t<returns>r</returns>\n\t<explanation>x</explanation>\n</response>' )

    def test_brainstorm_keeps_its_own_layout( self ):
        xml = _make( CodeBrainstormResponse, [ "l" ] ).to_xml()
        assert xml.index( "<brainstorm>" ) < xml.index( "<evaluation>" ) < xml.index( "<code>" )


class TestMatchesList:

    @pytest.mark.parametrize( "cls", [ FuzzyFileMatchResponse, TFEResumeMatchResponse ] )
    @pytest.mark.parametrize( "raw, expected", [
        ( "a.py, b.py ,, c.py", [ "a.py", "b.py", "c.py" ] ),
        ( "   ",                [] ),
        ( "solo",               [ "solo" ] ),
    ] )
    def test_comma_list( self, cls, raw, expected ):
        assert cls( matches = raw ).get_matches_list() == expected
