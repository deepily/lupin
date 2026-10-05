"""
Unit tests for cosa/orchestration/agy/runtime.py.

Isolation contract:
    - No real agy process: every call goes through an injected `_FakeRunner`.
    - No network and no model spend.
    - `binary_fingerprint` reads a stand-in file under tmp_path, never the installed agy.

`REAL_STDOUT` was captured from agy 1.2.17 on 2026-10-05 (model gemini-3.6-flash-low,
one user message on standard input). Only the long `init` event is shortened.
"""
import hashlib
import json
import os
import stat
import subprocess

import pytest

import cosa.orchestration.agy as agy_package
import cosa.orchestration.agy.runtime as runtime
from cosa.orchestration.agy.runtime import (
    AgyBinaryChanged, AgyCallError, AgyResult,
    AgyUnavailable,
    agy_version, binary_fingerprint, build_argv, build_stdin, check_success_fields, parse_result, run_agy,
)


REAL_STDOUT = (
    '{"event":"init","conversation_id":"fb9042c1-7483-414f-b9d7-172700471998","init":{"model":"gemini-3.6-flash-low","cwd":"/scratch","tools":["ask_permission"],"permission_mode":"request-review"}}\n'
    '{"event":"step_update","step_update":{"conversation_id":"fb9042c1-7483-414f-b9d7-172700471998","step_index":0,"state":"DONE","step_type":"user_input"}}\n'
    '{"event":"step_update","step_update":{"conversation_id":"fb9042c1-7483-414f-b9d7-172700471998","step_index":1,"state":"ACTIVE","step_type":"agent_response","text_delta":"PONG 2"}}\n'
    '{"event":"step_update","step_update":{"conversation_id":"fb9042c1-7483-414f-b9d7-172700471998","step_index":1,"state":"DONE","step_type":"agent_response","text_delta":"\\n","duration_seconds":12.458886899,"usage":{"input_tokens":5140,"output_tokens":203,"thinking_tokens":199,"cache_read_tokens":8138,"total_tokens":5343}}}\n'
    '{"event":"result","result":{"conversation_id":"fb9042c1-7483-414f-b9d7-172700471998","status":"SUCCESS","response":"PONG 2\\n","duration_seconds":12.488912804,"num_turns":1,"usage":{"input_tokens":5140,"output_tokens":203,"thinking_tokens":199,"cache_read_tokens":8138,"total_tokens":5343}}}\n'
)

# Captured the same day: the result agy prints when the stdin message is malformed.
REAL_ERROR_STDOUT = (
    '{"event":"result","result":{"conversation_id":"2892ed58-1326-47fd-b0a4-0c336c2be369","status":"ERROR","response":"","error":"stream input \\"user\\" message is missing the \\"message\\" field","duration_seconds":0,"num_turns":0,"usage":{"input_tokens":0,"output_tokens":0,"thinking_tokens":0,"cache_read_tokens":0,"total_tokens":0}}}\n'
)


class _Completed:
    """Stand-in for subprocess.CompletedProcess."""
    def __init__( self, returncode=0, stdout="", stderr="" ):
        self.returncode = returncode
        self.stdout     = stdout
        self.stderr     = stderr


class _FakeRunner:
    """Records the one call it receives and returns a scripted outcome."""
    def __init__( self, completed=None, raises=None ):
        self.completed = completed
        self.raises    = raises
        self.calls     = []

    def __call__( self, argv, **kwargs ):
        self.calls.append( ( argv, kwargs ) )
        if self.raises is not None: raise self.raises
        return self.completed


def _result_stdout( **overrides ):
    """One result event with the real event's fields, selectively overridden."""
    result = json.loads( REAL_STDOUT.splitlines()[ -1 ] )[ "result" ]
    result.update( overrides )
    return json.dumps( { "event" : "result", "result" : result } ) + "\n"


@pytest.fixture
def fake_bin( tmp_path ):
    """An executable stand-in for the agy binary."""
    path = tmp_path / "agy"
    path.write_bytes( b"#!/bin/sh\n" )
    path.chmod( 0o755 )
    return str( path )


