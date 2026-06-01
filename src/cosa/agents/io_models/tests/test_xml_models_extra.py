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
    BrainstormIdeas,
    CodeBrainstormResponse,
    BugInjectionResponse,
    IterativeDebuggingMinimalistResponse,
    IterativeDebuggingFullResponse,
    WeatherResponse,
    FormatterResponse,
    VoxCommandResponse,
    AgentRouterResponse,
    GistResponse,
    ConfirmationResponse,
    QualifierClassification,
    FuzzyFileMatchResponse,
    TFEResumeMatchResponse,
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


# =========================================================================== #
# BrainstormIdeas  ( nested three-idea model )
# =========================================================================== #
def test_brainstorm_ideas_valid_strips():
    b = BrainstormIdeas( idea1="  a  ", idea2="b", idea3="c" )
    assert b.idea1 == "a" and b.idea2 == "b" and b.idea3 == "c"


def test_brainstorm_ideas_empty_raises():
    # validate_ideas True arc: empty/whitespace → ValueError
    with pytest.raises( ValidationError, match="Brainstorm ideas cannot be empty" ):
        BrainstormIdeas( idea1="   ", idea2="b", idea3="c" )


def test_brainstorm_ideas_get_example_for_template():
    ex = BrainstormIdeas.get_example_for_template()
    assert ex.idea1 == "Your first idea"
    assert ex.idea3 == "Your third idea"


# =========================================================================== #
# CodeBrainstormResponse
# =========================================================================== #
_BRAINSTORM_XML = (
    "<response>"
    "<thoughts>reason</thoughts>"
    "<brainstorm><idea1>a</idea1><idea2>b</idea2><idea3>c</idea3></brainstorm>"
    "<evaluation>chose a</evaluation>"
    "<code><line>import os</line><line>def add(a, b):</line><line>    return a + b</line></code>"
    "<returns>int</returns><example>add(1,2)</example><explanation>adds</explanation>"
    "</response>"
)


def _make_code_brainstorm( **overrides ):
    kwargs = dict(
        thoughts    = "reason",
        brainstorm  = BrainstormIdeas( idea1="a", idea2="b", idea3="c" ),
        evaluation  = "chose a",
        code        = [ "import os", "def add(a, b):", "    return a + b" ],
        returns     = "int",
        example     = "add(1,2)",
        explanation = "adds",
    )
    kwargs.update( overrides )
    return CodeBrainstormResponse( **kwargs )


def test_code_brainstorm_from_xml_nested_code_list():
    # process_xml_data dict + 'code' dict arc ( 1242 ) → _extract list arc ( 1269 )
    r = CodeBrainstormResponse.from_xml( _BRAINSTORM_XML )
    assert r.thoughts == "reason"
    assert r.brainstorm.idea1 == "a"
    assert r.evaluation == "chose a"
    assert r.code == [ "import os", "def add(a, b):", "    return a + b" ]


def test_code_brainstorm_from_xml_single_line_code():
    # _extract single-line ( else ) arc ( 1271-1272 )
    xml = (
        "<response><thoughts>t</thoughts>"
        "<brainstorm><idea1>a</idea1><idea2>b</idea2><idea3>c</idea3></brainstorm>"
        "<evaluation>e</evaluation><code><line>x = 1</line></code>"
        "<returns>int</returns><example>e</example><explanation>x</explanation></response>"
    )
    r = CodeBrainstormResponse.from_xml( xml )
    assert r.code == [ "x = 1" ]


def test_code_brainstorm_from_xml_no_line_key_raises_empty():
    # _extract else ( no 'line' key ) arc ( 1275 ) → [] → validate_code raises ( wrapped )
    xml = (
        "<response><thoughts>t</thoughts>"
        "<brainstorm><idea1>a</idea1><idea2>b</idea2><idea3>c</idea3></brainstorm>"
        "<evaluation>e</evaluation><code><notline>x</notline></code>"
        "<returns>int</returns><example>e</example><explanation>x</explanation></response>"
    )
    with pytest.raises( XMLParsingError, match="at least one line" ):
        CodeBrainstormResponse.from_xml( xml )


def test_code_brainstorm_process_xml_data_non_dict_passthrough():
    # defensive non-dict arm ( 1238 )
    assert CodeBrainstormResponse.process_xml_data( "not a dict" ) == "not a dict"


def test_code_brainstorm_process_xml_data_dict_without_code_passthrough():
    # 'code' not in data arc ( 1241 False )
    data = { "thoughts": "t" }
    assert CodeBrainstormResponse.process_xml_data( data ) == { "thoughts": "t" }


