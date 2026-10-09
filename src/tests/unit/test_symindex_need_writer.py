#!/usr/bin/env python3
"""
Unit tests for cosa.repo.symindex.need_writer: one bounded call per member, tools off.

The model call is faked at two levels. A plain async reply function covers the retry logic.
A fake sdk_query yielding real SDK message objects covers the one real wrapper.
"""

import asyncio
import hashlib
import json

import pytest
from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock

import cosa.utils.util as cu
from cosa.repo.doc_lint import model_transport as mt
from cosa.repo.symindex import need_input as ni
from cosa.repo.symindex import need_writer as nw


GOOD  = "A function that reads a block of text and returns the parsed record as a dictionary."
MODULE_SOURCE = '''def parse_result_block( raw_text, strict=False ):
    """Parse raw_text into a dict."""
    return {}


class BlockReader:
    """Reads blocks."""

    def read_block( self, limit ):
        """Read limit lines."""
        return []
'''


@pytest.fixture
def src_root( tmp_path ):
    """A src root holding pk/mod.py."""
    pkg = tmp_path / "pk"
    pkg.mkdir()
    ( pkg / "__init__.py" ).write_text( "" )
    ( pkg / "mod.py" ).write_text( MODULE_SOURCE )
    return str( tmp_path )


def _reply( text, session="job-1", cost=0.5, tokens_in=100, tokens_out=20 ):
    return nw.Reply( text=text, session_id=session, cost_usd=cost, input_tokens=tokens_in, output_tokens=tokens_out )


class FakeQuery:
    """Async reply function that returns scripted replies and records every prompt."""

    def __init__( self, texts ):
        self.texts   = list( texts )
        self.prompts = []

    async def __call__( self, prompt, system_prompt ):
        self.prompts.append( prompt )
        return _reply( self.texts.pop( 0 ), session=f"job-{len( self.prompts )}" )


def _input( src_root, member="pk.mod.parse_result_block" ):
    return ni.build_input( member, src_root )


# --- extract_sentence -------------------------------------------------------

def test_extract_sentence_strips_quotes_ticks_and_whitespace():
    assert nw.extract_sentence( '  "A function that  does\n a thing."  ' ) == "A function that does a thing."
    assert nw.extract_sentence( "`A class that holds data.`" ) == "A class that holds data."


# --- check_form -------------------------------------------------------------

def test_good_sentence_passes( src_root ):
    assert nw.check_form( GOOD, _input( src_root ) ) == []


def test_opener_must_match_kind( src_root ):
    assert "opener" in nw.check_form( GOOD.replace( "function", "method" ), _input( src_root ) )
    assert nw.check_form( GOOD.replace( "function", "method" ), _input( src_root, "pk.mod.BlockReader.read_block" ) ) == []
    assert nw.check_form( GOOD.replace( "function", "class" ), _input( src_root, "pk.mod.BlockReader" ) ) == []


def test_word_count_bounds( src_root ):
    short = "A function that returns nothing."
    long  = "A function that " + " ".join( ["word"] * 40 ) + "."
    edge8 = "A function that does one small job ok."
    edge40 = "A function that " + " ".join( ["word"] * 36 ) + " end."
    assert nw.check_form( short, _input( src_root ) ) == [ "word_count" ]
    assert nw.check_form( long, _input( src_root ) )  == [ "word_count" ]
    assert len( edge8.split() ) == 8 and nw.check_form( edge8, _input( src_root ) ) == []
    assert len( edge40.split() ) == 40 and nw.check_form( edge40, _input( src_root ) ) == []


def test_more_than_one_sentence_fails( src_root ):
    two = GOOD + " It also logs the result for later review."
    assert "one_sentence" in nw.check_form( two, _input( src_root ) )
    assert "one_sentence" in nw.check_form( GOOD[ :-1 ], _input( src_root ) )


def test_placeholder_left_in_sentence_fails( src_root ):
    for token in ( "NAME", "CLASS", "MODULE", "ARG2", "ATTR1" ):
        assert "placeholder" in nw.check_form( GOOD.replace( "block", token ), _input( src_root ) ), token


def test_own_identifier_fails( src_root ):
    assert "own_identifier" in nw.check_form( GOOD.replace( "text", "raw_text" ), _input( src_root ) )
    assert "own_identifier" in nw.check_form( GOOD.replace( "block", "mod" ), _input( src_root ) )