@pytest.fixture
def scratch( tmp_path ):
    path = tmp_path / "scratch"
    path.mkdir()
    return str( path )


# =========================================================================== #
# binary_fingerprint
# =========================================================================== #
def test_fingerprint_reports_real_path_size_and_mtime( fake_bin ):
    stat        = os.stat( fake_bin )
    fingerprint = binary_fingerprint( fake_bin )

    assert fingerprint == {
        "path"     : os.path.realpath( fake_bin ),
        "size"     : 10,
        "mtime_ns" : stat.st_mtime_ns
    }


def test_fingerprint_follows_a_symlink_to_the_real_file( fake_bin, tmp_path ):
    link = tmp_path / "agy-link"
    link.symlink_to( fake_bin )

    assert binary_fingerprint( str( link ) )[ "path" ] == os.path.realpath( fake_bin )


def test_fingerprint_changes_when_the_binary_is_replaced( fake_bin ):
    before = binary_fingerprint( fake_bin )

    with open( fake_bin, "wb" ) as handle: handle.write( b"#!/bin/sh\n# newer build\n" )

    after = binary_fingerprint( fake_bin )
    assert after != before
    assert after[ "size" ] == 24


def test_fingerprint_file_removed_after_it_was_found_raises_call_error( tmp_path, monkeypatch ):
    removed = str( tmp_path / "agy-removed-after-lookup" )

    # The lookup answers with a path, and the file is gone by the time it is read.
    monkeypatch.setattr( runtime.shutil, "which", lambda name: removed )

    with pytest.raises( AgyCallError, match="agy binary cannot be read" ):
        binary_fingerprint( "agy" )


def test_fingerprint_missing_binary_raises( tmp_path ):
    with pytest.raises( AgyCallError, match="agy binary not found" ):
        binary_fingerprint( str( tmp_path / "absent" ) )


# =========================================================================== #
# agy_version
# =========================================================================== #
def test_version_returns_first_line_stripped():
    runner = _FakeRunner( _Completed( stdout="  1.2.17 \nextra line\n" ) )

    assert agy_version( "agy-x", runner=runner ) == "1.2.17"
    assert runner.calls == [ ( [ "agy-x", "--version" ], { "capture_output" : True, "text" : True, "timeout" : 60 } ) ]


def test_version_defaults_to_subprocess_run( monkeypatch ):
    seen = []

    def fake_run( argv, **kwargs ):
        seen.append( argv )
        return _Completed( stdout="9.9.9\n" )

    monkeypatch.setattr( runtime.subprocess, "run", fake_run )

    assert agy_version() == "9.9.9"
    assert seen == [ [ "agy", "--version" ] ]


def test_version_nonzero_exit_raises():
    runner = _FakeRunner( _Completed( returncode=2, stdout="1.2.17\n", stderr="boom" + "x" * 600 ) )

    with pytest.raises( AgyCallError ) as raised:
        agy_version( runner=runner )

    assert str( raised.value ) == "agy --version failed: exit=2, stderr=boom" + "x" * 496


@pytest.mark.parametrize( "stdout", [ "", "   \n", None ] )
def test_version_blank_output_raises( stdout ):
    runner = _FakeRunner( _Completed( stdout=stdout, stderr=None ) )

    with pytest.raises( AgyCallError, match="agy --version failed: exit=0" ):
        agy_version( runner=runner )


def test_version_missing_binary_raises_call_error_with_a_real_process( tmp_path ):
    with pytest.raises( AgyCallError, match="agy --version could not be started" ):
        agy_version( str( tmp_path / "no-such-agy" ) )


def test_version_timeout_raises():
    runner = _FakeRunner( raises=subprocess.TimeoutExpired( cmd="agy", timeout=60 ) )

    with pytest.raises( AgyCallError, match="agy --version timed out" ):
        agy_version( runner=runner )


# =========================================================================== #
# build_argv
# =========================================================================== #
def test_argv_without_effort_is_exact():
    assert build_argv( model="gemini-3.1-pro-high", timeout_seconds=300 ) == [
        "agy",
        "-p=",
        "--model", "gemini-3.1-pro-high",
        "--print-timeout", "300s",
        "--new-project",
        "--disable-slash-commands",
        "--input-format", "stream-json",
        "--output-format", "stream-json"
    ]


