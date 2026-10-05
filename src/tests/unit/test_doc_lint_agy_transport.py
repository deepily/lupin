"""
The agy path of the judge harness: model_transport after configure_agy, and harness_cli --transport agy.

Isolation contract:
    - No real agy and no model: every call goes through `FakeAgy`, a stand-in for subprocess.run,
      except two tests that start a shell script written under tmp_path.
    - The binary that is fingerprinted is a file under tmp_path, never the installed agy.
    - Every test ends with the transport back on Claude, no budget and an empty token tally.
"""

import asyncio
import json
import os
import re
import shutil
import stat
import time
import types

import pytest

from cosa.orchestration.agy import runtime as agy_runtime
from cosa.repo.doc_lint import claim_extractor as ce
from cosa.repo.doc_lint import claim_judge as cj
from cosa.repo.doc_lint import harness_cli as cli
from cosa.repo.doc_lint import harness_runner as hn
from cosa.repo.doc_lint import model_transport as mt


L1  = "Returns None when the row is parked."
L2  = "Raises ValueError if the id is blank."
L3  = "The window is ten minutes long."
OLD = "\n".join( [ L1, L2, L3 ] )

# The call profile written out, hash included, so a change to the agent text has to change this line too.
PROFILE    = "agy-print-2|new-project|disable-slash-commands|stream-json|scratch-cwd|no-edit-grant|agent=lupin-text-only-d7c8834864"
AGENT_TEXT = (
    "---\n"
    "name: lupin-text-only\n"
    "description: Answers from the text of the prompt only. Has no tools.\n"
    "tools: []\n"
    "---\n"
    "You answer from the text you are given and nothing else. You have no tools.\n"
)

USAGE = { "input_tokens" : 100, "output_tokens" : 7, "thinking_tokens" : 3, "cache_read_tokens" : 50, "total_tokens" : 110 }


def tagged( prompt, tag ):
    match = re.search( rf"<{tag}_(\w+)>\n(.*?)\n</{tag}_\1>", prompt, re.DOTALL )
    return match.group( 2 ) if match else ""


class Done:
    """Stand-in for subprocess.CompletedProcess."""
    def __init__( self, returncode=0, stdout="", stderr="" ):
        self.returncode = returncode
        self.stdout     = stdout
        self.stderr     = stderr


class FakeAgy:
    """
    Stand-in for subprocess.run that answers as agy would: a version, or one result event.

    It plays the extractor and the judge by reading the joined prompt, as the harness test's
    FakeModel does for Claude, and records every model call it receives.
    """

    def __init__( self, version="1.2.17", answer=None, result_overrides=None, exit_code=0, usage=USAGE, on_call=None ):
        self.version          = version
        self.answer           = answer
        self.result_overrides = result_overrides or {}
        self.exit_code        = exit_code
        self.usage            = usage
        self.on_call          = on_call
        self.calls            = []

    def __call__( self, argv, **kwargs ):
        if argv[ 1: ] == [ "--version" ]: return Done( stdout=self.version + "\n" )
        prompt = json.loads( kwargs[ "input" ] )[ "message" ][ "content" ]
        model  = argv[ argv.index( "--model" ) + 1 ]
        cwd     = kwargs[ "cwd" ]
        listing = sorted( os.path.relpath( os.path.join( folder, name ), cwd ) for folder, _, names in os.walk( cwd ) for name in names )
        agent   = open( os.path.join( cwd, mt.AGY_AGENT_PATH ), encoding="utf-8" ).read() if mt.AGY_AGENT_PATH in listing else None
        self.calls.append( { "model" : model, "prompt" : prompt, "cwd" : cwd, "cwd_listing" : listing, "agent_text" : agent, "argv" : argv } )
        if self.on_call is not None: self.on_call( kwargs[ "cwd" ] )
        if self.exit_code != 0: return Done( returncode=self.exit_code, stderr="AGY_ERROR: {\"status\":\"UNAVAILABLE\"}" )
        result = { "conversation_id" : "c-1", "status" : "SUCCESS", "response" : self.reply( prompt ), "duration_seconds" : 1.5, "num_turns" : 1, "usage" : self.usage }
        result.update( self.result_overrides )
        return Done( stdout=json.dumps( { "event" : "result", "result" : result } ) + "\n" )

    def reply( self, prompt ):
        if self.answer is not None: return self.answer
        if prompt.startswith( ce.SYSTEM_PROMPT ):
            return json.dumps( { "claims" : [ { "claim" : line, "quote" : line } for line in tagged( prompt, "old_text" ).splitlines() ] } )
        haystack = tagged( prompt, "new_text" )
        texts    = [ line.split( ". ", 1 )[ 1 ] for line in tagged( prompt, "claims" ).splitlines() ]
        return json.dumps( { "verdicts" : [ { "id" : n, "verdict" : "present" if text in haystack else "absent" } for n, text in enumerate( texts, start=1 ) ] } )


@pytest.fixture( autouse=True )
def claude_again_afterwards():
    yield
    mt.configure_claude()
    mt.set_budget( None, {} )
    mt.AGY_USAGE.clear()


@pytest.fixture
def agy_bin( tmp_path ):
    path = tmp_path / "agy"
    path.write_bytes( b"#!/bin/sh\n" )
    path.chmod( 0o755 )
    return str( path )


def complete( *args, **kwargs ):
    return asyncio.run( mt.complete( *args, **kwargs ) )


# ---- configure_agy and configure_claude ---------------------------------------------------------

def test_configure_agy_pins_the_binary_and_returns_the_ledger_binding( agy_bin ):
    fake    = FakeAgy( version="1.2.17" )
    binding = mt.configure_agy( agy_bin, runner=fake )

    info = os.stat( agy_bin )
    assert binding == f"agy={os.path.realpath( agy_bin )}|size=10|mtime_ns={info.st_mtime_ns}|version=1.2.17|profile={PROFILE}"
    assert mt.TRANSPORT   == "agy"
    assert mt.AGY_BIN     == agy_bin
    assert mt.AGY_PIN     == agy_runtime.binary_fingerprint( agy_bin )
    assert mt.AGY_VERSION == "1.2.17"
    assert mt.AGY_RUNNER  is fake


def test_configure_agy_empties_the_token_tally( agy_bin ):
    mt.AGY_USAGE[ "old-model" ] = { "calls" : 9 }

    mt.configure_agy( agy_bin, runner=FakeAgy() )

    assert mt.agy_usage_summary() == {}


