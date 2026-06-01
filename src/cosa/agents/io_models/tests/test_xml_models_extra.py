"""
Coverage-extension tests for prediction-relevant model classes in
cosa/agents/io_models/xml_models.py that the legacy migration tests do NOT cover.

Coverage target: 100% lines + branches + functions on production logic.
quick_smoke_test() blocks are excluded by pyproject.toml exclude_also.

Pure Pydantic model logic ( constructed from inline XML / kwargs ) — no LLM /
network / API boundaries, ZERO API spend.

This file extends the io_models suite ( per the assignment ) covering, in order:
SimpleResponse, CommandResponse, YesNoResponse, ReceptionistResponse.
"""
import pytest
from pydantic import ValidationError

from cosa.agents.io_models.xml_models import (
    SimpleResponse,
    CommandResponse,
    YesNoResponse,
    ReceptionistResponse,
    CodeResponse,
    CalendarResponse,
)
from cosa.agents.io_models.utils.util_xml_pydantic import XMLParsingError


# =========================================================================== #
# SimpleResponse  ( dynamic single-field model )
# =========================================================================== #
def test_simple_response_create_and_accessors():
    r = SimpleResponse.create( "gist", "a brief summary" )
    assert r.get_content()    == "a brief summary"
    assert r.get_field_name() == "gist"


def test_simple_response_from_xml_dynamic_field():
    r = SimpleResponse.from_xml( "<response><summary>detail here</summary></response>" )
    assert r.get_content()    == "detail here"
    assert r.get_field_name() == "summary"


def test_simple_response_get_content_none_when_no_string_field():
    # empty model → model_dump() has no fields → get_content loop never returns → None
    r = SimpleResponse()
    assert r.get_content() is None


def test_simple_response_get_content_skips_non_string_fields():
    # first field non-string → `if isinstance(...)` False → loop continues ( 56->55 ) to the str field
    r = SimpleResponse( count=5, text="real content" )
    assert r.get_content() == "real content"


def test_simple_response_get_field_name_none_when_empty():
    r = SimpleResponse()
    assert r.get_field_name() is None


def test_simple_response_round_trip():
    r = SimpleResponse.create( "answer", "42" )
    assert "<answer>42</answer>" in r.to_xml()


# =========================================================================== #
# CommandResponse
# =========================================================================== #
def test_command_response_from_xml():
    r = CommandResponse.from_xml( "<response><command>math</command><args>2+2</args></response>" )
    assert r.command == "math"
    assert r.args    == "2+2"


def test_command_response_known_command_passes_validator():
    # v.lower() in valid_commands → `if` False branch
    r = CommandResponse( command="calendar", args="" )
    assert r.command == "calendar"


def test_command_response_unknown_command_allowed():
    # v.lower() NOT in valid_commands → `if` True branch ( pass, no raise ) → returns v as-is
    r = CommandResponse( command="brand_new_agent", args="x" )
    assert r.command == "brand_new_agent"


def test_command_response_default_args_empty():
    r = CommandResponse( command="weather" )
    assert r.args == ""


def test_command_response_round_trip():
    xml = CommandResponse( command="todo", args="buy milk" ).to_xml()
    back = CommandResponse.from_xml( xml )
    assert back.command == "todo" and back.args == "buy milk"


# =========================================================================== #
# YesNoResponse
# =========================================================================== #
@pytest.mark.parametrize( "answer,yes,no", [
    ( "yes",   True,  False ),
    ( "no",    False, True ),
    ( "Y",     True,  False ),
    ( "N",     False, True ),
    ( "true",  True,  False ),
    ( "false", False, True ),
] )
def test_yes_no_response_variations( answer, yes, no ):
    r = YesNoResponse( answer=answer )
    assert r.is_yes() is yes
    assert r.is_no()  is no


def test_yes_no_response_normalizes_to_lowercase():
    assert YesNoResponse( answer="YES" ).answer == "yes"


def test_yes_no_response_unknown_answer_allowed_neither():
    # answer not in valid_responses → validator `if` True ( pass ) → kept ( lowered ); neither yes nor no
    r = YesNoResponse( answer="Maybe" )
    assert r.answer == "maybe"
    assert r.is_yes() is False
    assert r.is_no()  is False


def test_yes_no_response_from_xml_round_trip():
    r = YesNoResponse.from_xml( "<response><answer>yes</answer></response>" )
    assert r.is_yes() is True
    assert "<answer>yes</answer>" in r.to_xml()


