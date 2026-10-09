#!/usr/bin/env python3
"""
THE GUARD EXISTS — DOES ANY VERB ACTUALLY CALL IT?

`_refuse_borrowed_identity` can be complete, correct, fully covered and reached by nothing,
and every test that exercises the helper itself stays green. That is this repo's
§ IMPLEMENTED BUT NOT INSTALLED: revert one `if refusal is not None: return refusal` line
and the helper's own suite does not move.

So this file does not test the helper. It drives the ASSEMBLED verbs — the `FunctionTool`
objects the MCP server actually exposes — with this process's identity forced to a guess,
and asserts two things per verb:

    1. the verb returns the refusal, and
    2. it never reached its implementation.

⚠️ THE SECOND HALF IS NOT DECORATION. A verb that returned the refusal AFTER writing would
satisfy the first assertion perfectly and still have filed the row under a colleague. The
sentinel impl is what separates "refused" from "refused, eventually".

⚠️ AND THE NEGATIVE CONTROL CARRIES THE WHOLE FILE. Every arm here would pass against a
guard that refused unconditionally — which would take the fleet down. The `ppid` arm proves
the refusal discriminates rather than merely fires.

The verb list is not written here. It is found. Every tool the MCP server registers is either wired or exempt.
Wired means its function calls `_refuse_borrowed_identity`, found by reading the function's syntax tree.
Exempt means it is named in the exemption table with a reason. A tool in neither is a red test.
A new verb therefore cannot land unclassified. `podcast_for_rick` once did: it called the refusal and sat off the old list.

VENUE: :7999-eligible — monkeypatched module globals, no server, no network, no writes.
"""
import ast
import asyncio
import inspect
import textwrap

import pytest

from lupin_mcp import cosa_voice_mcp as m
from lupin_cli.claude_code.hooks.lib import session_bridge as sb


class _Reached( Exception ):
    """Raised by the sentinel impl. Its arrival IS the assertion that the guard let go."""


# Tools that do not call the refusal, each with the reason. A reason is a claim to check, not a pass.
# "RULING OWED" marks a tool that writes under the seat's name and has no ruling yet (follow-up row).
EXEMPT = {
    "ask_multiple_choice"   : "asks the user; the sender id rides the notification (not read further)",
    "ask_open_ended_batch"  : "asks the user; the sender id rides the notification (not read further)",
    "ask_yes_no"            : "asks the user; the sender id rides the notification (not read further)",
    "converse"              : "speaks to the user; the sender id rides the notification (not read further)",
    "notify"                : "announces to the user; the sender id rides the notification (not read further)",
    "set_session_topic"     : "sets this session's topic through the notification path (not read further)",
    "check_exists"          : "reuse-wiki lookup, per its docstring (not read further)",
    "fetch_similar"         : "reuse-wiki lookup, per its docstring (not read further)",
    "read_capability"       : "reuse-wiki page read, per its docstring (not read further)",
    "replay"                : "reuse-wiki receipt re-check, per its docstring (not read further)",
    "commons_read"          : "read-only (docstring tag READ)",
    "commons_who"           : "read-only (docstring tag READ)",
    "dm_get"                : "read-only (docstring tag READ)",
    "dm_list"               : "read-only (docstring tag READ)",
    "list_spawned_sessions" : "read-only (docstring tag READ)",
    "task_get"              : "read-only (docstring tag READ)",
    "task_promotion_status" : "read-only (docstring tag READ)",
    "task_query"            : "read-only (docstring tag READ)",
    "get_session_info"      : "returns this session's own identity and writes nothing",
    "enable_speakerphone"   : "user-initiated session setting (docstring: USER-ONLY INITIATION)",
    "disable_speakerphone"  : "user-initiated session setting (docstring: USER-ONLY INITIATION)",
    "request_persona"       : "user-initiated session setting (docstring: USER-INITIATED ONLY)",
    "spawn_sessions"        : "RULING OWED: host-side spawn of sessions by this manager; not read further",
    "commons_post"          : "RULING OWED: posts under the seat's session id and persona, no refusal call",
    "commons_ask_async"     : "RULING OWED: posts under the seat's name; not read further",
    "commons_ask_sync"      : "RULING OWED: posts under the seat's name; not read further",
    "dm_respond"            : "RULING OWED: a dm_send with mandatory threading, no refusal call",
}