def test_check_form_reports_every_failure_kind_once( src_root ):
    kinds = nw.check_form( "Reads raw_text NAME.", _input( src_root ) )
    assert kinds == sorted( set( kinds ) ) and set( kinds ) >= { "opener", "word_count", "placeholder", "own_identifier" }


# --- opener words ---------------------------------------------------------

def test_opener_words_do_not_count_as_a_member_name( tmp_path ):
    pkg = tmp_path / "pk"
    pkg.mkdir()
    ( pkg / "__init__.py" ).write_text( "" )
    ( pkg / "m.py" ).write_text( "def run( function, other ):\n    return function( other )\n" )
    need = ni.build_input( "pk.m.run", str( tmp_path ) )
    assert "function" in need.forbidden
    ok = "A function that calls the callable it is given on the second value and returns whatever that call returns."
    assert nw.check_form( ok, need ) == []
    assert nw.check_form( ok.replace( "second value", "function value" ), need ) == [ "own_identifier" ]


def test_prompt_allows_the_opener_and_bans_the_kind_words_elsewhere( src_root ):
    method_prompt = nw.build_prompt( _input( src_root, "pk.mod.BlockReader.read_block" ) )
    assert 'begins "A method that "' in method_prompt
    assert "function, class, method" in method_prompt
    assert 'begins "A function that "' in nw.build_prompt( _input( src_root ) )


# --- assemble ---------------------------------------------------------------

def test_needs_document_has_rios_format_and_the_sample_order( src_root, tmp_path ):
    out = tmp_path / "run"
    ids = [ "pk.mod.parse_result_block", "pk.mod.BlockReader" ]
    asyncio.run( nw.run_members( ids, src_root, str( out ), FakeQuery( [ GOOD, GOOD.replace( "function", "class" ) ] ) ) )
    document = nw.needs_document( str( out ), ids, "abc123" )
    assert document[ "format" ] == "reuse-e2e-needs-1" and document[ "sample_sha256" ] == "abc123"
    assert [ n[ "member" ] for n in document[ "needs" ] ] == ids
    assert document[ "needs" ][ 0 ][ "need" ] == GOOD and document[ "needs" ][ 0 ][ "writer_job_id" ] == "job-1"


def test_needs_document_refuses_a_missing_or_failed_member( src_root, tmp_path ):
    out = tmp_path / "run"
    asyncio.run( nw.run_members( [ "pk.mod.parse_result_block" ], src_root, str( out ), FakeQuery( [ "bad.", "bad.", "bad." ] ) ) )
    with pytest.raises( ValueError, match="no accepted need" ):
        nw.needs_document( str( out ), [ "pk.mod.parse_result_block" ], "x" )
    with pytest.raises( ValueError, match="no file" ):
        nw.needs_document( str( tmp_path / "empty-run" ), [ "pk.mod.parse_result_block" ], "x" )


def test_main_assemble_writes_the_document( src_root, tmp_path ):
    out = tmp_path / "out"
    base = [ "--sample", _sample_file( tmp_path ), "--src-root", src_root, "--out", str( out ) ]
    nw.main( base, reply_fn=FakeQuery( [ GOOD, GOOD.replace( "function", "class" ) ] ) )
    target = tmp_path / "needs.json"
    assert nw.main( base + [ "--assemble", str( target ) ] ) == 0
    document = json.loads( target.read_text() )
    assert len( document[ "needs" ] ) == 2 and len( document[ "sample_sha256" ] ) == 64


def test_main_assemble_records_the_sha256_of_the_sample_file_bytes( src_root, tmp_path ):
    out    = tmp_path / "out"
    sample = _sample_file( tmp_path )
    base   = [ "--sample", sample, "--src-root", src_root, "--out", str( out ) ]
    nw.main( base, reply_fn=FakeQuery( [ GOOD, GOOD.replace( "function", "class" ) ] ) )
    target = tmp_path / "needs.json"
    nw.main( base + [ "--assemble", str( target ) ] )
    expected = hashlib.sha256( open( sample, "rb" ).read() ).hexdigest()
    assert json.loads( target.read_text() )[ "sample_sha256" ] == expected
    assert expected != hashlib.sha256( b"" ).hexdigest()