def test_argv_with_effort_and_binary_appends_effort():
    argv = build_argv( model="m", timeout_seconds=45, effort="high", agy_bin="/opt/agy" )

    assert argv[ 0 ] == "/opt/agy"
    assert argv[ argv.index( "--print-timeout" ) + 1 ] == "45s"
    assert argv[ -2: ] == [ "--effort", "high" ]


def test_argv_names_the_agent_only_when_one_is_given():
    assert "--agent" not in build_argv( model="m", timeout_seconds=1 )
    assert build_argv( model="m", timeout_seconds=1, agent="text-only" )[ -2: ] == [ "--agent", "text-only" ]
    assert build_argv( model="m", timeout_seconds=1, effort="low", agent="text-only" )[ -4: ] == [ "--effort", "low", "--agent", "text-only" ]


@pytest.mark.parametrize( "forbidden", [ "accept-edits", "--sandbox", "--dangerously-skip-permissions", "--mode" ] )
def test_argv_never_grants_edits_or_skips_permissions( forbidden ):
    assert forbidden not in build_argv( model="m", timeout_seconds=1, effort="max" )


# =========================================================================== #
# build_stdin
# =========================================================================== #
def test_stdin_is_one_user_message_line_and_round_trips_hard_text():
    prompt = 'Line one has "quotes" and a backslash \\ .\n/usage on line two, é and 中.'
    line   = build_stdin( prompt )

    assert line.endswith( "\n" )
    assert line.count( "\n" ) == 1
    assert "é and 中" in line
    assert json.loads( line ) == {
        "event"   : "user",
        "message" : { "role" : "user", "content" : prompt }
    }


@pytest.mark.parametrize( "prompt", [ "", "   ", "\n\t" ] )
def test_stdin_blank_prompt_raises( prompt ):
    with pytest.raises( ValueError, match="prompt is empty" ):
        build_stdin( prompt )


# =========================================================================== #
# parse_result
# =========================================================================== #
def test_parse_real_capture_returns_the_result_object():
    result = parse_result( REAL_STDOUT )

    assert result[ "status" ] == "SUCCESS"
    assert result[ "response" ] == "PONG 2\n"
    assert result[ "usage" ][ "thinking_tokens" ] == 199


def test_parse_takes_the_last_result_and_skips_noise():
    stdout = (
        "Fetching...\n"
        "[1, 2, 3]\n"
        '"a bare string"\n'
        + _result_stdout( response="first" )
        + '{"event":"step_update","step_update":{}}\n'
        + _result_stdout( response="second" )
        + '{"event":"step_update","result":{"response":"not a result event"}}\n'
    )

    assert parse_result( stdout )[ "response" ] == "second"


@pytest.mark.parametrize( "noise", [ "9" * 5000, "[" * 200000 ] )
def test_parse_skips_a_line_json_refuses_for_size_or_depth( noise ):
    assert parse_result( noise + "\n" + _result_stdout( response="after the noise" ) )[ "response" ] == "after the noise"


def test_parse_keeps_an_answer_holding_unicode_line_separators_on_one_line():
    answer = "first\u2028second\u0085third"
    stdout = json.dumps( { "event" : "result", "result" : { "status" : "SUCCESS", "response" : answer } }, ensure_ascii=False ) + "\n"

    assert "\u2028" in stdout
    assert parse_result( stdout )[ "response" ] == answer


@pytest.mark.parametrize( "line", [
    '{"event":"result"}',
    '{"event":"result","result":null}',
    '{"event":"result","result":"boom"}',
    '{"event":"result","result":[1]}',
] )
def test_parse_result_event_without_a_result_object_raises( line ):
    with pytest.raises( AgyCallError, match="carries no result object" ):
        parse_result( _result_stdout() + line + "\n" )


# =========================================================================== #
# check_success_fields
# =========================================================================== #
def test_success_fields_accepts_the_real_result():
    assert check_success_fields( parse_result( REAL_STDOUT ) ) is None