def test_configure_agy_refuses_a_missing_binary_and_stays_on_claude( tmp_path ):
    with pytest.raises( ValueError, match="is not usable" ):
        mt.configure_agy( str( tmp_path / "absent" ) )

    assert mt.TRANSPORT == "claude"
    assert mt.AGY_PIN   is None


def test_configure_agy_refuses_a_binary_that_reports_no_version( agy_bin ):
    with pytest.raises( ValueError, match="is not usable: agy --version failed" ):
        mt.configure_agy( agy_bin, runner=FakeAgy( version="" ) )

    assert mt.TRANSPORT == "claude"


def test_configure_claude_forgets_the_agy_pin( agy_bin ):
    mt.configure_agy( agy_bin, runner=FakeAgy() )

    mt.configure_claude()

    assert ( mt.TRANSPORT, mt.AGY_BIN, mt.AGY_PIN, mt.AGY_VERSION, mt.AGY_RUNNER, mt.AGY_STOP ) == ( "claude", None, None, None, None, None )


def test_the_pin_is_taken_after_the_version_call_so_an_update_it_starts_is_the_pinned_binary( agy_bin ):
    class UpdatesOnVersion( FakeAgy ):
        def __call__( self, argv, **kwargs ):
            if argv[ 1: ] == [ "--version" ]:
                with open( agy_bin, "wb" ) as handle: handle.write( b"#!/bin/sh\n# the updater replaced me\n" )
            return super().__call__( argv, **kwargs )

    fake = UpdatesOnVersion( answer="ok" )
    mt.configure_agy( agy_bin, runner=fake )

    assert mt.AGY_PIN[ "size" ] == len( b"#!/bin/sh\n# the updater replaced me\n" ) != 10
    assert complete( "m", "s", "u" ) == "ok"


def test_calls_overlap_instead_of_waiting_for_each_other( agy_bin ):
    mt.configure_agy( agy_bin, runner=FakeAgy( answer="ok", on_call=lambda cwd: time.sleep( 0.3 ) ) )

    async def four_at_once():
        started = time.monotonic()
        await asyncio.gather( *[ mt.complete( "m", "s", "u" ) for _ in range( 4 ) ] )
        return time.monotonic() - started

    assert asyncio.run( four_at_once() ) < 0.9


def test_the_transports_are_claude_and_agy_and_claude_is_the_default():
    assert mt.TRANSPORTS == ( "claude", "agy" )
    assert mt.TRANSPORT  == "claude"


# ---- complete under agy -------------------------------------------------------------------------

def test_complete_sends_the_joined_prompt_to_the_named_model_and_returns_the_stripped_answer( agy_bin ):
    fake = FakeAgy( answer="  the answer \n" )
    mt.configure_agy( agy_bin, runner=fake )

    def never( **kwargs ):
        pytest.fail( "the Claude query function was called on the agy path", pytrace=False )

    assert complete( "gemini-x-high", "SYSTEM TEXT", "USER TEXT", query_fn=never, timeout_seconds=45 ) == "the answer"

    assert len( fake.calls ) == 1
    call = fake.calls[ 0 ]
    assert call[ "model" ]  == "gemini-x-high"
    assert call[ "prompt" ] == "SYSTEM TEXT\n\nUSER TEXT"
    assert call[ "argv" ]   == agy_runtime.build_argv( model="gemini-x-high", timeout_seconds=45, agent="lupin-text-only", agy_bin=os.path.realpath( agy_bin ) )


def test_each_call_runs_in_its_own_directory_holding_only_the_no_tools_agent_and_removed_afterwards( agy_bin ):
    fake = FakeAgy( answer="ok" )
    mt.configure_agy( agy_bin, runner=fake )

    complete( "m", "s", "u" )
    complete( "m", "s", "u" )

    first, second = fake.calls
    assert first[ "cwd" ] != second[ "cwd" ]
    assert os.path.basename( first[ "cwd" ] ).startswith( "agy-call-" )
    assert first[ "cwd_listing" ] == [ ".agents/agents/lupin-text-only.md" ] == second[ "cwd_listing" ]
    assert mt.AGY_SCRATCH_ENTRIES == [ ".agents", ".agents/agents", ".agents/agents/lupin-text-only.md" ]
    assert first[ "agent_text" ] == AGENT_TEXT == second[ "agent_text" ]
    assert not os.path.exists( first[ "cwd" ] ) and not os.path.exists( second[ "cwd" ] )


def test_tokens_are_summed_per_model_and_the_summary_is_a_copy( agy_bin ):
    mt.configure_agy( agy_bin, runner=FakeAgy( answer="ok" ) )

    complete( "model-a", "s", "u" )
    complete( "model-a", "s", "u" )
    complete( "model-b", "s", "u" )

    summary = mt.agy_usage_summary()
    assert summary == {
        "model-a" : { "calls" : 2, "input_tokens" : 200, "output_tokens" : 14, "thinking_tokens" : 6, "cache_read_tokens" : 100, "total_tokens" : 220 },
        "model-b" : { "calls" : 1, "input_tokens" : 100, "output_tokens" : 7,  "thinking_tokens" : 3, "cache_read_tokens" : 50,  "total_tokens" : 110 }
    }
    summary[ "model-a" ][ "calls" ] = 999
    assert mt.agy_usage_summary()[ "model-a" ][ "calls" ] == 2


def test_a_token_field_agy_does_not_report_counts_as_zero( agy_bin ):
    mt.configure_agy( agy_bin, runner=FakeAgy( answer="ok", usage={ "input_tokens" : 5, "total_tokens" : 6 } ) )

    complete( "m", "s", "u" )

    assert mt.agy_usage_summary() == { "m" : { "calls" : 1, "input_tokens" : 5, "output_tokens" : 0, "thinking_tokens" : 0, "cache_read_tokens" : 0, "total_tokens" : 6 } }


@pytest.mark.parametrize( "odd", [ None, "12", True, 1.5 ] )
def test_a_token_count_that_is_not_a_whole_number_adds_nothing_and_does_not_fail_the_call( agy_bin, odd ):
    mt.configure_agy( agy_bin, runner=FakeAgy( answer="ok", usage={ "input_tokens" : odd, "total_tokens" : 6 } ) )

    assert complete( "m", "s", "u" ) == "ok"
    assert mt.agy_usage_summary()[ "m" ] == { "calls" : 1, "input_tokens" : 0, "output_tokens" : 0, "thinking_tokens" : 0, "cache_read_tokens" : 0, "total_tokens" : 6 }