# --- build_prompt -----------------------------------------------------------

def test_prompt_holds_stripped_text_and_rules( src_root ):
    need   = _input( src_root )
    prompt = nw.build_prompt( need )
    assert need.text in prompt
    assert "A function that" in prompt and "8 to 40 words" in prompt
    assert "parse_result_block" not in prompt


def test_prompt_warns_off_plain_input_words_without_naming_this_members_names( src_root ):
    prompt = nw.build_prompt( _input( src_root ) )
    assert "text, data, value" in prompt
    assert "raw_text" not in prompt and "strict" not in prompt


def test_retry_hint_for_own_identifier_says_a_plain_word_may_be_a_name( src_root ):
    hinted = nw.build_prompt( _input( src_root ), failures=[ "own_identifier" ] )
    assert "plain everyday word" in hinted
    assert "limit, error, state, job" in hinted
    assert "plain everyday word" not in nw.build_prompt( _input( src_root ), failures=[ "opener" ] )


def test_retry_prompt_names_kind_of_failure_only( src_root ):
    prompt = nw.build_prompt( _input( src_root ), failures=[ "own_identifier" ] )
    assert "own_identifier" in prompt
    assert "raw_text" not in prompt.split( "rejected" )[ 1 ]


# --- naming the member's own offending word -------------------------------

def test_own_words_found_lists_only_the_members_own_names( src_root ):
    need = _input( src_root )
    sentence = "A function that reads raw_text with strict care and returns an extraneous mapping."
    assert nw.own_words_found( sentence, need ) == [ "raw_text", "strict" ]
    assert set( nw.own_words_found( sentence, need ) ) <= set( need.forbidden )


def test_own_words_found_skips_the_opening_phrase( tmp_path ):
    pkg = tmp_path / "pk"
    pkg.mkdir()
    ( pkg / "__init__.py" ).write_text( "" )
    ( pkg / "m.py" ).write_text( "def run( function ):\n    return function()\n" )
    need = ni.build_input( "pk.m.run", str( tmp_path ) )
    assert nw.own_words_found( "A function that calls it.", need ) == []


def test_prompt_names_the_offending_own_word_and_nothing_else( src_root ):
    need   = _input( src_root )
    prompt = nw.build_prompt( need, failures=[ "own_identifier" ], own_words=[ "raw_text" ] )
    assert 'the word "raw_text"' in prompt
    assert '"strict"' not in prompt and "extraneous" not in prompt


def test_prompt_refuses_a_word_that_is_not_in_the_members_own_names( src_root ):
    with pytest.raises( ValueError, match="not one of the member's own names" ):
        nw.build_prompt( _input( src_root ), failures=[ "own_identifier" ], own_words=[ "somebody_elses_name" ] )


def test_write_need_names_the_own_word_on_retry_but_not_a_foreign_word( src_root ):
    fake = FakeQuery( [ "A function that reads raw_text and returns a quux mapping of the parsed record into a dictionary object.", GOOD ] )
    asyncio.run( nw.write_need( _input( src_root ), fake ) )
    assert 'the word "raw_text"' in fake.prompts[ 1 ]
    assert "quux" not in fake.prompts[ 1 ]


def test_a_redo_prompt_carries_no_word_until_the_writer_has_used_one( src_root ):
    fake = FakeQuery( [ GOOD ] )
    asyncio.run( nw.write_need( _input( src_root ), fake, failures=[ "own_identifier" ] ) )
    assert 'the word "' not in fake.prompts[ 0 ]


# --- word count on retry ---------------------------------------------------

def test_retry_after_word_count_says_how_many_words_the_last_sentence_had( src_root ):
    long = "A function that " + " ".join( ["word"] * 45 ) + "."
    fake = FakeQuery( [ long, GOOD ] )
    asyncio.run( nw.write_need( _input( src_root ), fake ) )
    assert "had 49 words" in fake.prompts[ 1 ] and "8 to 40" in fake.prompts[ 1 ]


def test_retry_for_another_kind_carries_no_word_count( src_root ):
    fake = FakeQuery( [ "Reads things quickly in a single pass over everything it is given here.", GOOD ] )
    asyncio.run( nw.write_need( _input( src_root ), fake ) )
    assert " words" not in fake.prompts[ 1 ].split( "rejected" )[ 1 ]


