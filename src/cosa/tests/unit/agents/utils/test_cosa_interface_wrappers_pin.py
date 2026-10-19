"""
Pins the four async wrappers every agent's cosa_interface module exposes.

The wrappers copy module-level identity onto a module-level dispatcher, then await one
dispatcher method with a fixed set of keyword arguments. Which keywords each module forwards
differs by module, so the table below is the spec of today's behaviour.
Every dispatcher is a fake; nothing is sent.
"""

import asyncio
import importlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

NOTIFY_BASE  = { "priority": "high", "abstract": "abs", "session_name": "ses", "job_id": "j", "queue_name": "q" }
ASK_BASE     = { "default": "yes", "timeout": 7, "abstract": "abs", "job_id": "j" }
FEEDBACK_BASE = { "timeout": 9, "job_id": "j" }
CHOICES_BASE = { "timeout": 11, "title": "T", "abstract": "abs", "job_id": "j" }

# module -> ( extras each wrapper forwards, pushes SESSION_NAME in notify_progress, wrapper names it has )
SPEC = {
    "cosa.agents.bug_fix_expediter.cosa_interface": {
        "notify": ( "progress_group_id", ), "ask": ( "priority", ), "feedback": ( "priority", "response_default" ),
        "choices": ( "priority", "response_default" ), "session": True,  "has": ( "notify", "ask", "feedback", "choices" ) },
    "cosa.agents.claude_code.cosa_interface": {
        "notify": (), "ask": (), "feedback": (), "choices": (), "session": False, "has": ( "notify", "ask" ) },
    "cosa.agents.deep_research.cosa_interface": {
        "notify": ( "progress_group_id", ), "ask": (), "feedback": (), "choices": ( "priority", ), "session": True,
        "has": ( "notify", "ask", "feedback", "choices" ) },
    "cosa.agents.podcast_generator.cosa_interface": {
        "notify": ( "progress_group_id", ), "ask": (), "feedback": (), "choices": ( "priority", ), "session": True,
        "has": ( "notify", "ask", "feedback", "choices" ) },
    "cosa.agents.presentation_generator.cosa_interface": {
        "notify": ( "progress_group_id", ), "ask": (), "feedback": (), "choices": ( "priority", ), "session": True,
        "has": ( "notify", "ask", "feedback", "choices" ) },
}
FUNCS = {
    "notify"  : ( "notify_progress",  "message",  NOTIFY_BASE,   True  ),
    "ask"     : ( "ask_confirmation", "question", ASK_BASE,      False ),
    "feedback": ( "get_feedback",     "prompt",   FEEDBACK_BASE, False ),
    "choices" : ( "present_choices",  "questions", CHOICES_BASE, False ),
}
CASES = [ ( mod, kind ) for mod, spec in SPEC.items() for kind in spec["has"] ]


def load( name ):
    return importlib.import_module( name )


def fake_dispatcher():
    d = MagicMock()
    d.notify_progress  = AsyncMock( return_value=None )
    d.ask_confirmation = AsyncMock( return_value=True )
    d.get_feedback     = AsyncMock( return_value="said" )
    d.present_choices  = AsyncMock( return_value={ "answers": {} } )
    return d


def first_arg( kind ):
    return [ { "question": "q", "options": [] } ] if kind == "choices" else "text"


def call( ci, kind, **kwargs ):
    fn_name, _, base, _ = FUNCS[ kind ]
    return asyncio.run( getattr( ci, fn_name )( first_arg( kind ), **{ **base, **kwargs } ) )


@pytest.mark.parametrize( "mod, kind", CASES )
def test_the_base_arguments_are_forwarded_with_the_extras_this_module_forwards( mod, kind ):
    ci, spec, d = load( mod ), SPEC[ mod ], fake_dispatcher()
    fn_name, _, base, _ = FUNCS[ kind ]
    with patch.object( ci, "_dispatcher", d ):
        call( ci, kind )
    awaited = getattr( d, fn_name ).await_args
    assert awaited.args == ( first_arg( kind ), )
    expected = dict( base )
    expected.update( { extra: None for extra in spec[ kind ] } )
    assert awaited.kwargs == expected