def test_code_brainstorm_validate_code_empty_raises():
    with pytest.raises( ValidationError, match="at least one line" ):
        _make_code_brainstorm( code=[] )


def test_code_brainstorm_validate_text_fields_empty_raises():
    with pytest.raises( ValidationError, match="Text fields cannot be empty" ):
        _make_code_brainstorm( evaluation="   " )


def test_code_brainstorm_validate_returns_empty_defaults_to_none():
    r = _make_code_brainstorm( returns="" )
    assert r.returns == "None"


def test_code_brainstorm_to_xml_nested_structure():
    r = _make_code_brainstorm()
    xml = r.to_xml()
    assert "<idea1>a</idea1>" in xml
    assert "<line>import os</line>" in xml
    assert "<evaluation>chose a</evaluation>" in xml


def test_code_brainstorm_get_code_as_string_with_indent():
    r = _make_code_brainstorm()
    assert "import os" in r.get_code_as_string()
    assert "    import os" in r.get_code_as_string( indent="    " )


def test_code_brainstorm_has_imports_true_and_false():
    assert _make_code_brainstorm( code=[ "import os", "x=1" ] ).has_imports() is True
    assert _make_code_brainstorm( code=[ "x = 1", "y = 2" ] ).has_imports() is False


def test_code_brainstorm_get_function_name_found_and_none():
    assert _make_code_brainstorm( code=[ "def my_fn( a ):", "    pass" ] ).get_function_name() == "my_fn"
    assert _make_code_brainstorm( code=[ "x = 1" ] ).get_function_name() is None


# =========================================================================== #
# BugInjectionResponse
# =========================================================================== #
def test_bug_injection_from_xml_valid():
    xml = "<response><line-number>5</line-number><bug>x = bad_code</bug></response>"
    r = BugInjectionResponse.from_xml( xml )
    assert r.line_number == 5
    assert r.bug == "x = bad_code"


def test_bug_injection_empty_bug_raises():
    # validate_bug_code: cleaned empty arc ( 1635 )
    with pytest.raises( ValidationError, match="Bug code cannot be empty" ):
        BugInjectionResponse( line_number=1, bug="   " )


def test_bug_injection_is_valid_response():
    assert BugInjectionResponse( line_number=3, bug="b" ).is_valid_response() is True
    # -1 sentinel is a valid construction but an "invalid" response
    assert BugInjectionResponse( line_number=-1, bug="b" ).is_valid_response() is False


def test_bug_injection_validate_against_code_length():
    # is_valid_response False arc ( 1658-1659 )
    assert BugInjectionResponse( line_number=-1, bug="b" ).validate_against_code_length( 10 ) is False
    # range-check arc ( 1660 ): within and outside
    r = BugInjectionResponse( line_number=5, bug="b" )
    assert r.validate_against_code_length( 10 ) is True
    assert r.validate_against_code_length( 3 )  is False


def test_bug_injection_line_number_below_minus_one_raises():
    with pytest.raises( ValidationError, match="must be -1" ):
        BugInjectionResponse( line_number=-2, bug="b" )


def test_bug_injection_line_number_zero_raises():
    with pytest.raises( ValidationError, match="cannot be 0" ):
        BugInjectionResponse( line_number=0, bug="b" )


def test_bug_injection_to_xml_hyphenated():
    xml = BugInjectionResponse( line_number=3, bug="oops" ).to_xml()
    assert "<line-number>3</line-number>" in xml
    assert "<bug>oops</bug>" in xml


def test_bug_injection_get_example_for_template():
    ex = BugInjectionResponse.get_example_for_template()
    assert ex.line_number == 1
    assert ex.bug.startswith( "[" )


# =========================================================================== #
# IterativeDebuggingMinimalistResponse
# =========================================================================== #
_MIN_XML = (
    "<response><thoughts>misspelled var</thoughts><line-number>3</line-number>"
    "<one-line-of-code>result = calc(a, b)</one-line-of-code><success>True</success></response>"
)


def test_min_debug_from_xml_and_is_successful():
    r = IterativeDebuggingMinimalistResponse.from_xml( _MIN_XML )
    assert r.line_number == 3
    assert r.one_line_of_code == "result = calc(a, b)"
    assert r.is_successful() is True
    assert IterativeDebuggingMinimalistResponse(
        thoughts="t", line_number=1, one_line_of_code="x=1", success="False"
    ).is_successful() is False