# --- write_need -------------------------------------------------------------

def test_write_need_accepts_first_good_reply( src_root ):
    fake   = FakeQuery( [ GOOD ] )
    record = asyncio.run( nw.write_need( _input( src_root ), fake ) )
    assert record[ "ok" ] is True and record[ "need" ] == GOOD
    assert record[ "job_id" ] == "job-1" and len( record[ "attempts" ] ) == 1
    assert record[ "member_id" ] == "pk.mod.parse_result_block"
    assert len( fake.prompts ) == 1


def test_write_need_retries_after_a_bad_form( src_root ):
    fake   = FakeQuery( [ "Reads things.", GOOD ] )
    record = asyncio.run( nw.write_need( _input( src_root ), fake ) )
    assert record[ "ok" ] is True and len( record[ "attempts" ] ) == 2
    assert record[ "attempts" ][ 0 ][ "failures" ] == [ "opener", "word_count" ]
    assert record[ "job_id" ] == "job-2"
    assert "word_count" in fake.prompts[ 1 ]


def test_write_need_gives_up_after_max_attempts( src_root ):
    fake   = FakeQuery( [ "bad one.", "bad two.", "bad three." ] )
    record = asyncio.run( nw.write_need( _input( src_root ), fake, max_attempts=3 ) )
    assert record[ "ok" ] is False and record[ "need" ] is None and len( record[ "attempts" ] ) == 3
    assert record[ "job_id" ] is None


def test_write_need_retries_after_a_failed_call( src_root ):
    calls = []

    async def flaky( prompt, system_prompt ):
        calls.append( prompt )
        if len( calls ) == 1: raise RuntimeError( "error_max_turns" )
        return _reply( GOOD )

    record = asyncio.run( nw.write_need( _input( src_root ), flaky ) )
    assert record[ "ok" ] is True and len( record[ "attempts" ] ) == 2
    assert record[ "attempts" ][ 0 ][ "failures" ] == [ "call_error" ] and record[ "attempts" ][ 0 ][ "session_id" ] is None
    assert "call_error" not in calls[ 1 ]


def test_write_need_totals_cost_and_tokens( src_root ):
    record = asyncio.run( nw.write_need( _input( src_root ), FakeQuery( [ "bad.", GOOD ] ) ) )
    assert record[ "cost_usd" ] == 1.0 and record[ "input_tokens" ] == 200 and record[ "output_tokens" ] == 40


def test_write_need_passes_checker_failure_kinds_into_the_first_prompt( src_root ):
    fake = FakeQuery( [ GOOD ] )
    asyncio.run( nw.write_need( _input( src_root ), fake, failures=[ "four_word_run" ] ) )
    assert "four_word_run" in fake.prompts[ 0 ]


# --- run_members ------------------------------------------------------------

def test_run_members_writes_one_file_per_member_and_resumes( src_root, tmp_path ):
    out    = tmp_path / "run"
    ids    = [ "pk.mod.parse_result_block", "pk.mod.BlockReader" ]
    fake   = FakeQuery( [ GOOD, GOOD.replace( "function", "class" ) ] )
    records = asyncio.run( nw.run_members( ids, src_root, str( out ), fake ) )
    assert [ r[ "member_id" ] for r in records ] == ids and len( list( out.glob( "*.json" ) ) ) == 2
    again = FakeQuery( [] )
    records = asyncio.run( nw.run_members( ids, src_root, str( out ), again ) )
    assert again.prompts == [] and all( r[ "ok" ] for r in records )


def test_run_members_redo_replaces_only_named_members( src_root, tmp_path ):
    out  = tmp_path / "run"
    ids  = [ "pk.mod.parse_result_block", "pk.mod.BlockReader" ]
    asyncio.run( nw.run_members( ids, src_root, str( out ), FakeQuery( [ GOOD, GOOD.replace( "function", "class" ) ] ) ) )
    redo = FakeQuery( [ GOOD.replace( "returns", "gives back" ) ] )
    records = asyncio.run( nw.run_members( ids, src_root, str( out ), redo, redo={ "pk.mod.parse_result_block": [ "own_identifier" ] } ) )
    assert len( redo.prompts ) == 1 and "own_identifier" in redo.prompts[ 0 ]
    assert "gives back" in records[ 0 ][ "need" ] and records[ 1 ][ "need" ].startswith( "A class" )
    assert [ r[ "rewrites" ] for r in records ] == [ 1, 0 ]