@pytest.mark.parametrize( "name", [ "response", "conversation_id", "num_turns", "duration_seconds", "usage" ] )
def test_success_fields_names_a_missing_field( name ):
    result = parse_result( REAL_STDOUT )
    del result[ name ]

    with pytest.raises( AgyCallError, match=f"missing the field '{name}'" ):
        check_success_fields( result )


@pytest.mark.parametrize( "name, value", [
    ( "response", None ), ( "conversation_id", 7 ), ( "num_turns", "1" ), ( "duration_seconds", "12.4" ), ( "usage", [] ),
    ( "num_turns", True ), ( "duration_seconds", False ),
] )
def test_success_fields_names_a_field_of_the_wrong_type( name, value ):
    result         = parse_result( REAL_STDOUT )
    result[ name ] = value

    with pytest.raises( AgyCallError, match=f"field '{name}' has the wrong type" ):
        check_success_fields( result )


def test_success_fields_accepts_a_whole_number_duration():
    result                       = parse_result( REAL_STDOUT )
    result[ "duration_seconds" ] = 0

    assert check_success_fields( result ) is None


@pytest.mark.parametrize( "stdout", [ None, "", "not json\n", '{"event":"init","init":{}}\n' ] )
def test_parse_without_result_event_raises( stdout ):
    with pytest.raises( AgyCallError, match="no result event" ):
        parse_result( stdout )


# =========================================================================== #
# run_agy
# =========================================================================== #
def test_run_returns_the_real_answer_with_its_measurements( fake_bin, scratch, monkeypatch ):
    runner = _FakeRunner( _Completed( stdout=REAL_STDOUT ) )
    clock  = iter( [ 100.0, 114.7734 ] )
    monkeypatch.setattr( runtime.time, "monotonic", lambda: next( clock ) )

    result = run_agy( "Count the lines.", model="gemini-3.6-flash-low", workspace_dir=scratch, agy_bin=fake_bin, runner=runner )

    assert isinstance( result, AgyResult )
    assert result.response         == "PONG 2\n"
    assert result.model            == "gemini-3.6-flash-low"
    assert result.effort           is None
    assert result.conversation_id  == "fb9042c1-7483-414f-b9d7-172700471998"
    assert result.num_turns        == 1
    assert result.duration_seconds == 12.488912804
    assert result.usage            == { "input_tokens" : 5140, "output_tokens" : 203, "thinking_tokens" : 199, "cache_read_tokens" : 8138, "total_tokens" : 5343 }
    assert result.denied_actions   == []
    assert result.response_bytes   == 7
    assert result.response_sha     == hashlib.sha256( b"PONG 2\n" ).hexdigest()
    assert result.fingerprint      == binary_fingerprint( fake_bin )
    assert result.wall_seconds     == 14.773


def test_run_counts_bytes_not_characters_and_reports_the_model_it_was_given( fake_bin, scratch ):
    runner = _FakeRunner( _Completed( stdout=_result_stdout( response="é中" ) ) )

    result = run_agy( "p", model="some-other-model", workspace_dir=scratch, agy_bin=fake_bin, runner=runner )

    assert result.model          == "some-other-model"
    assert result.response_bytes == 5
    assert result.response_sha   == hashlib.sha256( "é中".encode( "utf-8" ) ).hexdigest()


def test_run_passes_prompt_on_stdin_and_runs_in_the_scratch_dir( fake_bin, scratch ):
    runner = _FakeRunner( _Completed( stdout=REAL_STDOUT ) )

    run_agy( "the prompt text", model="m", workspace_dir=scratch, timeout_seconds=40, effort="low", agy_bin=fake_bin, runner=runner )

    assert len( runner.calls ) == 1
    argv, kwargs = runner.calls[ 0 ]
    assert argv == build_argv( model="m", timeout_seconds=40, effort="low", agy_bin=os.path.realpath( fake_bin ) )
    assert "the prompt text" not in " ".join( argv )
    assert kwargs == {
        "input"          : build_stdin( "the prompt text" ),
        "capture_output" : True,
        "text"           : True,
        "encoding"       : "utf-8",
        "timeout"        : 100,
        "cwd"            : scratch
    }