def test_min_debug_validate_line_number_raises():
    with pytest.raises( ValidationError, match="must be positive" ):
        IterativeDebuggingMinimalistResponse(
            thoughts="t", line_number=0, one_line_of_code="x=1", success="True"
        )


def test_min_debug_validate_success_raises():
    with pytest.raises( ValidationError, match="must be 'True' or 'False'" ):
        IterativeDebuggingMinimalistResponse(
            thoughts="t", line_number=1, one_line_of_code="x=1", success="maybe"
        )


def test_min_debug_validate_thoughts_empty_raises():
    with pytest.raises( ValidationError, match="thoughts cannot be empty" ):
        IterativeDebuggingMinimalistResponse(
            thoughts="   ", line_number=1, one_line_of_code="x=1", success="True"
        )


def test_min_debug_validate_code_line_empty_raises():
    with pytest.raises( ValidationError, match="one_line_of_code cannot be empty" ):
        IterativeDebuggingMinimalistResponse(
            thoughts="t", line_number=1, one_line_of_code="   ", success="True"
        )


def test_min_debug_to_xml_hyphenated():
    xml = IterativeDebuggingMinimalistResponse(
        thoughts="t", line_number=2, one_line_of_code="y=2", success="True"
    ).to_xml()
    assert "<line-number>2</line-number>" in xml
    assert "<one-line-of-code>y=2</one-line-of-code>" in xml
    assert "<success>True</success>" in xml


def test_min_debug_get_example_for_template():
    ex = IterativeDebuggingMinimalistResponse.get_example_for_template()
    assert ex.line_number == 1
    assert ex.success == "True"


# =========================================================================== #
# IterativeDebuggingFullResponse
# =========================================================================== #
_FULL_XML = (
    "<response><thoughts>logic error</thoughts>"
    "<code><line>import math</line><line>def area(r):</line><line>    return math.pi*r*r</line></code>"
    "<example>area(5)</example><returns>float</returns><explanation>fixed</explanation></response>"
)


def _make_full_debug( **overrides ):
    kwargs = dict(
        thoughts    = "logic error",
        code        = [ "import math", "def area(r):", "    return math.pi*r*r" ],
        example     = "area(5)",
        returns     = "float",
        explanation = "fixed",
    )
    kwargs.update( overrides )
    return IterativeDebuggingFullResponse( **kwargs )


def test_full_debug_from_xml_list_code():
    r = IterativeDebuggingFullResponse.from_xml( _FULL_XML )
    assert len( r.code ) == 3
    assert r.has_imports() is True
    assert r.get_function_name() == "area"


def test_full_debug_from_xml_single_line_code():
    # _extract single-line else arc ( 2003 )
    xml = (
        "<response><thoughts>t</thoughts><code><line>x = 1</line></code>"
        "<example>e</example><returns>int</returns><explanation>x</explanation></response>"
    )
    assert IterativeDebuggingFullResponse.from_xml( xml ).code == [ "x = 1" ]


def test_full_debug_from_xml_no_line_key_raises_empty():
    # _extract else ( no line ) arc ( 2005 ) → [] → validate_code raises
    xml = (
        "<response><thoughts>t</thoughts><code><notline>x</notline></code>"
        "<example>e</example><returns>int</returns><explanation>x</explanation></response>"
    )
    with pytest.raises( XMLParsingError, match="at least one line" ):
        IterativeDebuggingFullResponse.from_xml( xml )


def test_full_debug_process_xml_data_non_dict_passthrough():
    # defensive non-dict arm ( 1987 )
    assert IterativeDebuggingFullResponse.process_xml_data( 42 ) == 42


def test_full_debug_validate_code_empty_raises():
    with pytest.raises( ValidationError, match="at least one line" ):
        _make_full_debug( code=[] )


def test_full_debug_validate_text_fields_empty_raises():
    with pytest.raises( ValidationError, match="Text fields cannot be empty" ):
        _make_full_debug( explanation="   " )


def test_full_debug_validate_returns_empty_defaults_to_none():
    assert _make_full_debug( returns="" ).returns == "None"


def test_full_debug_get_code_as_string_and_helpers():
    r = _make_full_debug()
    assert "    import math" in r.get_code_as_string( indent="    " )


def test_full_debug_get_function_name_none():
    # loop completes with no def → return None ( 2049 )
    assert _make_full_debug( code=[ "x = 1", "y = 2" ] ).get_function_name() is None
    assert _make_full_debug( code=[ "x = 1" ] ).has_imports() is False


def test_full_debug_to_xml_nested_structure():
    xml = _make_full_debug().to_xml()
    assert "<line>import math</line>" in xml
    assert "<explanation>fixed</explanation>" in xml