# Wired tools whose implementation is not a module symbol named <tool>_impl, so a sentinel cannot be placed.
# They are proved by the first-statement check alone; calling them unwired would run real code.
NO_IMPL_SYMBOL = { "self_respin", "dismiss_sessions" }

TOOLS = asyncio.run( m.mcp.get_tools() )


def public_name( key ):
    """Return the name the refusal is given: `_dm_send_fn` is registered, `dm_send` is said."""
    return key.removeprefix( "_" ).removesuffix( "_fn" )


def _function_tree( fn ):
    """Return the syntax tree of a tool's function definition."""
    return ast.parse( textwrap.dedent( inspect.getsource( fn ) ) ).body[ 0 ]


def _refusal_calls( fn ):
    """Return the string arguments of every call to the refusal inside a tool's function."""
    return [ node.args[ 0 ].value for node in ast.walk( _function_tree( fn ) )
             if isinstance( node, ast.Call ) and isinstance( node.func, ast.Name )
             and node.func.id == "_refuse_borrowed_identity" and node.args and isinstance( node.args[ 0 ], ast.Constant ) ]


WIRED = sorted( key for key, tool in TOOLS.items() if _refusal_calls( tool.fn ) )


def _impl_name( key ):
    """Return the module symbol that does the tool's work, or None when there is none by name."""
    for name in ( f"{public_name( key )}_impl", f"_{public_name( key )}_impl" ):
        if hasattr( m, name ): return name
    return None


def _kwargs_for( fn ):
    """Build otherwise-valid arguments for the required parameters, one dummy per annotation."""
    dummies = { str : "x", int : 1, bool : False, list : [ "x" ], dict : { "title" : "x" } }
    kwargs  = { }
    for name, param in inspect.signature( fn ).parameters.items():
        if param.default is not inspect.Parameter.empty: continue
        kwargs[ name ] = dummies.get( getattr( param.annotation, "__origin__", param.annotation ), "x" )
    return kwargs


VERBS = [ ( key, _impl_name( key ), _kwargs_for( TOOLS[ key ].fn ) ) for key in WIRED if _impl_name( key ) is not None ]


def _call( verb, kwargs ):
    """Call a verb and run the coroutine an offloaded (async) verb returns."""
    result = TOOLS[ verb ].fn( **kwargs )
    return asyncio.run( result ) if inspect.iscoroutine( result ) else result


def test_the_discovery_found_the_verbs_it_is_meant_to_find():
    """Pin the measured floor (12 wired, 39 registered): a loop over nothing passes."""
    assert len( TOOLS ) >= 39 and len( WIRED ) >= 12
    assert "podcast_for_rick" in WIRED and "_dm_send_fn" in WIRED


def test_every_registered_tool_is_wired_or_exempt():
    unclassified = sorted( set( TOOLS ) - set( WIRED ) - set( EXEMPT ) )
    assert not unclassified, f"registered but neither wired nor exempt: {unclassified}; call the refusal or add it to EXEMPT with a reason"


def test_no_tool_is_both_wired_and_exempt():
    assert not sorted( set( WIRED ) & set( EXEMPT ) )


def test_every_exemption_names_a_registered_tool_and_gives_a_reason():
    assert not sorted( set( EXEMPT ) - set( TOOLS ) ), "an exemption for a tool that is not registered"
    assert not [ key for key, reason in EXEMPT.items() if not reason.strip() ]


def test_the_tools_without_an_impl_symbol_are_exactly_the_ones_named():
    found = { public_name( key ) for key in WIRED if _impl_name( key ) is None }
    assert found == NO_IMPL_SYMBOL


