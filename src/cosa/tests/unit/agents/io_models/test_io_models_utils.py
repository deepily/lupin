"""
Unit tests for the io_models utils package:
  - utils/util_xml_pydantic.py   ( BaseXMLModel base + XMLParsingError + XMLUtilities )
  - utils/xml_parser_factory.py  ( PydanticXmlParser + XmlParserFactory )
  - utils/prompt_template_processor.py ( PromptTemplateProcessor )

Coverage target: 100% lines + branches + functions on production logic.
quick_smoke_test() + __main__ guards are excluded by pyproject.toml exclude_also.

Pure parsing / templating logic — no LLM / network / API boundaries ( models are
constructed from inline XML strings ), so no external mocking is needed beyond the
xmltodict serialization seam in two negative-path tests.

NOTE for the audit — two defensive regions are flagged to Tiberius as pragma
candidates ( NOT applied here — author proposes, manager applies ):
  - util_xml_pydantic.py:24-25  the `except ImportError: raise ImportError(...)`
    xmltodict-required guard. xmltodict is a hard dependency ( installed in this
    env ), so the except is unreachable. A reload-based cover was tried and
    REMOVED — reloading the shared module redefines BaseXMLModel and breaks
    ValidationError wrapping for the xml_models subclasses ( cross-test pollution );
    a pragma is the clean choice.
  - util_xml_pydantic.py:210-212  the `else: model_data = xml_dict` arm of from_xml.
    xmltodict.parse() yields EXACTLY one root key for any valid XML ( malformed
    multi-root input raises ExpatError first ), so `root_tag not in xml_dict and
    len(xml_dict) != 1` is unreachable. Covered branches: root present (205-206)
    + single non-response root (207-209).
"""
from unittest.mock import patch, MagicMock

import pytest

import cosa.agents.io_models.utils.util_xml_pydantic as uxp_mod
from cosa.agents.io_models.utils.util_xml_pydantic import (
    BaseXMLModel,
    XMLParsingError,
    XMLUtilities,
    remove_xml_escapes,
)
from cosa.agents.io_models.utils.xml_parser_factory import (
    PydanticXmlParser,
    XmlParserFactory,
)
from cosa.agents.io_models.utils.prompt_template_processor import PromptTemplateProcessor
from cosa.agents.io_models.xml_models import (
    BugInjectionResponse,
    WeatherResponse,
    IterativeDebuggingMinimalistResponse,
    IterativeDebuggingFullResponse,
)


# =========================================================================== #
# remove_xml_escapes
# =========================================================================== #
def test_remove_xml_escapes():
    assert remove_xml_escapes( "a &gt; b &lt; c &amp; d" ) == "a > b < c & d"


# =========================================================================== #
# XMLParsingError.__init__ ( message / xml_content truncation / original_error )
# =========================================================================== #
def test_xml_parsing_error_message_only():
    err = XMLParsingError( "boom" )
    assert str( err ) == "boom"
    assert err.xml_content is None
    assert err.original_error is None


def test_xml_parsing_error_with_short_xml_and_cause():
    cause = ValueError( "root cause" )
    err = XMLParsingError( "boom", xml_content="<a/>", original_error=cause )
    assert "XML: <a/>" in str( err )
    assert "Cause: root cause" in str( err )
    assert err.original_error is cause


def test_xml_parsing_error_truncates_long_xml():
    long_xml = "<x>" + ( "y" * 500 ) + "</x>"
    err = XMLParsingError( "boom", xml_content=long_xml )
    assert err.xml_content.endswith( "..." )
    assert len( err.xml_content ) == 203          # 200 chars + "..."


# =========================================================================== #
# BaseXMLModel.from_xml — prefix/suffix stripping, root extraction, errors
# =========================================================================== #
def test_from_xml_empty_raises():
    with pytest.raises( XMLParsingError, match="empty or whitespace" ):
        BaseXMLModel.from_xml( "   " )