@pytest.mark.parametrize( "given, sent", [ ( 45.9, "45s" ), ( 0.2, "1s" ), ( 600, "600s" ) ] )
def test_the_time_limit_reaches_agy_as_whole_seconds( agy_bin, given, sent ):
    fake = FakeAgy( answer="ok" )
    mt.configure_agy( agy_bin, runner=fake )

    complete( "m", "s", "u", timeout_seconds=given )

    argv = fake.calls[ 0 ][ "argv" ]
    assert argv[ argv.index( "--print-timeout" ) + 1 ] == sent


def test_thinking_off_is_refused_before_any_charge_or_call( agy_bin, tmp_path ):
    fake   = FakeAgy( answer="ok" )
    ledger = tmp_path / "calls.jsonl"
    mt.configure_agy( agy_bin, runner=fake )
    mt.set_budget( str( ledger ), { "m" : 5 } )

    with pytest.raises( ValueError, match="thinking 'off' has no agy setting" ):
        complete( "m", "s", "u", thinking="off" )

    assert fake.calls == []
    assert not ledger.exists()


def test_thinking_off_planned_by_record_calls_is_refused_too( agy_bin ):
    fake = FakeAgy( answer="ok" )
    mt.configure_agy( agy_bin, runner=fake )

    async def judge_block():
        with mt.record_calls( ( ( "judge", "off" ), ) ):
            await mt.complete( "m", "s", "u" )

    with pytest.raises( ValueError, match="thinking 'off' has no agy setting" ):
        asyncio.run( judge_block() )

    assert fake.calls == []


def test_a_capped_model_is_charged_and_the_cap_stops_the_next_call( agy_bin, tmp_path ):
    fake = FakeAgy( answer="ok" )
    mt.configure_agy( agy_bin, runner=fake )
    mt.set_budget( str( tmp_path / "calls.jsonl" ), { "m" : 1 } )

    assert complete( "m", "s", "u" ) == "ok"
    with pytest.raises( mt.CallBudgetExceeded ):
        complete( "m", "s", "u" )

    assert len( fake.calls ) == 1
    assert mt.calls_used( "m" ) == 1


def test_a_finished_call_is_recorded_with_its_stage_and_seconds_and_a_failed_one_is_not( agy_bin ):
    fake = FakeAgy( answer="ok", on_call=lambda cwd: time.sleep( 0.05 ) )
    mt.configure_agy( agy_bin, runner=fake )

    async def block():
        with mt.record_calls( ( ( "extractor", "default" ), ) ) as calls:
            await mt.complete( "m", "s", "u" )
            fake.exit_code = 3
            with pytest.raises( mt.ModelCallError ):
                await mt.complete( "m", "s", "u" )
            return list( calls )

    calls = asyncio.run( block() )

    assert len( calls ) == 1
    stage, seconds = calls[ 0 ]
    assert stage == "extractor"
    assert 0.05 <= seconds < 5


def test_a_call_outside_record_calls_returns_its_answer_and_records_nothing( agy_bin ):
    mt.configure_agy( agy_bin, runner=FakeAgy( answer="ok" ) )

    assert complete( "m", "s", "u" ) == "ok"


def test_a_failed_agy_call_is_a_model_call_error_naming_the_model( agy_bin ):
    mt.configure_agy( agy_bin, runner=FakeAgy( exit_code=3 ) )

    with pytest.raises( mt.ModelCallError, match=r"model call to gemini-x failed: agy exited 3 \(model gemini-x\)" ) as raised:
        complete( "gemini-x", "s", "u" )

    assert isinstance( raised.value.__cause__, agy_runtime.AgyCallError )
    assert mt.agy_usage_summary() == {}


def test_an_answer_that_came_with_a_refused_tool_action_is_rejected_and_not_tallied( agy_bin ):
    mt.configure_agy( agy_bin, runner=FakeAgy( answer="looks fine", result_overrides={ "denied_actions" : [ "write_file(/x)" ] } ) )

    with pytest.raises( mt.ModelCallError, match=r"tried tool actions and was refused them: \['write_file\(/x\)'\]" ):
        complete( "m", "s", "u" )

    assert mt.agy_usage_summary() == {}


def test_an_answer_that_left_a_file_in_the_scratch_directory_is_rejected( agy_bin ):
    def write_a_file( cwd ):
        with open( os.path.join( cwd, "notes.txt" ), "w" ) as handle: handle.write( "agy used a tool" )

    mt.configure_agy( agy_bin, runner=FakeAgy( answer="looks fine", on_call=write_a_file ) )

    with pytest.raises( mt.ModelCallError, match=r"changed its scratch directory, which now holds: \['.agents', '.agents/agents', '.agents/agents/lupin-text-only.md', 'notes.txt'\]" ):
        complete( "m", "s", "u" )

    assert mt.agy_usage_summary() == {}


def test_an_answer_that_came_with_a_file_hidden_under_the_agents_folder_is_rejected( agy_bin ):
    def write_beside_the_agent( cwd ):
        with open( os.path.join( cwd, ".agents", "agents", "other.md" ), "w" ) as handle: handle.write( "x" )

    mt.configure_agy( agy_bin, runner=FakeAgy( answer="looks fine", on_call=write_beside_the_agent ) )

    with pytest.raises( mt.ModelCallError, match="changed its scratch directory" ):
        complete( "m", "s", "u" )


def test_an_answer_that_came_with_a_changed_agent_definition_is_rejected( agy_bin ):
    def give_itself_tools( cwd ):
        with open( os.path.join( cwd, mt.AGY_AGENT_PATH ), "w" ) as handle: handle.write( mt.AGY_AGENT_TEXT.replace( "tools: []", "tools: [run_command]" ) )

    mt.configure_agy( agy_bin, runner=FakeAgy( answer="looks fine", on_call=give_itself_tools ) )

    with pytest.raises( mt.ModelCallError, match=r"changed its scratch directory, which now holds: \['.agents', '.agents/agents', '.agents/agents/lupin-text-only.md'\]" ):
        complete( "m", "s", "u" )

    assert mt.agy_usage_summary() == {}