def test_run_passes_the_agent_name_to_agy( fake_bin, scratch ):
    runner = _FakeRunner( _Completed( stdout=REAL_STDOUT ) )

    run_agy( "p", model="m", workspace_dir=scratch, agent="text-only", agy_bin=fake_bin, runner=runner )

    assert runner.calls[ 0 ][ 0 ] == build_argv( model="m", timeout_seconds=300, agent="text-only", agy_bin=os.path.realpath( fake_bin ) )


def test_run_defaults_to_subprocess_run( fake_bin, scratch, monkeypatch ):
    seen = []

    def fake_run( argv, **kwargs ):
        seen.append( kwargs[ "timeout" ] )
        return _Completed( stdout=REAL_STDOUT )

    monkeypatch.setattr( runtime.subprocess, "run", fake_run )

    assert run_agy( "p", model="m", workspace_dir=scratch, agy_bin=fake_bin ).response == "PONG 2\n"
    assert seen == [ 360 ]


def test_run_reports_denied_actions_when_agy_lists_them( fake_bin, scratch ):
    runner = _FakeRunner( _Completed( stdout=_result_stdout( denied_actions=[ "write_file(/x)" ] ) ) )

    result = run_agy( "p", model="m", workspace_dir=scratch, effort="high", agy_bin=fake_bin, runner=runner )

    assert result.denied_actions == [ "write_file(/x)" ]
    assert result.effort         == "high"


def test_run_null_denied_actions_becomes_an_empty_list( fake_bin, scratch ):
    runner = _FakeRunner( _Completed( stdout=_result_stdout( denied_actions=None ) ) )

    assert run_agy( "p", model="m", workspace_dir=scratch, agy_bin=fake_bin, runner=runner ).denied_actions == []


def test_run_denied_actions_of_the_wrong_type_raises_call_error( fake_bin, scratch ):
    runner = _FakeRunner( _Completed( stdout=_result_stdout( denied_actions="write_file(/x)" ) ) )

    with pytest.raises( AgyCallError, match="field 'denied_actions' has the wrong type" ):
        run_agy( "p", model="m", workspace_dir=scratch, agy_bin=fake_bin, runner=runner )


@pytest.mark.parametrize( "stream, exit_code", [ ( 1, 0 ), ( 2, 3 ) ] )
def test_run_with_a_real_process_printing_bytes_that_are_not_utf8_raises_call_error( tmp_path, stream, exit_code ):
    binary    = tmp_path / "agy"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    binary.write_text( f"#!/bin/sh\ncat > /dev/null\nprintf '\\377' >&{stream}\nexit {exit_code}\n" )
    binary.chmod( binary.stat().st_mode | stat.S_IXUSR )

    with pytest.raises( AgyCallError, match=r"not valid UTF-8 \(model m\)" ):
        run_agy( "p", model="m", workspace_dir=str( workspace ), agy_bin=str( binary ) )


def test_run_prompt_that_cannot_be_encoded_raises_call_error_with_a_real_process( tmp_path ):
    binary    = tmp_path / "agy"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _write_stand_in( binary, "never read" )

    with pytest.raises( AgyCallError, match=r"not valid UTF-8 \(model m\)" ):
        run_agy( "a\ud800b", model="m", workspace_dir=str( workspace ), agy_bin=str( binary ) )


def test_run_accepts_a_matching_pin( fake_bin, scratch ):
    runner = _FakeRunner( _Completed( stdout=REAL_STDOUT ) )
    pinned = binary_fingerprint( fake_bin )

    assert run_agy( "p", model="m", workspace_dir=scratch, agy_bin=fake_bin, pinned_fingerprint=pinned, runner=runner ).fingerprint == pinned


def test_run_refuses_a_replaced_binary_before_calling( fake_bin, scratch ):
    runner = _FakeRunner( _Completed( stdout=REAL_STDOUT ) )
    pinned = binary_fingerprint( fake_bin )

    with open( fake_bin, "wb" ) as handle: handle.write( b"#!/bin/sh\n# updated itself\n" )

    with pytest.raises( AgyBinaryChanged, match="agy binary changed since the run began" ):
        run_agy( "p", model="m", workspace_dir=scratch, agy_bin=fake_bin, pinned_fingerprint=pinned, runner=runner )

    assert runner.calls == []


