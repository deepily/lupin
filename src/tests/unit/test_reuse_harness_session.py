"""
Unit tests of the session port.

The command is faked, never the real `claude`. Most tests use a recording runner.
One group starts a real subprocess: a small script that behaves as the CLI does about deny rules.
It lists a tool in its init event only when no deny rule names it, then declines to call anything.
That group runs the arm proof of the harness through the port, so the switch is shown end to end against the fake.
Named gap: nothing here starts the real CLI; the pilot (plan 3, section 7.4) does.
"""
import json
import os
import stat
import sys

import pytest

from lupin_mcp.reuse_harness import arms
from lupin_mcp.reuse_harness import errors as err
from lupin_mcp.reuse_harness import session

HANDLE = { "url" : "http://127.0.0.1:18267", "container" : "rrun-server-aaaa", "db_name" : "rrun_aaaa" }
WITH    = arms.build_session_config( arms.ARM_WITH, "claude-opus-5-5" )
WITHOUT = arms.build_session_config( arms.ARM_WITHOUT, "claude-opus-5-5" )


def tool_use( name, call_id="t1", **input ):
    """Return an assistant event that calls a tool."""
    return { "type" : "assistant", "message" : { "content" : [ { "type" : "tool_use", "id" : call_id, "name" : name, "input" : input } ] } }


def tool_result( call_id="t1", content="ok", is_error=False ):
    """Return a user event carrying a tool result."""
    return { "type" : "user", "message" : { "content" : [ { "type" : "tool_result", "tool_use_id" : call_id, "content" : content, "is_error" : is_error } ] } }


ALL_TOOLS = [ "Bash", "Read", *[ arms.DENY_RULES[ surface ] for surface in arms.SURFACES[ :3 ] ], "Skill" ]


def init( tools=None, skills=None, **extra ):
    """Return the init event of a session offering the given tools and skills (all by default)."""
    return { "type" : "system", "subtype" : "init", "tools" : ALL_TOOLS if tools is None else tools, "skills" : [ "reuse-reviewer" ] if skills is None else skills, **extra }


def stream( *events, first="default" ):
    """Join events into a stream-json output after an init event, with two stray lines."""
    head = [ init() ] if first == "default" else ( [] if first is None else [ first ] )
    return "\n".join( [ "warning: not json", "[1, 2]" ] + [ json.dumps( event ) for event in head + list( events ) ] )


PROBE_OK  = stream()
NOTHING   = init( tools=[ "Bash", "Read" ], skills=[], slash_commands=[] )


class Runner:
    """A runner that records calls and answers a queue of ( code, output ) pairs."""

    def __init__( self, *answers ):
        """Keep the answers."""
        self.answers = list( answers ) or [ ( 0, PROBE_OK ) ]
        self.calls   = []

    def __call__( self, argv, env=None, cwd=None, timeout=None ):
        """Record the call and answer."""
        self.calls.append( { "argv" : argv, "env" : env, "cwd" : cwd, "timeout" : timeout } )
        return self.answers.pop( 0 ) if len( self.answers ) > 1 else self.answers[ 0 ]


class Clock:
    """A clock that moves a fixed step each time it is read."""

    def __init__( self, step=3600.0 ):
        """Choose the step in seconds."""
        self.now, self.step = 0.0, step

    def __call__( self ):
        """Return the time, then move on."""
        value = self.now
        self.now += self.step
        return value


def make( *answers, step=3600.0, **options ):
    """Return ( Sessions, runner ), bound to a worktree and a server."""
    runner  = Runner( *answers )
    sessions = session.Sessions( "notify-key-value", runner=runner, clock=Clock( step ), environ={ "PATH" : "/bin" }, **options )
    sessions.bind( "/wt/run1", HANDLE )
    return sessions, runner


def code_of( call ):
    """Return the code of the HarnessError a call raises."""
    with pytest.raises( err.HarnessError ) as caught: call()
    return caught.value.code


def test_events_of_keeps_only_json_objects_in_order():
    assert session.events_of( stream( { "type" : "a" }, { "type" : "b" } ) ) == [ init(), { "type" : "a" }, { "type" : "b" } ]