# =========================================================================== #
# ReceptionistResponse
# =========================================================================== #
def test_receptionist_valid_parse():
    xml = ( "<response><thoughts>analysis</thoughts>"
            "<category>benign</category><answer>hello</answer></response>" )
    r = ReceptionistResponse.from_xml( xml )
    assert r.thoughts == "analysis"
    assert r.category == "benign"
    assert r.answer   == "hello"
    assert r.is_safe_content() is True


def test_receptionist_strips_whitespace():
    r = ReceptionistResponse( thoughts="  t  ", category="benign", answer="  a  " )
    assert r.thoughts == "t"
    assert r.answer   == "a"


def test_receptionist_empty_thoughts_raises():
    with pytest.raises( ValidationError, match="thoughts cannot be empty" ):
        ReceptionistResponse( thoughts="   ", category="benign", answer="a" )


def test_receptionist_empty_answer_raises():
    with pytest.raises( ValidationError, match="answer cannot be empty" ):
        ReceptionistResponse( thoughts="t", category="benign", answer="   " )


@pytest.mark.parametrize( "category,safe", [
    ( "benign",    True ),
    ( "humorous",  True ),
    ( "salacious", False ),
] )
def test_receptionist_is_safe_content( category, safe ):
    r = ReceptionistResponse( thoughts="t", category=category, answer="a" )
    assert r.is_safe_content() is safe


def test_receptionist_invalid_category_raises():
    with pytest.raises( ValidationError ):
        ReceptionistResponse( thoughts="t", category="dangerous", answer="a" )


def test_receptionist_get_example_for_template():
    ex = ReceptionistResponse.get_example_for_template()
    assert ex.category == "benign"
    assert ex.thoughts.startswith( "[" )
    assert ex.answer.startswith( "[" )


def test_receptionist_round_trip():
    xml = ( "<response><thoughts>t</thoughts>"
            "<category>humorous</category><answer>a</answer></response>" )
    r = ReceptionistResponse.from_xml( xml )
    back = ReceptionistResponse.from_xml( r.to_xml() )
    assert back.category == "humorous"


# =========================================================================== #
# CodeResponse
# =========================================================================== #
_CODE_XML = (
    "<response>"
    "<thoughts>write a fn</thoughts>"
    "<code><line>import os</line><line>def add(a, b):</line><line>    return a + b</line></code>"
    "<returns>int</returns><example>add(2,3)</example><explanation>adds</explanation>"
    "</response>"
)


def test_code_response_from_xml_multiline():
    r = CodeResponse.from_xml( _CODE_XML )
    assert r.thoughts == "write a fn"
    assert r.code == [ "import os", "def add(a, b):", "    return a + b" ]
    assert r.returns == "int"


def test_code_response_single_line_code():
    xml = ( "<response><thoughts>t</thoughts><code><line>x = 1</line></code>"
            "<returns>int</returns><example>e</example><explanation>x</explanation></response>" )
    r = CodeResponse.from_xml( xml )
    assert r.code == [ "x = 1" ]


def test_code_response_empty_line_coerced_to_empty_string():
    # multiline list containing an empty <line></line> → None → "" ( the `if line is not None` arc )
    xml = ( "<response><thoughts>t</thoughts>"
            "<code><line>a</line><line></line><line>b</line></code>"
            "<returns>int</returns><example>e</example><explanation>x</explanation></response>" )
    r = CodeResponse.from_xml( xml )
    assert r.code == [ "a", "", "b" ]


def test_code_response_single_empty_line_coerced():
    # single <line></line> → None → [""] ( single-line None arc )
    xml = ( "<response><thoughts>t</thoughts><code><line></line></code>"
            "<returns>int</returns><example>e</example><explanation>x</explanation></response>" )
    r = CodeResponse.from_xml( xml )
    assert r.code == [ "" ]


def test_code_response_code_dict_without_line_key_raises_empty():
    # <code> dict without <line> → _extract returns [] → validate_code raises ( wrapped )
    xml = ( "<response><thoughts>t</thoughts><code><notline>x</notline></code>"
            "<returns>int</returns><example>e</example><explanation>x</explanation></response>" )
    with pytest.raises( XMLParsingError, match="at least one line" ):
        CodeResponse.from_xml( xml )