def test_an_answer_that_came_with_the_agent_definition_deleted_is_rejected( agy_bin ):
    mt.configure_agy( agy_bin, runner=FakeAgy( answer="looks fine", on_call=lambda cwd: os.remove( os.path.join( cwd, mt.AGY_AGENT_PATH ) ) ) )

    with pytest.raises( mt.ModelCallError, match=r"changed its scratch directory, which now holds: \['.agents', '.agents/agents'\]" ):
        complete( "m", "s", "u" )


def test_an_agent_definition_that_cannot_be_written_is_a_model_call_error_and_agy_is_not_called( agy_bin, monkeypatch ):
    fake = FakeAgy( answer="ok" )
    mt.configure_agy( agy_bin, runner=fake )

    def no_room( path ): raise OSError( 28, "No space left on device" )
    monkeypatch.setattr( mt.os, "makedirs", no_room )

    with pytest.raises( mt.ModelCallError, match="model call to m could not write its agent definition: .*No space left on device" ):
        complete( "m", "s", "u" )

    assert fake.calls == []
    assert mt.agy_usage_summary() == {}


def test_an_agent_definition_whose_folder_exists_but_refuses_the_file_is_a_model_call_error( agy_bin, monkeypatch ):
    if os.geteuid() == 0: pytest.skip( "root writes into a folder whatever its mode" )
    fake = FakeAgy( answer="ok" )
    mt.configure_agy( agy_bin, runner=fake )
    real_makedirs = os.makedirs

    # os.makedirs calls itself for each parent, so only the last folder is made read-only.
    def read_only_folder( path, **kwargs ):
        real_makedirs( path, **kwargs )
        if path.endswith( os.path.join( ".agents", "agents" ) ): os.chmod( path, 0o500 )
    monkeypatch.setattr( mt.os, "makedirs", read_only_folder )

    with pytest.raises( mt.ModelCallError, match="model call to m could not write its agent definition: .*Permission denied" ):
        complete( "m", "s", "u" )

    assert fake.calls == []


def test_a_scratch_directory_that_cannot_be_made_is_a_model_call_error_and_agy_is_not_called( agy_bin, monkeypatch ):
    fake = FakeAgy( answer="ok" )
    mt.configure_agy( agy_bin, runner=fake )

    def no_room( prefix ): raise OSError( 28, "No space left on device" )
    monkeypatch.setattr( mt.tempfile, "mkdtemp", no_room )

    with pytest.raises( mt.ModelCallError, match="model call to m could not make its scratch directory: .*No space left on device" ):
        complete( "m", "s", "u" )

    assert fake.calls == []


def test_a_scratch_directory_that_cannot_be_removed_does_not_lose_the_answer( agy_bin, monkeypatch ):
    fake = FakeAgy( answer="the answer" )
    mt.configure_agy( agy_bin, runner=fake )
    asked       = []
    real_rmtree = shutil.rmtree

    def busy( path, ignore_errors=False ):
        asked.append( ignore_errors )
    monkeypatch.setattr( mt.shutil, "rmtree", busy )

    try:
        assert complete( "m", "s", "u" ) == "the answer"
        assert asked == [ True ]
    finally:
        real_rmtree( fake.calls[ 0 ][ "cwd" ] )


def test_an_answer_that_left_an_empty_directory_is_rejected( agy_bin ):
    mt.configure_agy( agy_bin, runner=FakeAgy( answer="looks fine", on_call=lambda cwd: os.mkdir( os.path.join( cwd, "made-by-a-tool" ) ) ) )

    with pytest.raises( mt.ModelCallError, match=r"changed its scratch directory, which now holds: \['.agents', '.agents/agents', '.agents/agents/lupin-text-only.md', 'made-by-a-tool'\]" ):
        complete( "m", "s", "u" )

    assert mt.agy_usage_summary() == {}


def test_an_answer_that_left_a_directory_that_cannot_be_listed_is_rejected( agy_bin ):
    if os.geteuid() == 0: pytest.skip( "root lists a directory whatever its mode" )

    made = []

    def hide_a_file( cwd ):
        hidden = os.path.join( cwd, "hidden" )
        os.mkdir( hidden )
        with open( os.path.join( hidden, "notes.txt" ), "w" ) as handle: handle.write( "agy used a tool" )
        os.chmod( hidden, 0 )
        made.append( cwd )

    mt.configure_agy( agy_bin, runner=FakeAgy( answer="looks fine", on_call=hide_a_file ) )

    try:
        with pytest.raises( mt.ModelCallError, match="model call to m left a scratch directory that cannot be listed: .*Permission denied" ):
            complete( "m", "s", "u" )

        assert mt.agy_usage_summary() == {}
    finally:
        # The removal the call attempts cannot empty a directory it cannot list, so the test does it.
        os.chmod( os.path.join( made[ 0 ], "hidden" ), 0o700 )
        shutil.rmtree( made[ 0 ] )


class Unavailable:
    """Stand-in for subprocess.run that answers 503 a set number of times, then hands over to a FakeAgy."""

    STDERR = "error: Eligibility check failed: UNAVAILABLE (code 503): The service is currently unavailable.\n"

    def __init__( self, times, then ):
        self.left = times
        self.then = then
        self.cwds = []

    def __call__( self, argv, **kwargs ):
        if argv[ 1: ] == [ "--version" ]: return self.then( argv, **kwargs )
        self.cwds.append( kwargs[ "cwd" ] )
        if self.left > 0:
            self.left -= 1
            return Done( returncode=1, stderr=self.STDERR )
        return self.then( argv, **kwargs )


def test_a_call_answered_unavailable_is_tried_again_after_each_wait_and_then_answers( agy_bin, monkeypatch, capsys ):
    waits  = []
    runner = Unavailable( 2, FakeAgy( answer="the answer" ) )
    monkeypatch.setattr( mt, "AGY_SLEEP", waits.append )
    mt.configure_agy( agy_bin, runner=runner )

    assert complete( "m", "s", "u" ) == "the answer"

    assert waits == [ 15, 45 ]
    assert capsys.readouterr().err == "agy unavailable (model m), try 1 of 4; waiting 15s\nagy unavailable (model m), try 2 of 4; waiting 45s\n"
    assert len( runner.cwds ) == 3 and len( set( runner.cwds ) ) == 3
    assert not any( os.path.exists( cwd ) for cwd in runner.cwds )
    assert mt.agy_usage_summary()[ "m" ][ "calls" ] == 1