def test_blocks_of_reads_list_content_of_assistant_and_user_messages_only():
    events = [ { "type" : "system", "message" : { "content" : [ { "type" : "tool_use" } ] } }, { "type" : "user", "message" : { "content" : "plain text" } },
               { "type" : "assistant", "message" : { "content" : [ "str", { "type" : "text" }, { "type" : "tool_use", "id" : "x" } ] } }, { "type" : "result" } ]
    assert session.blocks_of( events, "tool_use" ) == [ { "type" : "tool_use", "id" : "x" } ]


def blind( *events ):
    """Return a stream whose init event offers none of the surfaces, so only a call can answer."""
    return stream( *events, first=NOTHING )


@pytest.mark.parametrize( "surface", arms.SURFACES[ :3 ] )
def test_a_tool_surface_the_init_event_offers_is_answered_even_when_the_model_never_called_it( surface ):
    assert session.surface_answered( stream(), surface ) is True


@pytest.mark.parametrize( "surface", arms.SURFACES[ :3 ] )
def test_a_tool_surface_the_init_event_leaves_out_is_not_answered_whatever_the_model_did_or_declined_to_do( surface ):
    assert session.surface_answered( blind(), surface ) is False
    assert session.surface_answered( blind( tool_use( "Bash", command="ls" ), tool_result() ), surface ) is False


@pytest.mark.parametrize( "surface", arms.SURFACES[ :3 ] )
def test_a_tool_surface_missing_from_the_init_event_is_still_answered_when_the_session_called_it_and_was_not_refused( surface ):
    assert session.surface_answered( blind( tool_use( arms.DENY_RULES[ surface ] ), tool_result() ), surface ) is True


def test_a_call_whose_result_is_a_refusal_is_not_answered_but_a_tool_error_about_arguments_is():
    name = arms.DENY_RULES[ arms.SURFACE_FETCH_SIMILAR ]
    assert session.surface_answered( blind( tool_use( name ), tool_result( content="Permission to use this tool has been denied", is_error=True ) ), arms.SURFACE_FETCH_SIMILAR ) is False
    assert session.surface_answered( blind( tool_use( name ), tool_result( content="language is required", is_error=True ) ), arms.SURFACE_FETCH_SIMILAR ) is True


def test_a_call_with_no_result_yet_counts_as_answered_and_an_earlier_refusal_is_not_outweighed_by_a_later_good_call():
    name = arms.DENY_RULES[ arms.SURFACE_READ_CAPABILITY ]
    assert session.surface_answered( blind( tool_use( name ) ), arms.SURFACE_READ_CAPABILITY ) is True
    refused_then_ok = blind( tool_use( name, "a" ), tool_result( "a", "denied", True ), tool_use( name, "b" ), tool_result( "b" ) )
    assert session.surface_answered( refused_then_ok, arms.SURFACE_READ_CAPABILITY ) is False


def test_the_reviewer_is_offered_when_the_skill_or_command_list_names_it_with_or_without_a_prefix_and_a_slash():
    for listing in ( { "skills" : [ "reuse-reviewer" ] }, { "skills" : [ "plugin:reuse-reviewer" ] }, { "slash_commands" : [ "/reuse-reviewer" ] } ):
        assert session.surface_answered( stream( first=init( tools=[ "Skill" ], **{ "skills" : [], "slash_commands" : [], **listing } ) ), arms.SURFACE_REVIEWER ) is True
    for listing in ( { "skills" : [ "simplify", "reuse-reviewer-extra" ] }, {} ):
        assert session.surface_answered( stream( first=init( tools=[ "Skill" ], **{ "skills" : [], "slash_commands" : [], **listing } ) ), arms.SURFACE_REVIEWER ) is False


def test_the_reviewer_call_is_the_skill_tool_naming_the_reviewer_and_no_other_skill():
    assert session.surface_answered( blind( tool_use( "Skill", skill="reuse-reviewer" ), tool_result() ), arms.SURFACE_REVIEWER ) is True
    assert session.surface_answered( blind( tool_use( "Skill", skill="simplify" ), tool_result() ), arms.SURFACE_REVIEWER ) is False
    assert session.surface_answered( blind( tool_use( "Skill" ), tool_result() ), arms.SURFACE_REVIEWER ) is False