def test_full_debug_get_example_for_template():
    ex = IterativeDebuggingFullResponse.get_example_for_template()
    assert ex.thoughts == "Your thoughts"
    assert any( "def function_name_here" in line for line in ex.code )


# =========================================================================== #
# WeatherResponse
# =========================================================================== #
def test_weather_from_xml_temperature_and_forecast():
    temp = WeatherResponse.from_xml(
        "<response><rephrased-answer>It's 76 degrees in DC.</rephrased-answer></response>"
    )
    assert temp.is_temperature_response() is True
    assert temp.is_forecast_response() is False
    fc = WeatherResponse.from_xml(
        "<response><rephrased-answer>30% chance of rain today.</rephrased-answer></response>"
    )
    assert fc.is_temperature_response() is False
    assert fc.is_forecast_response() is True


def test_weather_validate_empty_raises():
    with pytest.raises( ValidationError, match="rephrased_answer cannot be empty" ):
        WeatherResponse( rephrased_answer="   " )


def test_weather_to_xml_hyphenated():
    xml = WeatherResponse( rephrased_answer="It is sunny" ).to_xml()
    assert "<rephrased-answer>It is sunny</rephrased-answer>" in xml


def test_weather_get_example_for_template():
    ex = WeatherResponse.get_example_for_template()
    assert ex.rephrased_answer.startswith( "[" )


# =========================================================================== #
# FormatterResponse  ( universal rephrased-answer model )
# =========================================================================== #
def test_formatter_from_xml_and_alias():
    r = FormatterResponse.from_xml(
        "<response><rephrased-answer>Two plus two is four.</rephrased-answer></response>"
    )
    assert r.rephrased_answer == "Two plus two is four."
    assert "rephrased_answer" in r.model_dump()


def test_formatter_strips_whitespace():
    assert FormatterResponse( rephrased_answer="  hi  " ).rephrased_answer == "hi"


def test_formatter_validate_empty_raises():
    with pytest.raises( ValidationError, match="rephrased_answer cannot be empty" ):
        FormatterResponse( rephrased_answer="   " )


# =========================================================================== #
# VoxCommandResponse
# =========================================================================== #
def test_vox_command_from_xml():
    r = VoxCommandResponse.from_xml(
        "<response><command>search google new tab</command><args>ml tutorials</args></response>"
    )
    assert r.command == "search google new tab"
    assert r.args == "ml tutorials"


def test_vox_command_validate_command_truthy_strips():
    # v truthy → v.strip() arc
    assert VoxCommandResponse( command="  open tab  " ).command == "open tab"


def test_vox_command_validate_command_empty_falsy():
    # v falsy ( "" ) → else "" arc
    assert VoxCommandResponse( command="" ).command == ""


def test_vox_command_default_args_empty():
    assert VoxCommandResponse( command="x" ).args == ""


def test_vox_command_get_example_for_template():
    ex = VoxCommandResponse.get_example_for_template()
    assert ex.command == "search google new tab"
    assert "tutorials" in ex.args


# =========================================================================== #
# AgentRouterResponse
# =========================================================================== #
def test_agent_router_from_xml():
    r = AgentRouterResponse.from_xml(
        "<response><command>agent router go to math</command><args>2+2</args></response>"
    )
    assert r.command == "agent router go to math"
    assert r.args == "2+2"


def test_agent_router_known_command_strips():
    # v in valid_commands ( if False arc ) → v.strip()
    assert AgentRouterResponse( command="  agent router go to weather  " ).command == "agent router go to weather"


def test_agent_router_unknown_command_allowed():
    # v NOT in valid_commands ( if True arc, pass ) → still returned
    assert AgentRouterResponse( command="agent router go to brand_new" ).command == "agent router go to brand_new"


def test_agent_router_empty_command_falsy():
    # v falsy → else "" arc
    assert AgentRouterResponse( command="" ).command == ""


def test_agent_router_get_example_for_template():
    ex = AgentRouterResponse.get_example_for_template()
    assert ex.command == "agent router go to math"
    assert "square root" in ex.args


# =========================================================================== #
# GistResponse
# =========================================================================== #
def test_gist_from_xml():
    r = GistResponse.from_xml( "<response><gist>Calculate the square root of 144</gist></response>" )
    assert r.gist == "Calculate the square root of 144"


def test_gist_validate_empty_raises():
    with pytest.raises( ValidationError, match="Gist cannot be empty" ):
        GistResponse( gist="   " )


def test_gist_strips_whitespace():
    assert GistResponse( gist="  summary  " ).gist == "summary"