def test_a_call_answered_unavailable_on_every_try_is_a_model_call_error_naming_the_tries( agy_bin, monkeypatch ):
    waits  = []
    runner = Unavailable( 99, FakeAgy( answer="never reached" ) )
    monkeypatch.setattr( mt, "AGY_SLEEP", waits.append )
    mt.configure_agy( agy_bin, runner=runner )

    with pytest.raises( mt.ModelCallError, match=r"model call to m failed, unavailable on each of 4 tries: agy exited 1 \(model m\); stderr: error: Eligibility check failed: UNAVAILABLE \(code 503\)" ) as raised:
        complete( "m", "s", "u" )

    assert isinstance( raised.value.__cause__, agy_runtime.AgyUnavailable )
    assert waits == [ 15, 45, 90 ] == list( mt.AGY_UNAVAILABLE_WAITS )
    assert len( runner.cwds ) == 4
    assert mt.agy_usage_summary() == {}


def test_the_recorded_seconds_are_those_of_the_try_that_answered_and_leave_the_waits_out( agy_bin, monkeypatch ):
    # The module's own name for time is swapped, not time.monotonic itself, which the event loop reads.
    clock = [ 1000.0 ]
    monkeypatch.setattr( mt, "time", types.SimpleNamespace( monotonic=lambda: clock[ 0 ], sleep=time.sleep ) )

    def a_long_wait( seconds ): clock[ 0 ] += seconds

    class Slow( FakeAgy ):
        def __call__( self, argv, **kwargs ):
            if argv[ 1: ] != [ "--version" ]: clock[ 0 ] += 2.0
            return super().__call__( argv, **kwargs )

    monkeypatch.setattr( mt, "AGY_SLEEP", a_long_wait )
    mt.configure_agy( agy_bin, runner=Unavailable( 2, Slow( answer="ok" ) ) )

    async def one_call():
        with mt.record_calls( [ ( "judge", "default" ) ] ) as calls:
            await mt.complete( "m", "s", "u" )
        return calls

    assert asyncio.run( one_call() ) == [ ( "judge", 2.0 ) ]
    assert clock[ 0 ] == 1000.0 + 15 + 45 + 2.0


def test_an_agent_definition_replaced_by_a_link_to_the_same_text_is_rejected( agy_bin, tmp_path ):
    twin = tmp_path / "twin.md"
    twin.write_text( mt.AGY_AGENT_TEXT, encoding="utf-8" )

    def swap_for_a_link( cwd ):
        os.remove( os.path.join( cwd, mt.AGY_AGENT_PATH ) )
        os.symlink( str( twin ), os.path.join( cwd, mt.AGY_AGENT_PATH ) )

    mt.configure_agy( agy_bin, runner=FakeAgy( answer="looks fine", on_call=swap_for_a_link ) )

    with pytest.raises( mt.ModelCallError, match="changed its scratch directory" ):
        complete( "m", "s", "u" )

    assert mt.agy_usage_summary() == {}


def test_a_failure_that_is_not_unavailable_is_not_tried_again( agy_bin, monkeypatch ):
    waits = []
    fake  = FakeAgy( exit_code=3 )
    monkeypatch.setattr( mt, "AGY_SLEEP", waits.append )
    mt.configure_agy( agy_bin, runner=fake )

    with pytest.raises( mt.ModelCallError, match=r"model call to m failed: agy exited 3" ):
        complete( "m", "s", "u" )

    assert waits == [] and len( fake.calls ) == 1


def test_a_capped_model_is_charged_once_for_a_call_that_was_tried_again( agy_bin, tmp_path, monkeypatch ):
    monkeypatch.setattr( mt, "AGY_SLEEP", lambda seconds: None )
    mt.configure_agy( agy_bin, runner=Unavailable( 1, FakeAgy( answer="ok" ) ) )
    mt.set_budget( str( tmp_path / "ledger.jsonl" ), { "m" : 1 } )

    assert complete( "m", "s", "u" ) == "ok"

    with pytest.raises( mt.CallBudgetExceeded ):
        complete( "m", "s", "u" )


def test_the_real_sleep_is_what_waits_by_default():
    assert mt.AGY_SLEEP is time.sleep


def test_an_agent_definition_left_as_bytes_that_are_not_text_is_a_model_call_error( agy_bin ):
    def not_text( cwd ):
        with open( os.path.join( cwd, mt.AGY_AGENT_PATH ), "wb" ) as handle: handle.write( b"\xff\xfe\xff" )

    mt.configure_agy( agy_bin, runner=FakeAgy( answer="looks fine", on_call=not_text ) )

    with pytest.raises( mt.ModelCallError, match="model call to m left an agent definition that cannot be read back: 'utf-8' codec" ):
        complete( "m", "s", "u" )

    assert mt.agy_usage_summary() == {}


def test_an_agent_definition_left_unreadable_is_a_model_call_error( agy_bin ):
    if os.geteuid() == 0: pytest.skip( "root reads a file whatever its mode" )
    mt.configure_agy( agy_bin, runner=FakeAgy( answer="looks fine", on_call=lambda cwd: os.chmod( os.path.join( cwd, mt.AGY_AGENT_PATH ), 0 ) ) )

    with pytest.raises( mt.ModelCallError, match="model call to m left an agent definition that cannot be read back: .*Permission denied" ):
        complete( "m", "s", "u" )

    assert mt.agy_usage_summary() == {}


def test_a_binary_that_changed_after_the_pin_stops_the_call_and_is_not_a_model_call_error( agy_bin ):
    fake = FakeAgy( answer="ok" )
    mt.configure_agy( agy_bin, runner=fake )

    with open( agy_bin, "wb" ) as handle: handle.write( b"#!/bin/sh\n# agy updated itself\n" )

    with pytest.raises( agy_runtime.AgyBinaryChanged ) as raised:
        complete( "m", "s", "u" )

    assert not isinstance( raised.value, mt.ModelCallError )
    assert fake.calls == []
    assert mt.AGY_STOP.startswith( "agy binary changed since the run began: pinned " )


