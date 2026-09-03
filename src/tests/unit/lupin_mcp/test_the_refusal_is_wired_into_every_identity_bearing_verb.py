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

VENUE: :7999-eligible — monkeypatched module globals, no server, no network, no writes.
"""
import pytest

from lupin_mcp import cosa_voice_mcp as m
from lupin_cli.claude_code.hooks.lib import session_bridge as sb


class _Reached( Exception ):
    """Raised by the sentinel impl. Its arrival IS the assertion that the guard let go."""


# ( verb attribute, the impl symbol it must not reach, kwargs that are otherwise valid )
VERBS = [
    ( "task_create",     "task_create_impl",     dict( item_class="task", title="t", project="lupin" ) ),
    ( "task_transition", "task_transition_impl", dict( task_id="abc12345", to_status="done" ) ),
    ( "task_correlate",  "task_correlate_impl",  dict( task_id="abc12345", correlation_key="k" ) ),
    ( "task_amend",      "task_amend_impl",      dict( task_id="abc12345", note="n" ) ),
]


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

    result = getattr( m, verb ).fn( **kwargs )

    assert isinstance( result, dict ), f"{verb} returned {type(result)}, not a refusal dict"
    assert result[ "reason" ] == "borrowed_identity", f"{verb} was not refused: {result}"
    assert verb in result[ "detail" ]


@pytest.mark.parametrize( "verb,impl,kwargs", VERBS, ids=[ v[ 0 ] for v in VERBS ] )
def test_NEGATIVE_CONTROL_a_definitive_identity_reaches_the_impl( verb, impl, kwargs, owned, monkeypatch ):
    """
    🔴 WITHOUT THIS, A GUARD THAT REFUSED EVERY WRITE PASSES THE WHOLE FILE ABOVE.
    """
    def _sentinel( *a, **k ):
        raise _Reached( "reached" )

    monkeypatch.setattr( m, impl, _sentinel )

    with pytest.raises( _Reached ):
        getattr( m, verb ).fn( **kwargs )


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