def test_code_response_process_xml_data_non_dict_passthrough():
    # defensive arm: model_validator(before) returns non-dict input unchanged
    assert CodeResponse.process_xml_data( "not a dict" ) == "not a dict"


def test_code_response_process_xml_data_dict_without_code_passthrough():
    # dict present but no 'code' key → returned unchanged ( the `if 'code' in data` False arc )
    data = { "thoughts": "t" }
    assert CodeResponse.process_xml_data( data ) == { "thoughts": "t" }


def test_code_response_validate_thoughts_empty_raises():
    with pytest.raises( ValidationError, match="Thoughts cannot be empty" ):
        CodeResponse( thoughts="   ", code=[ "x" ], returns="int", example="e", explanation="x" )


def test_code_response_validate_returns_empty_defaults_to_none():
    r = CodeResponse( thoughts="t", code=[ "x" ], returns="", example="e", explanation="x" )
    assert r.returns == "None"


def test_code_response_validate_returns_strips():
    r = CodeResponse( thoughts="t", code=[ "x" ], returns="  bool  ", example="e", explanation="x" )
    assert r.returns == "bool"


def test_code_response_validate_code_empty_raises():
    with pytest.raises( ValidationError, match="at least one line" ):
        CodeResponse( thoughts="t", code=[], returns="int", example="e", explanation="x" )


def test_code_response_get_code_as_string_with_and_without_indent():
    r = CodeResponse.from_xml( _CODE_XML )
    assert "import os" in r.get_code_as_string()
    assert "    import os" in r.get_code_as_string( indent="    " )


def test_code_response_has_imports_true_and_false():
    r_imp = CodeResponse( thoughts="t", code=[ "import os", "x=1" ], returns="int", example="e", explanation="x" )
    assert r_imp.has_imports() is True
    r_no = CodeResponse( thoughts="t", code=[ "x = 1", "y = 2" ], returns="int", example="e", explanation="x" )
    assert r_no.has_imports() is False


def test_code_response_get_function_name_found_and_none():
    r_fn = CodeResponse( thoughts="t", code=[ "def my_fn( a ):", "    pass" ], returns="None", example="e", explanation="x" )
    assert r_fn.get_function_name() == "my_fn"
    r_no = CodeResponse( thoughts="t", code=[ "x = 1" ], returns="int", example="e", explanation="x" )
    assert r_no.get_function_name() is None


def test_code_response_to_xml_nested_line_structure():
    r = CodeResponse( thoughts="t", code=[ "import os", "x=1" ], returns="int", example="e", explanation="x" )
    xml = r.to_xml()
    assert "<line>import os</line>" in xml
    assert "<thoughts>t</thoughts>" in xml


def test_code_response_get_example_for_template():
    ex = CodeResponse.get_example_for_template()
    assert ex.thoughts.startswith( "[" )
    assert any( "def function_name_here" in line for line in ex.code )


# =========================================================================== #
# CalendarResponse  ( extends CodeResponse with a question field )
# =========================================================================== #
_CAL_XML = (
    "<response><question>events today?</question><thoughts>filter</thoughts>"
    "<code><line>r = df[df.date == today]</line></code>"
    "<returns>list</returns><example>e</example><explanation>x</explanation></response>"
)


def test_calendar_response_from_xml():
    r = CalendarResponse.from_xml( _CAL_XML )
    assert r.question == "events today?"
    assert r.code == [ "r = df[df.date == today]" ]
    assert r.has_imports() is False        # inherited helper


def test_calendar_response_validate_question_empty_raises():
    with pytest.raises( ValidationError, match="Question cannot be empty" ):
        CalendarResponse( question="   ", thoughts="t", code=[ "x" ], returns="None", example="e", explanation="x" )


def test_calendar_response_to_xml_includes_question_first():
    r = CalendarResponse.from_xml( _CAL_XML )
    xml = r.to_xml()
    assert "<question>events today?</question>" in xml
    assert "<line>r = df[df.date == today]</line>" in xml


def test_calendar_response_round_trip():
    r = CalendarResponse.from_xml( _CAL_XML )
    back = CalendarResponse.from_xml( r.to_xml() )
    assert back.question == "events today?"
    assert back.returns == "list"


def test_calendar_response_get_example_for_template():
    ex = CalendarResponse.get_example_for_template()
    assert ex.question.startswith( "[" )
    assert ex.thoughts.startswith( "[" )
