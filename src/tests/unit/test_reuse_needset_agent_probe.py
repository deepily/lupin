"""
The tools-on probe: its prompt, its options, its reading of a stream and its rulings.

The streams here are built in the test from the SDK's own message classes. The captured stream of one real run replaces them in the 10 a.m. window.
"""
import asyncio

import pytest
from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock, ToolUseBlock

from cosa.repo.doc_lint import model_transport as mt
from lupin_mcp.reuse_needset import agent_probe as ap
from lupin_mcp.reuse_needset import errors as er

SHORTLIST = [ { "id": "pkg.a.f", "file": "pkg/a.py", "p": 0.9, "text": "SECRET SUMMARY" }, { "id": "pkg.b.g", "file": "pkg/b.py", "p": 0.4, "text": "OTHER SUMMARY" } ]
RESULT    = { "shortlist": SHORTLIST, "verdict": "REUSE" }
GOOD      = "RULING pkg.a.f :: DUPLICATE\nRULING pkg.b.g :: DISTINCT it does another job"


def assistant( *blocks ): return AssistantMessage( content=list( blocks ), model="m" )


def done( error=False ): return ResultMessage( subtype="success", duration_ms=1, duration_api_ms=1, is_error=error, num_turns=1, session_id="s", result="r" if error else None )


def read( path, **given ): return ToolUseBlock( id="t", name="Read", input={ "file_path": path, **given } )


def stream_of( *messages_per_call ):
    """Return a query function that plays one list of messages per call and counts the calls."""
    calls = []

    async def query( prompt, options ):
        calls.append( ( prompt, options ) )
        for m in messages_per_call[ len( calls ) - 1 ]: yield m

    query.calls = calls
    return query


def test_the_prompt_names_the_need_and_each_candidate_without_its_summary_text():
    prompt = ap.build_prompt( "Add up numbers.", RESULT )
    assert "Need: Add up numbers." in prompt and '"id": "pkg.a.f"' in prompt and '"id": "pkg.b.g"' in prompt and '"file": "pkg/a.py"' in prompt
    assert "SECRET SUMMARY" not in prompt and "OTHER SUMMARY" not in prompt and "REUSE" not in prompt
    assert prompt.startswith( ap.INSTRUCTION )
    assert prompt.splitlines()[ -2: ] == [ '{"file": "pkg/a.py", "id": "pkg.a.f", "p": 0.9}', '{"file": "pkg/b.py", "id": "pkg.b.g", "p": 0.4}' ]


@pytest.mark.parametrize( "reply, expected", [
    ( GOOD, { "pkg.a.f": "DUPLICATE", "pkg.b.g": "DISTINCT" } ),
    ( "Here you go.\nRULING x.y :: EXTEND\n  RULING z :: DUPLICATE  \nRULING w : DUPLICATE", { "x.y": "EXTEND", "z": "DUPLICATE" } ),
    ( "RULING a :: DUPLICATE\nRULING a :: DUPLICATE", { "a": "DUPLICATE" } ),
    ( "RULING a :: DUPLICATE\nRULING a :: DISTINCT", {} ),
    ( "RULING a :: MAYBE", {} ), ( "", {} ), ( None, {} ) ] )
def test_the_rulings_are_read_one_per_line_and_a_contradiction_reads_as_unruled( reply, expected ):
    assert ap.rulings( reply ) == expected


def test_read_files_collects_only_the_read_calls_of_assistant_messages_in_order():
    transcript = [ assistant( TextBlock( text="looking" ), read( "/t/pkg/a.py" ) ), assistant( ToolUseBlock( id="u", name="Grep", input={ "pattern": "x" } ), read( "/t/pkg/b.py", offset=10, limit=5 ) ), done() ]
    assert ap.read_files( transcript ) == [ { "path": "/t/pkg/a.py", "offset": None, "limit": None }, { "path": "/t/pkg/b.py", "offset": 10, "limit": 5 } ]
    assert ap.read_files( [ done() ] ) == []


def test_serialize_keeps_text_and_tool_calls_in_order_and_reply_text_is_the_last_text_message():
    transcript = [ assistant( TextBlock( text="first" ), read( "/t/a.py" ) ), assistant( read( "/t/b.py" ) ), assistant( TextBlock( text="last " ), TextBlock( text="words" ) ), done() ]
    assert ap.serialize( transcript ) == [ { "type": "text", "text": "first" }, { "type": "tool_use", "name": "Read", "input": { "file_path": "/t/a.py" } },
                                           { "type": "tool_use", "name": "Read", "input": { "file_path": "/t/b.py" } }, { "type": "text", "text": "last " }, { "type": "text", "text": "words" } ]
    assert ap.reply_text( transcript ) == "last words" and ap.reply_text( [ done() ] ) == ""