def test_from_xml_basic_response_root():
    obj = BaseXMLModel.from_xml( "<response><field>val</field></response>" )
    assert obj.field == "val"


def test_from_xml_strips_prefix_before_xml_declaration( capsys ):
    xml = "Here is the response: <?xml version='1.0'?><response><a>1</a></response>"
    obj = BaseXMLModel.from_xml( xml )
    assert obj.a == "1"
    assert "Stripping" in capsys.readouterr().out


def test_from_xml_strips_prefix_before_root_tag( capsys ):
    xml = "Output:\n<response><a>1</a></response>"
    obj = BaseXMLModel.from_xml( xml )
    assert obj.a == "1"
    assert "Stripping" in capsys.readouterr().out


def test_from_xml_strips_suffix_after_closing_tag( capsys ):
    xml = "<response><a>1</a></response>\nand some trailing explanation text"
    obj = BaseXMLModel.from_xml( xml )
    assert obj.a == "1"
    assert "Stripping" in capsys.readouterr().out


def test_from_xml_escapes_bare_ampersand():
    obj = BaseXMLModel.from_xml( "<response><a>Q&A session</a></response>" )
    assert obj.a == "Q&A session"


def test_from_xml_explicit_root_tag():
    # root_tag is not None → skips the `root_tag = 'response'` default ( 202->205 false arc )
    obj = BaseXMLModel.from_xml( "<result><a>1</a></result>", root_tag="result" )
    assert obj.a == "1"


def test_from_xml_single_non_response_root_used():
    # root_tag 'response' not present, but a single root element → use it ( elif len==1 )
    obj = BaseXMLModel.from_xml( "<custom><a>1</a></custom>" )
    assert obj.a == "1"


def test_from_xml_empty_tags_yield_empty_model():
    # <response></response> → model_data None → {} → empty BaseXMLModel ( extra=allow )
    obj = BaseXMLModel.from_xml( "<response></response>" )
    assert isinstance( obj, BaseXMLModel )


def test_from_xml_malformed_raises_xml_parsing_error():
    # mismatched tags → xmltodict ExpatError → wrapped XMLParsingError
    with pytest.raises( XMLParsingError, match="Invalid XML format" ):
        BaseXMLModel.from_xml( "<response><a></b></response>" )


def test_from_xml_validation_error_wrapped():
    # BugInjectionResponse requires int line_number → non-int → ValidationError → wrapped
    with pytest.raises( XMLParsingError, match="Data validation failed" ):
        BugInjectionResponse.from_xml( "<response><line-number>NaN</line-number><bug>x</bug></response>" )


def test_from_xml_generic_exception_wrapped():
    # <response>plaintext</response> → model_data is the str 'plaintext' → cls(**'plaintext')
    # raises TypeError → caught by the generic except → wrapped XMLParsingError
    with pytest.raises( XMLParsingError, match="Unexpected error parsing XML" ):
        BaseXMLModel.from_xml( "<response>plaintext</response>" )


# =========================================================================== #
# BaseXMLModel.to_xml / __str__ / __repr__
# =========================================================================== #
def test_to_xml_round_trip():
    obj = BaseXMLModel.from_xml( "<response><field>val</field></response>" )
    xml = obj.to_xml()
    assert "<response>" in xml and "<field>val</field>" in xml


def test_to_xml_wraps_serialization_error():
    obj = BaseXMLModel.from_xml( "<response><a>1</a></response>" )
    with patch.object( uxp_mod.xmltodict, "unparse", side_effect=RuntimeError( "serialize boom" ) ):
        with pytest.raises( XMLParsingError, match="Failed to serialize model to XML" ):
            obj.to_xml()


def test_str_uses_to_xml():
    obj = BaseXMLModel.from_xml( "<response><a>1</a></response>" )
    assert "<a>1</a>" in str( obj )