@pytest.mark.parametrize( "output", [ "", "not json at all", stream( first=None ), stream( first={ "type" : "system", "subtype" : "other", "tools" : [] } ),
                                      stream( first={ "type" : "system", "subtype" : "init" } ), stream( first={ "type" : "system", "subtype" : "init", "tools" : "Bash" } ) ] )
def test_a_session_output_with_no_usable_init_event_is_refused_because_a_denied_tool_and_a_declined_call_look_alike( output ):
    with pytest.raises( err.HarnessError ) as caught: session.surface_answered( output, arms.SURFACE_CHECK_EXISTS )
    assert caught.value.code == err.PROBE_BLIND


def test_a_probe_whose_output_has_no_init_event_ends_in_probe_blind_and_not_in_a_denied_verdict():
    sessions, _ = make( ( 0, "no events here" ) )
    assert code_of( lambda: sessions.probe( WITHOUT, arms.SURFACE_CHECK_EXISTS ) ) == err.PROBE_BLIND


def test_bind_derives_one_session_id_per_container_and_resets_the_counts():
    sessions, _ = make( ( 0, PROBE_OK ) )
    first = sessions.session_id
    sessions.slices, sessions.stops = 3, 1
    sessions.bind( "/wt/run1", HANDLE )
    other = session.Sessions( "k", environ={} )
    other.bind( "/wt/run2", dict( HANDLE, container="rrun-server-bbbb" ) )
    assert ( sessions.session_id, sessions.slices, sessions.stops ) == ( first, 0, 0 ) and other.session_id != first and len( first ) == 36


def test_probe_asks_for_the_surface_in_the_bound_tree_without_storing_the_session_and_with_hooks_off():
    sessions, runner = make( ( 0, stream( tool_use( arms.DENY_RULES[ arms.SURFACE_CHECK_EXISTS ] ), tool_result() ) ) )
    assert sessions.probe( WITH, arms.SURFACE_CHECK_EXISTS ) is True
    call = runner.calls[ 0 ]
    assert call[ "argv" ][ :3 ] == [ "claude", "-p", session.PROBE_PROMPTS[ arms.SURFACE_CHECK_EXISTS ] ] and "--no-session-persistence" in call[ "argv" ]
    assert call[ "cwd" ] == "/wt/run1" and call[ "timeout" ] == session.PROBE_TIMEOUT
    assert json.loads( call[ "argv" ][ call[ "argv" ].index( "--settings" ) + 1 ] ) == { "disableAllHooks" : True }
    assert "--disallowedTools" not in call[ "argv" ] and "--session-id" not in call[ "argv" ]


def test_the_without_arm_passes_exactly_its_four_deny_rules_and_the_with_arm_passes_none():
    sessions, runner = make( ( 0, PROBE_OK ) )
    sessions.probe( WITHOUT, arms.SURFACE_REVIEWER )
    argv = runner.calls[ 0 ][ "argv" ]
    assert argv[ argv.index( "--disallowedTools" ) + 1 ].split( "," ) == [ arms.DENY_RULES[ surface ] for surface in arms.SURFACES ]


def test_the_two_arms_start_the_same_command_but_for_the_deny_flag():
    sessions, runner = make( ( 0, PROBE_OK ) )
    sessions.probe( WITH, arms.SURFACE_REVIEWER )
    sessions.probe( WITHOUT, arms.SURFACE_REVIEWER )
    plain, denied = runner.calls[ 0 ][ "argv" ], runner.calls[ 1 ][ "argv" ]
    index = denied.index( "--disallowedTools" )
    assert denied[ :index ] + denied[ index + 2: ] == plain


def test_the_mcp_config_is_passed_to_both_arms_alike_and_exclusively_when_given():
    sessions, runner = make( ( 0, PROBE_OK ), mcp_config="/cfg/mcp.json" )
    sessions.probe( WITH, arms.SURFACE_CHECK_EXISTS )
    sessions.probe( WITHOUT, arms.SURFACE_CHECK_EXISTS )
    for call in runner.calls: assert call[ "argv" ][ call[ "argv" ].index( "--mcp-config" ) : call[ "argv" ].index( "--mcp-config" ) + 3 ] == [ "--mcp-config", "/cfg/mcp.json", "--strict-mcp-config" ]