@pytest.mark.parametrize( "offset, limit, expected", [
    ( None, None, True ), ( 1, None, True ), ( 10, None, True ), ( 11, None, False ), ( None, 20, True ), ( None, 19, False ), ( 10, 11, True ), ( 10, 10, False ), ( 5, 100, True ), ( 11, 100, False ) ] )
def test_a_read_covers_a_definition_only_when_its_range_holds_every_line( offset, limit, expected ):
    call = { "path": "/t/pkg/a.py", "offset": offset, "limit": limit }
    assert ap.covers( call, "/t", "pkg/a.py", 10, 20 ) is expected


def test_a_read_of_another_file_or_a_relative_path_is_judged_by_the_file_it_names():
    assert ap.covers( { "path": "/t/pkg/b.py", "offset": None, "limit": None }, "/t", "pkg/a.py", 1, 2 ) is False
    assert ap.covers( { "path": "pkg/a.py", "offset": None, "limit": None }, "/t", "pkg/a.py", 1, 2 ) is True
    assert ap.covers( { "path": "/t/./pkg/../pkg/a.py", "offset": None, "limit": None }, "/t", "pkg/a.py", 1, 2 ) is True


def test_the_options_hold_the_read_tool_only_and_the_isolation_the_transport_gives_every_call():
    options = ap.probe_options( "/t", "claude-opus-5-5" )
    assert options.tools == [ "Read" ] and options.setting_sources == [] and options.extra_args == dict( mt.ISOLATION_ARGS ) and options.cwd == "/t"
    assert options.permission_mode == mt.PERMISSION_MODE and options.max_turns == ap.MAX_TURNS and options.model == "claude-opus-5-5" and options.cli_path == mt.CLI_PATH
    assert options.system_prompt == ap.SYSTEM and "strict-mcp-config" in options.extra_args and "disable-slash-commands" in options.extra_args


def test_the_prompt_version_changes_with_the_instruction_the_tools_and_the_turn_limit( monkeypatch ):
    base = ap.prompt_version()
    assert base.startswith( "needset-probe-" ) and ap.prompt_version() == base
    for name, value in ( ( "INSTRUCTION", ap.INSTRUCTION + "!" ), ( "SYSTEM", ap.SYSTEM + "!" ), ( "TOOLS", [ "Read", "Grep" ] ), ( "MAX_TURNS", ap.MAX_TURNS + 1 ) ):
        with monkeypatch.context() as m:
            m.setattr( ap, name, value )
            assert ap.prompt_version() != base, name


def test_a_readable_reply_returns_the_rulings_the_reads_and_the_transcript():
    query = stream_of( [ assistant( read( "/t/pkg/a.py" ) ), assistant( TextBlock( text=GOOD ) ), done() ] )
    out   = asyncio.run( ap.run_probe( "Add up numbers.", RESULT, "/t", "claude-opus-5-5", query_fn=query ) )
    assert out[ "rulings" ] == { "pkg.a.f": "DUPLICATE", "pkg.b.g": "DISTINCT" } and out[ "reply" ] == GOOD
    assert out[ "reads" ] == [ { "path": "/t/pkg/a.py", "offset": None, "limit": None } ] and out[ "transcript" ][ 0 ][ "type" ] == "tool_use" and len( query.calls ) == 1
    assert query.calls[ 0 ][ 0 ] == ap.build_prompt( "Add up numbers.", RESULT ) and query.calls[ 0 ][ 1 ].tools == [ "Read" ]


def test_an_unreadable_reply_is_asked_once_more_with_the_same_prompt_and_then_refused():
    query = stream_of( [ assistant( TextBlock( text="no idea" ) ), done() ], [ assistant( TextBlock( text=GOOD ) ), done() ] )
    out   = asyncio.run( ap.run_probe( "n", RESULT, "/t", "m", query_fn=query ) )
    assert out[ "rulings" ] and len( query.calls ) == 2 and query.calls[ 0 ][ 0 ] == query.calls[ 1 ][ 0 ]
    query = stream_of( [ assistant( TextBlock( text="no" ) ), done() ], [ done() ] )
    with pytest.raises( er.NeedsetError ) as e: asyncio.run( ap.run_probe( "n", RESULT, "/t", "m", query_fn=query ) )
    assert e.value.code == er.PROBE_UNREADABLE and "'n'" in e.value.detail and len( query.calls ) == 2


def test_an_error_result_and_a_stream_with_no_result_raise_runtime_errors():
    with pytest.raises( RuntimeError ): asyncio.run( ap.run_probe( "n", RESULT, "/t", "m", query_fn=stream_of( [ done( error=True ) ] ) ) )
    with pytest.raises( RuntimeError, match="no result message" ): asyncio.run( ap.run_probe( "n", RESULT, "/t", "m", query_fn=stream_of( [ assistant( TextBlock( text=GOOD ) ) ] ) ) )