@pytest.mark.parametrize( "mod, kind", CASES )
def test_every_extra_this_module_forwards_arrives_unchanged( mod, kind ):
    ci, spec, d = load( mod ), SPEC[ mod ], fake_dispatcher()
    fn_name, _, base, _ = FUNCS[ kind ]
    extras = { name: f"v-{ name }" for name in spec[ kind ] }
    with patch.object( ci, "_dispatcher", d ):
        call( ci, kind, **extras )
    assert getattr( d, fn_name ).await_args.kwargs == { **base, **extras }


@pytest.mark.parametrize( "mod, kind", CASES )
def test_the_return_value_is_the_dispatchers( mod, kind ):
    ci, d = load( mod ), fake_dispatcher()
    fn_name = FUNCS[ kind ][ 0 ]
    with patch.object( ci, "_dispatcher", d ):
        result = call( ci, kind )
    assert result is ( None if kind == "notify" else getattr( d, fn_name ).return_value )


@pytest.mark.parametrize( "mod, kind", CASES )
def test_an_extra_this_module_does_not_forward_is_refused( mod, kind ):
    ci, spec, d = load( mod ), SPEC[ mod ], fake_dispatcher()
    unsupported = [ x for x in ( "priority", "response_default", "progress_group_id" ) if x not in spec[ kind ] and x not in FUNCS[ kind ][ 2 ] ]
    assert unsupported
    for name in unsupported:
        for value in ( "x", None ):
            with patch.object( ci, "_dispatcher", d ), pytest.raises( TypeError ):
                call( ci, kind, **{ name: value } )


@pytest.mark.parametrize( "mod, kind", CASES )
def test_identity_is_read_from_the_module_globals_on_every_call( mod, kind ):
    ci, spec, d = load( mod ), SPEC[ mod ], fake_dispatcher()
    for n in ( 1, 2 ):
        with patch.object( ci, "_dispatcher", d ), patch.object( ci, "SENDER_ID", f"sid-{ n }" ), \
             patch.object( ci, "TARGET_USER", f"user-{ n }@x" ), \
             patch.object( ci, "SESSION_NAME", f"sess-{ n }", create=True ):
            call( ci, kind )
        assert d.sender_id == f"sid-{ n }"
        assert d.target_user == f"user-{ n }@x"
        if kind == "notify" and spec[ "session" ]:
            assert d.session_name == f"sess-{ n }"


@pytest.mark.parametrize( "mod, kind", [ c for c in CASES if c[ 1 ] != "notify" ] )
def test_only_notify_progress_copies_the_session_name( mod, kind ):
    ci, d = load( mod ), fake_dispatcher()
    d.session_name = "untouched"
    with patch.object( ci, "_dispatcher", d ), patch.object( ci, "SESSION_NAME", "changed", create=True ):
        call( ci, kind )
    assert d.session_name == "untouched"


def test_claude_code_notify_progress_never_touches_the_session_name():
    ci, d = load( "cosa.agents.claude_code.cosa_interface" ), fake_dispatcher()
    d.session_name = "untouched"
    with patch.object( ci, "_dispatcher", d ):
        call( ci, "notify" )
    assert d.session_name == "untouched"


def test_a_module_global_assigned_at_run_time_is_what_the_next_call_sends():
    ci, d = load( "cosa.agents.deep_research.cosa_interface" ), fake_dispatcher()
    old = ci.SENDER_ID
    try:
        with patch.object( ci, "_dispatcher", d ):
            ci.SENDER_ID = "assigned-later"
            call( ci, "ask" )
    finally:
        ci.SENDER_ID = old
    assert d.sender_id == "assigned-later"


@pytest.mark.parametrize( "mod, kind", CASES )
def test_the_wrapper_is_a_coroutine_function_under_its_public_name( mod, kind ):
    import inspect
    ci = load( mod )
    fn = getattr( ci, FUNCS[ kind ][ 0 ] )
    assert inspect.iscoroutinefunction( fn ) and fn.__name__ == FUNCS[ kind ][ 0 ]
    assert list( inspect.signature( fn ).parameters )[ 0 ] == FUNCS[ kind ][ 1 ]