def test_gist_get_example_for_template():
    ex = GistResponse.get_example_for_template()
    assert ex.gist == "Calculate the square root of 144"


# =========================================================================== #
# ConfirmationResponse
# =========================================================================== #
@pytest.mark.parametrize( "decision", [ "yes", "no", "ambiguous" ] )
def test_confirmation_valid_decisions( decision ):
    assert ConfirmationResponse( decision=decision ).decision == decision


def test_confirmation_invalid_decision_raises():
    # Literal[...] rejects out-of-set value ( Pydantic, before any validator )
    with pytest.raises( ValidationError ):
        ConfirmationResponse( decision="maybe" )


def test_confirmation_get_example_for_template():
    assert ConfirmationResponse.get_example_for_template().decision == "yes"


def test_confirmation_to_xml_appends_options_comment():
    xml = ConfirmationResponse( decision="yes" ).to_xml()
    assert "<decision>yes</decision>" in xml
    assert "Examples of valid responses" in xml
    assert "<response><decision>ambiguous</decision></response>" in xml


# =========================================================================== #
# QualifierClassification
# =========================================================================== #
def test_qualifier_from_xml_and_intent_helpers():
    r = QualifierClassification.from_xml(
        "<response><intent>question</intent><confidence>0.9</confidence>"
        "<reasoning>asking about results</reasoning></response>"
    )
    assert r.is_question() is True
    assert r.is_instruction() is False
    instr = QualifierClassification( intent="instruction", confidence="0.8", reasoning="do it" )
    assert instr.is_question() is False
    assert instr.is_instruction() is True


def test_qualifier_coerce_none_to_empty_str():
    # coerce_none_to_empty_str: None arc ( 2733-2734 ) AND non-None arc ( 2735 )
    r = QualifierClassification( intent="question", confidence=None, reasoning=None )
    assert r.confidence == ""
    assert r.reasoning == ""


def test_qualifier_defaults():
    r = QualifierClassification( intent="question" )
    assert r.confidence == "0.0"
    assert r.reasoning == ""


def test_qualifier_get_example_for_template():
    ex = QualifierClassification.get_example_for_template()
    assert ex.intent == "question"
    assert ex.confidence == "0.85"


# =========================================================================== #
# FuzzyFileMatchResponse
# =========================================================================== #
def test_fuzzy_file_match_from_xml():
    r = FuzzyFileMatchResponse.from_xml(
        "<response><matches>a.md, b.md, c.md</matches></response>"
    )
    assert r.matches == "a.md, b.md, c.md"


def test_fuzzy_file_match_get_matches_list_populated():
    # non-empty arc ( 2871 ): split + strip + filter empties
    r = FuzzyFileMatchResponse( matches="a.md, b.md , , c.md" )
    assert r.get_matches_list() == [ "a.md", "b.md", "c.md" ]


def test_fuzzy_file_match_get_matches_list_empty_and_whitespace():
    # empty/whitespace arc ( 2868-2869 ) → []
    assert FuzzyFileMatchResponse( matches="" ).get_matches_list() == []
    assert FuzzyFileMatchResponse( matches="   " ).get_matches_list() == []


def test_fuzzy_file_match_get_example_for_template():
    ex = FuzzyFileMatchResponse.get_example_for_template()
    assert "claude-code-analysis.md" in ex.matches


# =========================================================================== #
# TFEResumeMatchResponse
# =========================================================================== #
def test_tfe_resume_match_from_xml():
    r = TFEResumeMatchResponse.from_xml(
        "<response><matches>tfe-abc::u1, tfe-def::u1</matches></response>"
    )
    assert r.matches == "tfe-abc::u1, tfe-def::u1"


def test_tfe_resume_match_get_matches_list_populated():
    # non-empty arc ( 2990 )
    r = TFEResumeMatchResponse( matches="tfe-abc::u1, tfe-def::u1 , , tfe-xyz::u1" )
    assert r.get_matches_list() == [ "tfe-abc::u1", "tfe-def::u1", "tfe-xyz::u1" ]


def test_tfe_resume_match_get_matches_list_empty_and_whitespace():
    # empty/whitespace arc ( 2987-2988 ) → []
    assert TFEResumeMatchResponse( matches="" ).get_matches_list() == []
    assert TFEResumeMatchResponse( matches="   " ).get_matches_list() == []


def test_tfe_resume_match_get_example_for_template():
    ex = TFEResumeMatchResponse.get_example_for_template()
    assert "tfe-7c25082a" in ex.matches