def test_calls_refused_for_a_changed_binary_are_not_charged_and_the_disk_is_read_once( agy_bin, tmp_path, monkeypatch ):
    mt.configure_agy( agy_bin, runner=FakeAgy( answer="ok" ) )
    mt.set_budget( str( tmp_path / "calls.jsonl" ), { "m" : 5 } )
    with open( agy_bin, "wb" ) as handle: handle.write( b"#!/bin/sh\n# agy updated itself\n" )

    with pytest.raises( agy_runtime.AgyBinaryChanged ):
        complete( "m", "s", "u" )

    def no_more_reads( agy_bin ):
        pytest.fail( "the binary was fingerprinted again after the run had stopped", pytrace=False )

    monkeypatch.setattr( agy_runtime, "binary_fingerprint", no_more_reads )
    for _ in range( 2 ):
        with pytest.raises( agy_runtime.AgyBinaryChanged, match="agy binary changed since the run began" ):
            complete( "m", "s", "u" )

    assert mt.calls_used( "m" ) == 0


def test_configuring_agy_again_after_a_stop_pins_the_new_binary_and_calls_work( agy_bin ):
    fake = FakeAgy( answer="ok" )
    mt.configure_agy( agy_bin, runner=fake )
    with open( agy_bin, "wb" ) as handle: handle.write( b"#!/bin/sh\n# agy updated itself\n" )
    with pytest.raises( agy_runtime.AgyBinaryChanged ):
        complete( "m", "s", "u" )

    mt.configure_agy( agy_bin, runner=fake )

    assert mt.AGY_STOP is None
    assert complete( "m", "s", "u" ) == "ok"


def test_a_binary_that_disappeared_counts_as_changed( agy_bin ):
    mt.configure_agy( agy_bin, runner=FakeAgy( answer="ok" ) )
    os.remove( agy_bin )

    with pytest.raises( agy_runtime.AgyBinaryChanged, match="now None" ):
        complete( "m", "s", "u" )


def test_a_change_run_agy_reports_during_a_call_is_kept_as_the_stop_reason( agy_bin ):
    def update_itself( cwd ):
        with open( agy_bin, "wb" ) as handle: handle.write( b"#!/bin/sh\n# agy updated itself mid-call\n" )

    mt.configure_agy( agy_bin, runner=FakeAgy( answer="ok", on_call=update_itself ) )

    with pytest.raises( agy_runtime.AgyBinaryChanged, match="while the call ran" ):
        complete( "m", "s", "u" )

    assert "while the call ran" in mt.AGY_STOP


def test_on_claude_the_agy_runner_is_never_used_and_the_query_function_is( agy_bin ):
    from claude_agent_sdk import AssistantMessage, TextBlock

    async def claude( prompt, options ):
        yield AssistantMessage( content=[ TextBlock( "from claude" ) ], model=options.model )

    fake = FakeAgy( answer="from agy" )
    mt.configure_agy( agy_bin, runner=fake )
    mt.configure_claude()

    assert complete( "m", "s", "u", query_fn=claude ) == "from claude"
    assert fake.calls == []


def write_stand_in( path ):
    """A real executable that answers --version, and otherwise echoes the prompt it read on stdin."""
    path.write_text(
        "#!/bin/sh\n"
        "if [ \"$1\" = \"--version\" ]; then echo 9.9.9; exit 0; fi\n"
        "python3 -c 'import json,sys; p=json.loads(sys.stdin.readline())[\"message\"][\"content\"]; "
        "print(json.dumps({\"event\":\"result\",\"result\":{\"conversation_id\":\"c\",\"status\":\"SUCCESS\","
        "\"response\":\"echo: \"+p,\"duration_seconds\":0.1,\"num_turns\":1,\"usage\":{\"total_tokens\":4}}}))'\n"
    )
    path.chmod( path.stat().st_mode | stat.S_IXUSR )


def test_with_a_real_process_the_version_is_read_and_the_joined_prompt_arrives_on_stdin( tmp_path ):
    binary = tmp_path / "agy"
    write_stand_in( binary )

    binding = mt.configure_agy( str( binary ) )

    assert binding.endswith( "|version=9.9.9|profile=" + PROFILE )
    assert complete( "m", "système", "user \"text\"\nline two" ) == "echo: système\n\nuser \"text\"\nline two"
    assert mt.agy_usage_summary()[ "m" ][ "total_tokens" ] == 4


# ---- harness_cli --transport agy ----------------------------------------------------------------

def cli_args( tmp_path, *extra, **override ):
    names = { "extractor-model" : "gem-pro", "judge-model" : "gem-flash", "escalation-model" : "gem-flash-2", "writer-model" : "gem-pro" }
    names.update( override )
    argv  = [ "--pairs", str( tmp_path / "pairs.json" ), "--ledger", str( tmp_path / "ledger.jsonl" ), "--out", str( tmp_path / "out.json" ) ]
    for key, value in names.items(): argv += [ f"--{key}", value ]
    return argv + list( extra )


def write_pairs( tmp_path ):
    seeded = { "id" : "seeded", "old" : OLD, "new" : L1 + "\n" + L3, "design" : None, "seed_span" : list( ce.locate_quote( L2, OLD ) ) }
    clean  = { "id" : "clean",  "old" : OLD, "new" : OLD,            "design" : None, "seed_span" : None }
    ( tmp_path / "pairs.json" ).write_text( json.dumps( [ seeded, clean ] ) )