def test_str_falls_back_on_to_xml_failure():
    obj = BaseXMLModel.from_xml( "<response><a>1</a></response>" )
    with patch.object( uxp_mod.xmltodict, "unparse", side_effect=RuntimeError( "boom" ) ):
        # __str__ swallows the XMLParsingError and falls back to BaseModel.__str__
        assert isinstance( str( obj ), str )


def test_repr_developer_friendly():
    obj = BaseXMLModel.from_xml( "<response><a>1</a></response>" )
    assert obj.__class__.__name__ in repr( obj )


# =========================================================================== #
# XMLUtilities
# =========================================================================== #
def test_validate_xml_structure_valid_no_required():
    result = XMLUtilities.validate_xml_structure( "<response><a>1</a></response>" )
    assert result[ "valid_xml" ] is True
    assert result[ "has_response_wrapper" ] is True


def test_validate_xml_structure_required_tags_present():
    result = XMLUtilities.validate_xml_structure(
        "<response><a>1</a><b>2</b></response>", required_tags=[ "a", "b" ]
    )
    assert result[ "required_tags_present" ] is True
    assert result[ "missing_tags" ] == []


def test_validate_xml_structure_required_tags_missing():
    result = XMLUtilities.validate_xml_structure(
        "<response><a>1</a></response>", required_tags=[ "a", "missing" ]
    )
    assert result[ "required_tags_present" ] is False
    assert result[ "missing_tags" ] == [ "missing" ]


def test_validate_xml_structure_invalid_xml():
    result = XMLUtilities.validate_xml_structure( "<a></b>" )
    assert result[ "valid_xml" ] is False
    assert "error" in result


def test_compare_with_baseline_match_debug( capsys ):
    result = XMLUtilities.compare_with_baseline( "x", "x", debug=True )
    assert result[ "values_match" ] is True
    assert "Values match" in capsys.readouterr().out


def test_compare_with_baseline_differ_debug( capsys ):
    result = XMLUtilities.compare_with_baseline( "x", "y", debug=True )
    assert result[ "values_match" ] is False
    assert "Values differ" in capsys.readouterr().out


def test_compare_with_baseline_no_debug():
    result = XMLUtilities.compare_with_baseline( "x", "x", debug=False )
    assert result[ "values_match" ] is True


# =========================================================================== #
# PydanticXmlParser — debug/verbose prints, unsupported agent, error branch,
# _get_debugging_model default arm
# =========================================================================== #
def test_parser_parse_debug_verbose_success( capsys ):
    parser = PydanticXmlParser()
    xml = "<response><thoughts>t</thoughts><category>benign</category><answer>a</answer></response>"
    result = parser.parse_xml_response(
        xml, "agent router go to receptionist", [ "thoughts", "category", "answer" ],
        debug=True, verbose=True,
    )
    assert result[ "answer" ] == "a"
    out = capsys.readouterr().out
    assert "parsing XML for agent" in out
    assert "Using Pydantic model" in out
    assert "Successfully parsed" in out


def test_parser_unsupported_agent_raises():
    parser = PydanticXmlParser()
    with pytest.raises( ValueError, match="not yet implemented" ):
        parser.parse_xml_response( "<response/>", "agent router go to nonexistent", [ "x" ] )


def test_parser_parse_failure_debug_branch_reraises( capsys ):
    parser = PydanticXmlParser()
    bad_xml = "<response><line-number>NaN</line-number><bug>x</bug></response>"
    with pytest.raises( Exception ):
        parser.parse_xml_response( bad_xml, "agent router go to bug injector", [ "line-number", "bug" ], debug=True )
    assert "Pydantic parsing failed" in capsys.readouterr().out


def test_get_debugging_model_minimalist():
    parser = PydanticXmlParser()
    assert parser._get_debugging_model( [ "thoughts", "one-line-of-code", "success" ] ) is IterativeDebuggingMinimalistResponse


def test_get_debugging_model_full():
    parser = PydanticXmlParser()
    assert parser._get_debugging_model( [ "thoughts", "code", "explanation" ] ) is IterativeDebuggingFullResponse