@pytest.mark.parametrize( "replace_with", [ b"#!/bin/sh\n# updated itself mid-call\n", None ] )
def test_run_refuses_the_answer_when_the_binary_changed_during_the_call( fake_bin, scratch, replace_with ):
    pinned = binary_fingerprint( fake_bin )

    def runner( argv, **kwargs ):
        if replace_with is None:
            os.remove( fake_bin )
        else:
            with open( fake_bin, "wb" ) as handle: handle.write( replace_with )
        return _Completed( stdout=REAL_STDOUT )

    with pytest.raises( AgyBinaryChanged, match="agy binary changed while the call ran" ):
        run_agy( "p", model="m", workspace_dir=scratch, agy_bin=fake_bin, pinned_fingerprint=pinned, runner=runner )


def test_run_without_a_pin_returns_the_answer_even_if_the_binary_changed( fake_bin, scratch ):
    before = binary_fingerprint( fake_bin )

    def runner( argv, **kwargs ):
        with open( fake_bin, "wb" ) as handle: handle.write( b"#!/bin/sh\n# updated itself mid-call\n" )
        return _Completed( stdout=REAL_STDOUT )

    assert run_agy( "p", model="m", workspace_dir=scratch, agy_bin=fake_bin, runner=runner ).fingerprint == before


def _write_stand_in( path, answer ):
    """A real executable that records its stdin and prints one result event."""
    result_line = _result_stdout( response=answer ).strip()
    path.write_text( f"#!/bin/sh\ncat > stdin.txt\ncat <<'AGY_EOF'\n{result_line}\nAGY_EOF\n" )
    path.chmod( path.stat().st_mode | stat.S_IXUSR )


def test_run_with_a_real_process_runs_the_fingerprinted_file_not_a_same_named_one_in_the_workspace( tmp_path, monkeypatch ):
    caller_dir = tmp_path / "caller"
    workspace  = tmp_path / "workspace"
    ( caller_dir / "bin" ).mkdir( parents=True )
    ( workspace  / "bin" ).mkdir( parents=True )
    _write_stand_in( caller_dir / "bin" / "agy", "from the fingerprinted binary" )
    _write_stand_in( workspace  / "bin" / "agy", "from the impostor in the workspace" )
    monkeypatch.chdir( caller_dir )

    pinned = binary_fingerprint( "./bin/agy" )
    result = run_agy( "héllo\nline two", model="m", workspace_dir=str( workspace ), agy_bin="./bin/agy", pinned_fingerprint=pinned )

    assert result.response              == "from the fingerprinted binary"
    assert result.fingerprint[ "path" ] == os.path.realpath( caller_dir / "bin" / "agy" )
    assert ( workspace / "stdin.txt" ).read_text( encoding="utf-8" ) == build_stdin( "héllo\nline two" )


@pytest.mark.parametrize( "error", [ FileNotFoundError( 2, "No such file" ), PermissionError( 13, "denied" ), OSError( 26, "Text file busy" ) ] )
def test_run_binary_that_cannot_be_started_raises_call_error( fake_bin, scratch, error ):
    runner = _FakeRunner( raises=error )

    with pytest.raises( AgyCallError, match=r"agy could not be started \(model m\)" ):
        run_agy( "p", model="m", workspace_dir=scratch, agy_bin=fake_bin, runner=runner )


@pytest.mark.parametrize( "timeout_seconds", [ 0, -100, True, 1.5, "300", None ] )
def test_run_bad_timeout_raises_before_calling( fake_bin, scratch, timeout_seconds ):
    runner = _FakeRunner( _Completed( stdout=REAL_STDOUT ) )

    with pytest.raises( ValueError, match="timeout_seconds is not a positive integer" ):
        run_agy( "p", model="m", workspace_dir=scratch, timeout_seconds=timeout_seconds, agy_bin=fake_bin, runner=runner )

    assert runner.calls == []