def test_run_members_rejects_duplicate_ids( src_root, tmp_path ):
    with pytest.raises( ValueError, match="duplicate" ):
        asyncio.run( nw.run_members( [ "pk.mod.parse_result_block" ] * 2, src_root, str( tmp_path ), FakeQuery( [] ) ) )


# --- the real wrapper, over a fake sdk_query ---------------------------------

def _fake_sdk( messages, seen ):
    async def fake( prompt, options ):
        seen.append( options )
        for message in messages: yield message
    return fake


def test_sdk_reply_runs_with_tools_off_and_reads_the_result( monkeypatch ):
    seen     = []
    messages = [
        object(),
        AssistantMessage( content=[ TextBlock( text="A function that " ), TextBlock( text="does it." ) ], model="m" ),
        ResultMessage( subtype="success", duration_ms=1, duration_api_ms=1, is_error=False, num_turns=1, session_id="sess-9",
                       total_cost_usd=0.25, usage={ "input_tokens": 7, "output_tokens": 3 } ),
    ]
    monkeypatch.setattr( nw, "sdk_query", _fake_sdk( messages, seen ) )
    reply = asyncio.run( nw.sdk_reply( "p", "s" ) )
    assert reply == nw.Reply( text="A function that does it.", session_id="sess-9", cost_usd=0.25, input_tokens=7, output_tokens=3 )
    assert seen[ 0 ].tools == [] and seen[ 0 ].permission_mode == "default" and seen[ 0 ].system_prompt == "s"
    assert seen[ 0 ].max_turns == 3


def test_sdk_reply_options_are_the_hermetic_profile_of_the_model_transport( monkeypatch ):
    seen     = []
    messages = [ ResultMessage( subtype="success", duration_ms=1, duration_api_ms=1, is_error=False, num_turns=1, session_id="s" ) ]
    monkeypatch.setattr( nw, "sdk_query", _fake_sdk( messages, seen ) )
    asyncio.run( nw.sdk_reply( "p", "s" ) )
    options = seen[ 0 ]
    settings = json.loads( options.extra_args[ "settings" ] )
    assert options.setting_sources == [] and options.tools == []
    assert settings[ "disableAllHooks" ] is True and settings[ "autoMemoryEnabled" ] is False
    assert any( pattern.endswith( "CLAUDE.md" ) for pattern in settings[ "claudeMdExcludes" ] )
    assert "strict-mcp-config" in options.extra_args and "disable-slash-commands" in options.extra_args
    assert options.extra_args == mt.ISOLATION_ARGS and options.cwd == cu.get_project_root()
    assert options.permission_mode == mt.PERMISSION_MODE


def test_sdk_reply_raises_when_the_stream_has_no_result( monkeypatch ):
    monkeypatch.setattr( nw, "sdk_query", _fake_sdk( [ AssistantMessage( content=[ TextBlock( text="x" ) ], model="m" ) ], [] ) )
    with pytest.raises( RuntimeError, match="no result message" ):
        asyncio.run( nw.sdk_reply( "p", "s" ) )


def test_write_need_counts_a_stream_with_no_result_as_a_failed_call( src_root, monkeypatch ):
    streams = [ [ AssistantMessage( content=[ TextBlock( text="x" ) ], model="m" ) ],
                [ AssistantMessage( content=[ TextBlock( text=GOOD ) ], model="m" ),
                  ResultMessage( subtype="success", duration_ms=1, duration_api_ms=1, is_error=False, num_turns=1, session_id="ok" ) ] ]

    async def fake( prompt, options ):
        for message in streams.pop( 0 ): yield message

    monkeypatch.setattr( nw, "sdk_query", fake )
    record = asyncio.run( nw.write_need( _input( src_root ), nw.sdk_reply ) )
    assert record[ "ok" ] is True and record[ "attempts" ][ 0 ][ "failures" ] == [ "call_error" ]