@pytest.mark.parametrize( "key", WIRED )
def test_wired_means_the_refusal_is_the_first_statement_and_names_the_tool( key ):
    """
    Read the syntax tree, not the text.

    The first statement after the docstring is `refusal = _refuse_borrowed_identity( "<name>" )`.
    The next is the early return, so nothing runs before the refusal.
    """
    body = _function_tree( TOOLS[ key ].fn ).body
    if isinstance( body[ 0 ], ast.Expr ) and isinstance( body[ 0 ].value, ast.Constant ): body = body[ 1: ]
    first, second = body[ 0 ], body[ 1 ]
    assert isinstance( first, ast.Assign ) and ast.unparse( first.value ) == f"_refuse_borrowed_identity('{public_name( key )}')", \
        f"{key}: first statement is {ast.unparse( first )!r}"
    assert isinstance( second, ast.If ) and "return refusal" in ast.unparse( second ), f"{key}: no early return after the refusal"


@pytest.fixture
def borrowed( monkeypatch ):
    monkeypatch.setattr( m, "SESSION_ID_SOURCE", sb.SOURCE_CWD_FALLBACK )


@pytest.fixture
def owned( monkeypatch ):
    monkeypatch.setattr( m, "SESSION_ID_SOURCE", sb.SOURCE_PPID )


@pytest.mark.parametrize( "verb,impl,kwargs", VERBS, ids=[ v[ 0 ] for v in VERBS ] )
def test_the_verb_REFUSES_and_never_reaches_its_impl( verb, impl, kwargs, borrowed, monkeypatch ):
    def _sentinel( *a, **k ):
        raise _Reached( f"{verb} reached {impl} while wearing a borrowed identity" )

    monkeypatch.setattr( m, impl, _sentinel )

    result = _call( verb, kwargs )

    assert isinstance( result, dict ), f"{verb} returned {type(result)}, not a refusal dict"
    assert result[ "reason" ] == "borrowed_identity", f"{verb} was not refused: {result}"
    assert public_name( verb ) in result[ "detail" ]


@pytest.mark.parametrize( "verb,impl,kwargs", VERBS, ids=[ v[ 0 ] for v in VERBS ] )
def test_NEGATIVE_CONTROL_a_definitive_identity_reaches_the_impl( verb, impl, kwargs, owned, monkeypatch ):
    """
    🔴 WITHOUT THIS, A GUARD THAT REFUSED EVERY WRITE PASSES THE WHOLE FILE ABOVE.
    """
    def _sentinel( *a, **k ):
        raise _Reached( "reached" )

    monkeypatch.setattr( m, impl, _sentinel )

    with pytest.raises( _Reached ):
        _call( verb, kwargs )


def test_dm_send_is_wired_too( borrowed, monkeypatch ):
    """
    dm_send is the verb that misattributes a CONVERSATION rather than a row — a peer reads
    a message signed by a colleague who never sent it, and nothing in the thread says so.
    """
    def _sentinel( *a, **k ):
        raise _Reached( "dm_send reached _dm_send_impl while wearing a borrowed identity" )

    monkeypatch.setattr( m, "_dm_send_impl", _sentinel )

    result = m._dm_send_fn( recipient="maria", body="b" )
    assert result[ "reason" ] == "borrowed_identity"


def test_dm_send_NEGATIVE_CONTROL( owned, monkeypatch ):
    """
    The real `_commons_persona_fields` is left in place deliberately: stubbing it thin was
    enough to make this arm fail PAST the guard, which reads like the guard blocking and is
    the opposite. Let the verb run its own body and stop it at the transport.
    """
    def _sentinel( *a, **k ):
        raise _Reached( "reached" )

    monkeypatch.setattr( m, "_dm_send_impl", _sentinel )

    with pytest.raises( _Reached ):
        m._dm_send_fn( recipient="maria", body="b" )


def test_the_REFUSAL_NAMES_THE_SEAT_IT_WOULD_HAVE_WRITTEN_AS( borrowed ):
    """
    A refusal that says only "refused" leaves the reader unable to tell a real problem from
    a misconfiguration. This one names the identity it would have used and what to do.
    """
    detail = m._refuse_borrowed_identity( "task_create" )[ "detail" ]

    assert m.SENDER_ID in detail
    assert "CLAUDE_SESSION_ID" in detail, "the refusal does not say how to fix it"