def test_get_debugging_model_default_arm():
    # neither minimalist signal nor (code AND explanation) → default minimalist ( else arm )
    parser = PydanticXmlParser()
    assert parser._get_debugging_model( [ "thoughts" ] ) is IterativeDebuggingMinimalistResponse


# =========================================================================== #
# XmlParserFactory — debug_mode init + parse_agent_response debug print
# =========================================================================== #
class _DebugConfig:
    def get( self, key, default=None, return_type=None ):
        if key == "xml parsing migration debug mode":
            return True
        return default


def test_factory_debug_mode_init_and_parse_print( capsys ):
    factory = XmlParserFactory( _DebugConfig() )
    assert factory.debug_mode is True
    assert "initialized with Pydantic-only parsing" in capsys.readouterr().out

    xml = "<response><thoughts>t</thoughts><category>benign</category><answer>a</answer></response>"
    factory.parse_agent_response( xml, "agent router go to receptionist", [ "thoughts", "category", "answer" ] )
    assert "Parsing XML response using Pydantic parser" in capsys.readouterr().out


# =========================================================================== #
# PromptTemplateProcessor
# =========================================================================== #
def test_processor_get_example_for_known_agent_debug( capsys ):
    proc = PromptTemplateProcessor( debug=True )
    xml = proc.get_example_for_agent( "agent router go to math" )
    assert "<response>" in xml
    assert "Generating XML example" in capsys.readouterr().out


def test_processor_get_example_unknown_agent_verbose_returns_none( capsys ):
    proc = PromptTemplateProcessor( verbose=True )
    assert proc.get_example_for_agent( "no such agent" ) is None
    assert "No model mapping" in capsys.readouterr().out


def test_processor_process_template_replaces_marker_debug( capsys ):
    proc = PromptTemplateProcessor( debug=True )
    out = proc.process_template( "before {{PYDANTIC_XML_EXAMPLE}} after", "agent router go to math" )
    assert "{{PYDANTIC_XML_EXAMPLE}}" not in out
    assert "</stop>" in out
    assert "Replaced XML marker" in capsys.readouterr().out


def test_processor_process_template_no_marker_debug( capsys ):
    proc = PromptTemplateProcessor( debug=True )
    out = proc.process_template( "no markers here", "agent router go to math" )
    assert out == "no markers here"
    assert "No XML markers found" in capsys.readouterr().out


def test_processor_process_template_marker_but_unknown_agent_debug( capsys ):
    # marker present but agent has no model → xml_example None → else branch keeps template
    proc = PromptTemplateProcessor( debug=True )
    template = "before {{PYDANTIC_XML_EXAMPLE}} after"
    out = proc.process_template( template, "no such agent" )
    assert out == template
    assert "No XML generator" in capsys.readouterr().out


# ---- debug=False arcs ( the `if self.debug:` False skips: 86->88, 110->112, 122->124, 126->128 ) ----
def test_processor_debug_false_branches_get_example():
    proc = PromptTemplateProcessor( debug=False )
    assert "<response>" in proc.get_example_for_agent( "agent router go to math" )   # 86->88


def test_processor_debug_false_no_marker():
    proc = PromptTemplateProcessor( debug=False )
    assert proc.process_template( "no markers", "agent router go to math" ) == "no markers"   # 110->112


def test_processor_debug_false_replaces_marker():
    proc = PromptTemplateProcessor( debug=False )
    out = proc.process_template( "x {{PYDANTIC_XML_EXAMPLE}} y", "agent router go to math" )   # 122->124
    assert "{{PYDANTIC_XML_EXAMPLE}}" not in out and "</stop>" in out


def test_processor_debug_false_unknown_agent_keeps_template():
    proc = PromptTemplateProcessor( debug=False )
    template = "x {{PYDANTIC_XML_EXAMPLE}} y"
    assert proc.process_template( template, "no such agent" ) == template   # 126->128