def test_the_command_line_runs_the_pairs_through_agy_and_reports_it( tmp_path, agy_bin, capsys ):
    write_pairs( tmp_path )
    fake = FakeAgy()

    def never( **kwargs ):
        pytest.fail( "the Claude query function was called on an agy run", pytrace=False )

    code = cli.main( cli_args( tmp_path, "--transport", "agy", "--agy-bin", agy_bin, "--parallel", "2" ), query_fn=never, agy_runner=fake )

    assert code == 0
    report  = json.loads( ( tmp_path / "out.json" ).read_text() )
    info    = os.stat( agy_bin )
    binding = f"agy={os.path.realpath( agy_bin )}|size=10|mtime_ns={info.st_mtime_ns}|version=1.2.17|profile={PROFILE}"
    assert report[ "transport" ]   == "agy"
    assert report[ "agy_binding" ] == binding
    assert report[ "call_profile" ]          == mt.AGY_CALL_PROFILE
    assert mt.AGY_CALL_PROFILE               == PROFILE
    assert all( call[ "argv" ][ -2: ] == [ "--agent", "lupin-text-only" ] for call in fake.calls )
    assert report[ "call_residual_context" ] == mt.AGY_RESIDUAL_CONTEXT
    assert report[ "lists" ][ 0 ][ "positives" ] == 1 and report[ "lists" ][ 0 ][ "misses" ] == 0

    # Two pairs, two extractor lists each, three judge runs per list: 4 extractor and 12 judge calls.
    models = sorted( call[ "model" ] for call in fake.calls )
    assert models == [ "gem-flash" ] * 12 + [ "gem-pro" ] * 4
    assert report[ "agy_usage" ] == {
        "gem-pro"   : { "calls" : 4,  "input_tokens" : 400,  "output_tokens" : 28, "thinking_tokens" : 12, "cache_read_tokens" : 200, "total_tokens" : 440 },
        "gem-flash" : { "calls" : 12, "input_tokens" : 1200, "output_tokens" : 84, "thinking_tokens" : 36, "cache_read_tokens" : 600, "total_tokens" : 1320 }
    }
    assert all( call[ "prompt" ].startswith( ( ce.SYSTEM_PROMPT + "\n\n", cj.SYSTEM_PROMPT + "\n\n" ) ) for call in fake.calls )

    first_record = json.loads( ( tmp_path / "ledger.jsonl" ).read_text().splitlines()[ 0 ] )
    assert first_record == { "binding" : binding }
    assert mt.TRANSPORT == "claude"
    assert "report written" in capsys.readouterr().out


def test_the_default_transport_is_claude_and_its_report_has_no_agy_fields( tmp_path, capsys ):
    from claude_agent_sdk import AssistantMessage, TextBlock
    write_pairs( tmp_path )
    as_agy = FakeAgy()

    async def claude( prompt, options ):
        yield AssistantMessage( content=[ TextBlock( as_agy.reply( options.system_prompt + "\n\n" + prompt ) ) ], model=options.model )

    assert cli.main( cli_args( tmp_path ), query_fn=claude ) == 0

    report = json.loads( ( tmp_path / "out.json" ).read_text() )
    assert report[ "transport" ] == "claude"
    assert "agy_binding" not in report and "agy_usage" not in report
    assert report[ "call_profile" ]          == mt.CALL_PROFILE
    assert report[ "call_residual_context" ] == mt.RESIDUAL_CONTEXT
    assert json.loads( ( tmp_path / "ledger.jsonl" ).read_text().splitlines()[ 0 ] ) == { "binding" : "claude_cli=None|version=None" }


@pytest.mark.parametrize( "extra, message", [
    ( [ "--transport", "agy", "--claude-cli-path", "/bin/true" ], "--claude-cli-path only applies to --transport claude" ),
    ( [ "--transport", "agy", "--judge-thinking", "off" ],        "--judge-thinking only applies to --transport claude" ),
    ( [ "--agy-bin", "/bin/true" ],                               "--agy-bin only applies to --transport agy" ),
] )
def test_the_command_line_refuses_settings_that_belong_to_the_other_transport( tmp_path, capsys, extra, message ):
    write_pairs( tmp_path )
    fake = FakeAgy()

    assert cli.main( cli_args( tmp_path, *extra ), agy_runner=fake ) == 2

    assert f"REFUSED: {message}" in capsys.readouterr().err
    assert fake.calls == []
    assert not ( tmp_path / "ledger.jsonl" ).exists()


def test_the_command_line_refuses_an_agy_binary_it_cannot_use( tmp_path, capsys ):
    write_pairs( tmp_path )

    assert cli.main( cli_args( tmp_path, "--transport", "agy", "--agy-bin", str( tmp_path / "absent" ) ) ) == 2

    assert "REFUSED: agy binary" in capsys.readouterr().err
    assert not ( tmp_path / "ledger.jsonl" ).exists()
    assert mt.TRANSPORT == "claude"


def test_the_command_line_uses_agy_on_the_search_path_when_no_binary_is_named( tmp_path, monkeypatch ):
    write_pairs( tmp_path )
    seen = []

    def configure( agy_bin, runner=None ):
        seen.append( agy_bin )
        raise ValueError( "stop here" )

    monkeypatch.setattr( mt, "configure_agy", configure )

    assert cli.main( cli_args( tmp_path, "--transport", "agy" ) ) == 2
    assert seen == [ "agy" ]


def test_a_binary_that_changes_during_the_run_ends_it_with_a_refusal( tmp_path, agy_bin, capsys ):
    write_pairs( tmp_path )

    def update_itself( cwd ):
        with open( agy_bin, "wb" ) as handle: handle.write( b"#!/bin/sh\n# agy updated itself mid-run\n" )

    fake = FakeAgy( on_call=update_itself )

    assert cli.main( cli_args( tmp_path, "--transport", "agy", "--agy-bin", agy_bin ), agy_runner=fake ) == 2

    assert "REFUSED: agy binary changed" in capsys.readouterr().err
    assert len( fake.calls ) == 1
    assert not ( tmp_path / "out.json" ).exists()
    assert mt.TRANSPORT == "claude"


def test_a_ledger_written_under_one_agy_binary_is_refused_under_another( tmp_path, agy_bin, capsys ):
    write_pairs( tmp_path )
    argv = cli_args( tmp_path, "--transport", "agy", "--agy-bin", agy_bin )
    assert cli.main( argv, agy_runner=FakeAgy( version="1.2.17" ) ) == 0
    capsys.readouterr()
    second = FakeAgy( version="1.2.18" )

    assert cli.main( argv, agy_runner=second ) == 2

    assert "use a new ledger" in capsys.readouterr().err
    assert second.calls == []


def test_a_ledger_written_under_one_call_profile_is_refused_under_another( tmp_path, agy_bin, capsys, monkeypatch ):
    write_pairs( tmp_path )
    argv = cli_args( tmp_path, "--transport", "agy", "--agy-bin", agy_bin )
    monkeypatch.setattr( mt, "AGY_CALL_PROFILE", "agy-print-1|default-agent" )
    assert cli.main( argv, agy_runner=FakeAgy() ) == 0
    capsys.readouterr()
    monkeypatch.setattr( mt, "AGY_CALL_PROFILE", PROFILE )
    second = FakeAgy()

    assert cli.main( argv, agy_runner=second ) == 2

    assert "use a new ledger" in capsys.readouterr().err
    assert second.calls == []