@pytest.mark.parametrize( "prompt", [ None, 7, b"bytes" ] )
def test_run_non_string_prompt_raises_before_calling( fake_bin, scratch, prompt ):
    runner = _FakeRunner( _Completed( stdout=REAL_STDOUT ) )

    with pytest.raises( ValueError, match="prompt is not a string" ):
        run_agy( prompt, model="m", workspace_dir=scratch, agy_bin=fake_bin, runner=runner )

    assert runner.calls == []


def test_run_success_result_missing_a_field_raises_call_error( fake_bin, scratch ):
    result = parse_result( REAL_STDOUT )
    del result[ "usage" ]
    runner = _FakeRunner( _Completed( stdout=json.dumps( { "event" : "result", "result" : result } ) + "\n" ) )

    with pytest.raises( AgyCallError, match="missing the field 'usage'" ):
        run_agy( "p", model="m", workspace_dir=scratch, agy_bin=fake_bin, runner=runner )


def test_run_null_response_raises_call_error( fake_bin, scratch ):
    runner = _FakeRunner( _Completed( stdout=_result_stdout( response=None ) ) )

    with pytest.raises( AgyCallError, match="field 'response' has the wrong type" ):
        run_agy( "p", model="m", workspace_dir=scratch, agy_bin=fake_bin, runner=runner )


def test_run_result_without_a_status_raises_call_error( fake_bin, scratch ):
    runner = _FakeRunner( _Completed( stdout='{"event":"result","result":{"response":"looks fine"}}\n' ) )

    with pytest.raises( AgyCallError, match=r"agy result status None \(model m\)" ):
        run_agy( "p", model="m", workspace_dir=scratch, agy_bin=fake_bin, runner=runner )


def test_run_missing_workspace_raises_before_calling( fake_bin, tmp_path ):
    runner = _FakeRunner( _Completed( stdout=REAL_STDOUT ) )

    with pytest.raises( ValueError, match="workspace_dir is not a directory" ):
        run_agy( "p", model="m", workspace_dir=str( tmp_path / "absent" ), agy_bin=fake_bin, runner=runner )

    assert runner.calls == []


def test_run_blank_prompt_raises_before_calling( fake_bin, scratch ):
    runner = _FakeRunner( _Completed( stdout=REAL_STDOUT ) )

    with pytest.raises( ValueError, match="prompt is empty" ):
        run_agy( "  ", model="m", workspace_dir=scratch, agy_bin=fake_bin, runner=runner )

    assert runner.calls == []


def test_run_timeout_raises_with_the_outer_limit( fake_bin, scratch ):
    runner = _FakeRunner( raises=subprocess.TimeoutExpired( cmd="agy", timeout=70 ) )

    with pytest.raises( AgyCallError, match=r"agy timed out after 70s \(model m\)" ):
        run_agy( "p", model="m", workspace_dir=scratch, timeout_seconds=10, agy_bin=fake_bin, runner=runner )


def test_run_nonzero_exit_raises_with_the_stderr_tail_even_when_a_result_is_present( fake_bin, scratch ):
    stderr = "x" * 3000 + "AGY_ERROR: {\"status\":\"UNAVAILABLE\"}"
    runner = _FakeRunner( _Completed( returncode=3, stdout=REAL_STDOUT, stderr=stderr ) )

    with pytest.raises( AgyCallError ) as raised:
        run_agy( "p", model="m", workspace_dir=scratch, agy_bin=fake_bin, runner=runner )

    message = str( raised.value )
    assert message.startswith( "agy exited 3 (model m); stderr: " )
    assert message.endswith( 'AGY_ERROR: {"status":"UNAVAILABLE"}' )
    assert len( message ) == len( "agy exited 3 (model m); stderr: " ) + 2000


# The two forms agy 1.2.17 printed on 2026-10-05, copied from the trial130 run log.
UNAVAILABLE_STDERR = [
    "error: Eligibility check failed: UNAVAILABLE (code 503): The service is currently unavailable.\n",
    "error: failed to send message: send failed; already reported to the user: Eligibility check failed: UNAVAILABLE (code 503): The service is currently unavailable.\n"
]