def test_the_key_and_server_url_are_in_the_environment_and_never_in_the_arguments():
    sessions, runner = make( ( 0, PROBE_OK ) )
    sessions.probe( WITH, arms.SURFACE_CHECK_EXISTS )
    call = runner.calls[ 0 ]
    assert ( call[ "env" ][ "EXPERIMENT_SERVER_URL" ], call[ "env" ][ "EXPERIMENT_NOTIFY_API_KEY" ], call[ "env" ][ "PATH" ] ) == ( HANDLE[ "url" ], "notify-key-value", "/bin" )
    assert "notify-key-value" not in " ".join( call[ "argv" ] )


def test_a_command_that_cannot_start_is_refused_for_a_probe_and_a_slice():
    sessions, _ = make( ( 127, "FileNotFoundError: claude" ) )
    assert code_of( lambda: sessions.probe( WITH, arms.SURFACE_CHECK_EXISTS ) ) == err.SESSION_START
    assert code_of( lambda: sessions.work( WITH, "/wt/run1", HANDLE, 5 ) ) == err.SESSION_START


def test_the_first_slice_starts_the_session_with_the_brief_and_later_slices_resume_it():
    sessions, runner = make( ( 0, PROBE_OK ) )
    sessions.work( WITH, "/wt/run1", HANDLE, 10 )
    sessions.work( WITH, "/wt/run1", HANDLE, 10 )
    first, second = runner.calls[ 0 ][ "argv" ], runner.calls[ 1 ][ "argv" ]
    assert first[ 2 ] == session.BRIEF and first[ -2: ] == [ "--session-id", sessions.session_id ]
    assert second[ 2 ] == session.RESUME_PROMPT and second[ -2: ] == [ "--resume", sessions.session_id ]


def test_a_slice_is_limited_to_the_slice_length_or_the_hours_left_whichever_is_less_and_runs_in_the_given_tree():
    sessions, runner = make( ( 0, PROBE_OK ), slice_hours=2.0 )
    sessions.work( WITH, "/wt/other", HANDLE, 10 )
    sessions.work( WITH, "/wt/other", HANDLE, 0.5 )
    assert [ call[ "timeout" ] for call in runner.calls ] == [ 7200, 1800 ] and runner.calls[ 0 ][ "cwd" ] == "/wt/other"


def test_seat_hours_are_the_wall_time_times_the_seats():
    sessions, _ = make( ( 0, PROBE_OK ), step=5400.0, seats=2 )
    assert sessions.work( WITH, "/wt/run1", HANDLE, 10 )[ "seat_hours" ] == 3.0


def test_a_session_that_stops_on_its_own_twice_in_a_row_has_finished_and_a_timeout_resets_the_count():
    sessions, _ = make( ( 0, PROBE_OK ), ( 127, "TimeoutExpired: ran out" ), ( 0, PROBE_OK ), ( 0, PROBE_OK ) )
    assert [ sessions.work( WITH, "/wt/run1", HANDLE, 10 )[ "finished" ] for _ in range( 4 ) ] == [ False, False, False, True ]


def test_a_timed_out_slice_is_not_a_failure():
    sessions, _ = make( ( 127, "TimeoutExpired: ran out" ) )
    assert sessions.work( WITH, "/wt/run1", HANDLE, 10 ) == { "seat_hours" : 1.0, "finished" : False }


def test_a_slice_that_ends_with_an_error_before_its_time_is_refused_with_the_output_tail():
    sessions, _ = make( ( 1, "\n".join( f"line {n}" for n in range( 40 ) ) ) )
    with pytest.raises( err.HarnessError ) as caught: sessions.work( WITH, "/wt/run1", HANDLE, 10 )
    assert caught.value.code == err.SESSION_FAILED and "line 39" in caught.value.detail and "line 5 " not in caught.value.detail and sessions.slices == 0


def test_the_defaults_are_the_real_runner_clock_and_environment():
    import time
    from lupin_mcp.reuse_harness import commands
    sessions = session.Sessions( "k" )
    assert ( sessions.runner, sessions.clock, sessions.environ ) == ( commands.run_command, time.monotonic, os.environ )