def test_a_run_stopped_by_a_binary_change_says_to_use_a_new_ledger_and_the_old_one_stays_refused( tmp_path, agy_bin, capsys ):
    write_pairs( tmp_path )
    argv = cli_args( tmp_path, "--transport", "agy", "--agy-bin", agy_bin )

    def update_itself( cwd ):
        with open( agy_bin, "wb" ) as handle: handle.write( b"#!/bin/sh\n# agy updated itself mid-run\n" )

    assert cli.main( argv, agy_runner=FakeAgy( on_call=update_itself ) ) == 2
    assert "rerun with a new --ledger" in capsys.readouterr().err
    again = FakeAgy()

    assert cli.main( argv, agy_runner=again ) == 2

    assert "use a new ledger" in capsys.readouterr().err
    assert again.calls == []


def test_with_pairs_in_flight_a_binary_change_is_the_refusal_even_when_an_earlier_pair_failed_first( tmp_path, agy_bin, capsys, monkeypatch ):
    late_line = "It logs each retry."
    first     = { "id" : "first",  "old" : OLD,                    "new" : OLD,                    "design" : None, "seed_span" : None }
    second    = { "id" : "second", "old" : OLD + "\n" + late_line, "new" : OLD + "\n" + late_line, "design" : None, "seed_span" : None }
    ( tmp_path / "pairs.json" ).write_text( json.dumps( [ first, second ] ) )

    class FirstFailsFastSecondSwapsLate( FakeAgy ):
        def __call__( self, argv, **kwargs ):
            if argv[ 1: ] == [ "--version" ]: return super().__call__( argv, **kwargs )
            prompt = json.loads( kwargs[ "input" ] )[ "message" ][ "content" ]
            # The first pair's call fails at once with an ordinary error. The second pair's call
            # is still running when it does, swaps the binary, and then answers.
            if late_line not in prompt: return Done( returncode=3, stderr="AGY_ERROR" )
            time.sleep( 0.3 )
            with open( agy_bin, "wb" ) as handle: handle.write( b"#!/bin/sh\n# agy updated itself mid-run\n" )
            return super().__call__( argv, **kwargs )

    raised   = []
    real_run = hn.run_all

    async def spy( *args, **kwargs ):
        try:
            return await real_run( *args, **kwargs )
        except Exception as e:
            raised.append( e )
            raise

    monkeypatch.setattr( hn, "run_all", spy )

    code = cli.main( cli_args( tmp_path, "--transport", "agy", "--agy-bin", agy_bin, "--parallel", "2", "--extractor-lists", "1" ), agy_runner=FirstFailsFastSecondSwapsLate() )

    # The masked case itself: what run_all raised is the first pair's ordinary failure.
    assert [ type( e ) for e in raised ] == [ mt.ModelCallError ]
    assert code == 2
    err = capsys.readouterr().err
    assert "REFUSED: agy binary changed while the call ran" in err
    assert "the failure the run raised was ModelCallError: model call to gem-pro failed: agy exited 3" in err
    assert mt.TRANSPORT == "claude"


def test_a_stop_reason_left_by_other_code_does_not_turn_a_claude_failure_into_a_refusal( tmp_path ):
    write_pairs( tmp_path )
    mt.AGY_STOP = "stale reason from a library caller"

    async def broken( prompt, options ):
        raise RuntimeError( "a real bug" )
        yield

    with pytest.raises( mt.ModelCallError, match="a real bug" ):
        cli.main( cli_args( tmp_path ), query_fn=broken )


@pytest.mark.parametrize( "bad", [ None, "600", True, 0, -5, float( "inf" ), float( "nan" ) ] )
def test_a_time_limit_agy_cannot_take_is_refused_before_any_charge_or_call( agy_bin, tmp_path, bad ):
    fake   = FakeAgy( answer="ok" )
    ledger = tmp_path / "calls.jsonl"
    mt.configure_agy( agy_bin, runner=fake )
    mt.set_budget( str( ledger ), { "m" : 5 } )

    with pytest.raises( ValueError, match="timeout_seconds must be a finite number above zero under agy" ):
        complete( "m", "s", "u", timeout_seconds=bad )

    assert fake.calls == []
    assert not ledger.exists()


def test_a_failure_that_is_not_a_binary_change_still_surfaces_as_itself( tmp_path, agy_bin ):
    write_pairs( tmp_path )

    with pytest.raises( mt.ModelCallError ):
        cli.main( cli_args( tmp_path, "--transport", "agy", "--agy-bin", agy_bin, "--parallel", "2" ), agy_runner=FakeAgy( exit_code=3 ) )

    assert mt.TRANSPORT == "claude"


def test_a_ledger_holding_claude_calls_is_refused_under_agy( tmp_path, agy_bin, capsys ):
    write_pairs( tmp_path )
    ( tmp_path / "ledger.jsonl" ).write_text( json.dumps( { "binding" : "claude_cli=None|version=None" } ) + "\n" + json.dumps( { "key" : "k", "value" : "v" } ) + "\n" )
    fake = FakeAgy()

    assert cli.main( cli_args( tmp_path, "--transport", "agy", "--agy-bin", agy_bin ), agy_runner=fake ) == 2

    assert "use a new ledger" in capsys.readouterr().err
    assert fake.calls == []


def test_a_finished_agy_run_resumes_from_its_ledger_without_a_new_call( tmp_path, agy_bin ):
    write_pairs( tmp_path )
    argv  = cli_args( tmp_path, "--transport", "agy", "--agy-bin", agy_bin )
    first = FakeAgy()
    assert cli.main( argv, agy_runner=first ) == 0
    again = FakeAgy()

    assert cli.main( argv, agy_runner=again ) == 0

    assert len( first.calls ) == 16
    assert again.calls == []


def test_the_harness_still_refuses_a_judge_that_is_the_writer_under_agy( tmp_path, agy_bin, capsys ):
    write_pairs( tmp_path )
    fake = FakeAgy()

    assert cli.main( cli_args( tmp_path, "--transport", "agy", "--agy-bin", agy_bin, **{ "judge-model" : "gem-pro" } ), agy_runner=fake ) == 2

    assert "REFUSED" in capsys.readouterr().err
    assert fake.calls == []