@pytest.mark.parametrize( "stderr", UNAVAILABLE_STDERR )
def test_run_exit_with_a_503_in_the_error_text_raises_unavailable( fake_bin, scratch, stderr ):
    runner = _FakeRunner( _Completed( returncode=1, stdout="", stderr=stderr ) )

    with pytest.raises( AgyUnavailable, match=r"agy exited 1 \(model m\); stderr: error: .*\(code 503\)" ) as raised:
        run_agy( "p", model="m", workspace_dir=scratch, agy_bin=fake_bin, runner=runner )

    assert isinstance( raised.value, AgyCallError )


@pytest.mark.parametrize( "returncode, stderr", [
    ( 3, "error: Individual quota reached. Please upgrade your subscription to increase your limits. Resets in 1h39m6s.\n" ),
    ( 3, "AGY_ERROR: {\"status\":\"UNAVAILABLE\"}" ),
    ( 1, "error: code 503" )
] )
def test_run_exit_without_the_503_mark_is_not_unavailable( fake_bin, scratch, returncode, stderr ):
    runner = _FakeRunner( _Completed( returncode=returncode, stdout="", stderr=stderr ) )

    with pytest.raises( AgyCallError ) as raised:
        run_agy( "p", model="m", workspace_dir=scratch, agy_bin=fake_bin, runner=runner )

    assert type( raised.value ) is AgyCallError


def test_a_successful_exit_is_not_unavailable_whatever_standard_error_says( fake_bin, scratch ):
    runner = _FakeRunner( _Completed( returncode=0, stdout=REAL_STDOUT, stderr=UNAVAILABLE_STDERR[ 0 ] ) )

    assert run_agy( "p", model="m", workspace_dir=scratch, agy_bin=fake_bin, runner=runner ).response


def test_run_nonzero_exit_with_no_stderr_raises( fake_bin, scratch ):
    runner = _FakeRunner( _Completed( returncode=1, stdout="", stderr=None ) )

    with pytest.raises( AgyCallError, match=r"agy exited 1 \(model m\); stderr: $" ):
        run_agy( "p", model="m", workspace_dir=scratch, agy_bin=fake_bin, runner=runner )


def test_run_exit_zero_without_a_result_event_raises( fake_bin, scratch ):
    runner = _FakeRunner( _Completed( stdout="warning: ignoring unsupported stream input\n" ) )

    with pytest.raises( AgyCallError, match="no result event" ):
        run_agy( "p", model="m", workspace_dir=scratch, agy_bin=fake_bin, runner=runner )


def test_run_real_error_result_raises_with_agys_own_message( fake_bin, scratch ):
    runner = _FakeRunner( _Completed( stdout=REAL_ERROR_STDOUT ) )

    with pytest.raises( AgyCallError, match=r'agy result status ERROR \(model m\): stream input "user" message is missing' ):
        run_agy( "p", model="m", workspace_dir=scratch, agy_bin=fake_bin, runner=runner )


def test_run_failed_status_without_an_error_field_raises( fake_bin, scratch ):
    runner = _FakeRunner( _Completed( stdout=_result_stdout( status="CANCELLED" ) ) )

    with pytest.raises( AgyCallError, match=r"agy result status CANCELLED \(model m\): $" ):
        run_agy( "p", model="m", workspace_dir=scratch, agy_bin=fake_bin, runner=runner )


@pytest.mark.parametrize( "response", [ "", "  \n" ] )
def test_run_blank_answer_raises( fake_bin, scratch, response ):
    runner = _FakeRunner( _Completed( stdout=_result_stdout( response=response ) ) )

    with pytest.raises( AgyCallError, match="blank answer" ):
        run_agy( "p", model="m", workspace_dir=scratch, agy_bin=fake_bin, runner=runner )


# =========================================================================== #
# package surface
# =========================================================================== #
def test_package_exports_the_runtime_names():
    for name in agy_package.__all__:
        assert getattr( agy_package, name ) is getattr( runtime, name )

    assert len( agy_package.__all__ ) == 10