FAKE_CLAUDE = '''#!{python}
import json, sys
argv = sys.argv
denied = argv[ argv.index( "--disallowedTools" ) + 1 ].split( "," ) if "--disallowedTools" in argv else []
tools = [ "Bash", "Read", "Skill" ] + [ tool for tool in ( "mcp__cosa-voice__check_exists", "mcp__cosa-voice__fetch_similar", "mcp__cosa-voice__read_capability" ) if tool not in denied ]
skills = [] if "Skill(reuse-reviewer)" in denied else [ "reuse-reviewer" ]
print( json.dumps( {{ "type" : "system", "subtype" : "init", "tools" : tools, "skills" : skills }} ) )
print( json.dumps( {{ "type" : "result", "subtype" : "success", "is_error" : False }} ) )
'''


@pytest.fixture
def fake_claude( tmp_path ):
    """Write a fake CLI that honours deny rules, and return its path."""
    path = tmp_path / "claude"
    path.write_text( FAKE_CLAUDE.format( python=sys.executable ) )
    path.chmod( path.stat().st_mode | stat.S_IXUSR )
    return str( path )


@pytest.mark.parametrize( "arm", [ arms.ARM_WITH, arms.ARM_WITHOUT ] )
def test_the_arm_proof_of_the_harness_passes_through_the_port_against_a_real_subprocess( fake_claude, arm ):
    sessions = session.Sessions( "k", claude=fake_claude, environ=dict( os.environ ) )
    sessions.bind( os.getcwd(), HANDLE )
    config   = arms.build_session_config( arm, "claude-opus-5-5" )
    answers  = arms.verify_arm( arm, config, sessions )
    assert answers == { surface : arm == arms.ARM_WITH for surface in arms.SURFACES }


def test_a_missing_command_ends_a_real_probe_in_session_start():
    sessions = session.Sessions( "k", claude="/no/such/claude", environ=dict( os.environ ) )
    sessions.bind( os.getcwd(), HANDLE )
    assert code_of( lambda: sessions.probe( WITH, arms.SURFACE_CHECK_EXISTS ) ) == err.SESSION_START


def test_the_probe_and_the_working_session_run_in_the_same_permission_mode_with_the_same_deny_rules():
    sessions, runner = make( ( 0, PROBE_OK ) )
    sessions.probe( WITHOUT, arms.SURFACE_CHECK_EXISTS )
    sessions.work( WITHOUT, "/wt/run1", HANDLE, 5 )
    probe, work = runner.calls[ 0 ][ "argv" ], runner.calls[ 1 ][ "argv" ]
    for argv in ( probe, work ):
        assert argv[ argv.index( "--permission-mode" ) + 1 ] == session.PERMISSION_MODE == "bypassPermissions"
        assert argv[ argv.index( "--disallowedTools" ) + 1 ].split( "," ) == [ arms.DENY_RULES[ surface ] for surface in arms.SURFACES ]


def test_a_chosen_permission_mode_reaches_the_probe_and_the_working_session_alike():
    sessions, runner = make( ( 0, PROBE_OK ), permission_mode="acceptEdits" )
    sessions.probe( WITH, arms.SURFACE_CHECK_EXISTS )
    sessions.work( WITH, "/wt/run1", HANDLE, 5 )
    assert [ call[ "argv" ][ call[ "argv" ].index( "--permission-mode" ) + 1 ] for call in runner.calls ] == [ "acceptEdits", "acceptEdits" ]


def test_the_setting_sources_flag_carries_the_configs_sources_and_not_a_fixed_list():
    sessions, runner = make( ( 0, PROBE_OK ) )
    sessions.probe( WITH, arms.SURFACE_CHECK_EXISTS )
    sessions.probe( dict( WITH, setting_sources=[ "project" ] ), arms.SURFACE_CHECK_EXISTS )
    values = [ call[ "argv" ][ call[ "argv" ].index( "--setting-sources" ) + 1 ] for call in runner.calls ]
    assert values == [ "project,local", "project" ] and "user" not in values[ 0 ]