def test_sdk_reply_raises_on_an_error_result( monkeypatch ):
    messages = [ ResultMessage( subtype="error_max_turns", duration_ms=1, duration_api_ms=1, is_error=True, num_turns=1,
                                session_id="s", result="out of turns" ) ]
    monkeypatch.setattr( nw, "sdk_query", _fake_sdk( messages, [] ) )
    with pytest.raises( RuntimeError, match="out of turns" ):
        asyncio.run( nw.sdk_reply( "p", "s" ) )


def test_sdk_reply_defaults_missing_usage_and_cost( monkeypatch ):
    messages = [ ResultMessage( subtype="success", duration_ms=1, duration_api_ms=1, is_error=False, num_turns=1, session_id="s2" ) ]
    monkeypatch.setattr( nw, "sdk_query", _fake_sdk( messages, [] ) )
    reply = asyncio.run( nw.sdk_reply( "p", "s" ) )
    assert reply.cost_usd == 0.0 and reply.input_tokens == 0 and reply.output_tokens == 0 and reply.text == ""


# --- main -------------------------------------------------------------------

def _sample_file( tmp_path, near=None ):
    path = tmp_path / "sample.json"
    path.write_text( json.dumps( { "strata": {
        "has_exact_cluster": { "members": [ "pk.mod.parse_result_block" ] },
        "near_only"        : { "members": near if near is not None else [ "pk.mod.BlockReader" ] } } } ) )
    return str( path )


def test_sample_members_reads_both_strata_in_file_order( tmp_path ):
    assert nw.sample_members( _sample_file( tmp_path ) ) == [ "pk.mod.parse_result_block", "pk.mod.BlockReader" ]


def _empty_sample( tmp_path ):
    path = tmp_path / "empty.json"
    path.write_text( json.dumps( { "strata": { "has_exact_cluster": { "members": [] }, "near_only": { "members": [] } } } ) )
    return str( path )


def test_sample_members_refuses_an_empty_sample( tmp_path ):
    with pytest.raises( ValueError, match="no members" ):
        nw.sample_members( _empty_sample( tmp_path ) )


def test_main_runs_the_sample_with_the_injected_reply( src_root, tmp_path, monkeypatch ):
    out = tmp_path / "out"
    code = nw.main( [ "--sample", _sample_file( tmp_path ), "--src-root", src_root, "--out", str( out ) ],
                    reply_fn=FakeQuery( [ GOOD, GOOD.replace( "function", "class" ) ] ) )
    assert code == 0 and len( list( out.glob( "*.json" ) ) ) == 2


def test_main_returns_one_when_any_member_failed( src_root, tmp_path ):
    out = tmp_path / "out"
    code = nw.main( [ "--sample", _sample_file( tmp_path ), "--src-root", src_root, "--out", str( out ), "--max-attempts", "1" ],
                    reply_fn=FakeQuery( [ "bad.", GOOD.replace( "function", "class" ) ] ) )
    assert code == 1


def test_main_limit_and_redo_file( src_root, tmp_path ):
    out  = tmp_path / "out"
    base = [ "--sample", _sample_file( tmp_path ), "--src-root", src_root, "--out", str( out ) ]
    assert nw.main( base + [ "--limit", "1" ], reply_fn=FakeQuery( [ GOOD ] ) ) == 0
    assert len( list( out.glob( "*.json" ) ) ) == 1
    redo_path = tmp_path / "resend.json"
    redo_path.write_text( json.dumps( [ { "member": "pk.mod.parse_result_block", "check": "four_word_run" } ] ) )
    fake = FakeQuery( [ GOOD.replace( "returns", "gives back" ) ] )
    assert nw.main( base + [ "--limit", "1", "--redo-file", str( redo_path ) ], reply_fn=fake ) == 0
    assert "four_word_run" in fake.prompts[ 0 ]


def test_main_defaults_to_the_real_sdk_reply( src_root, tmp_path, monkeypatch ):
    messages = [ AssistantMessage( content=[ TextBlock( text=GOOD ) ], model="m" ),
                 ResultMessage( subtype="success", duration_ms=1, duration_api_ms=1, is_error=False, num_turns=1, session_id="x" ) ]
    monkeypatch.setattr( nw, "sdk_query", _fake_sdk( messages, [] ) )
    code = nw.main( [ "--sample", _sample_file( tmp_path ), "--src-root", src_root, "--out", str( tmp_path / "o" ), "--limit", "1" ] )
    assert code == 0
