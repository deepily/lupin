#!/usr/bin/env python3
"""
STAGE 4 — the caller's side of an asynchronous promotion.

Row `3493ae9b`, design §5.4. María 🌸's binding requirement: a 202 that leaves the manager
unable to learn the outcome is the same defect with the waiting moved somewhere nobody
looks.

🔴 TWO CLAIMS, AND THEY ARE SEPARATE:
    1. a caller that said nothing sends a BYTE-IDENTICAL request to today's
    2. a caller that opted in gets, on resolution, the SAME ANSWER a 200 carried

⚠️ AND ONE THIS FILE DELIBERATELY DOES NOT MAKE: that the common case is invisible.
Nobody has measured how long Rick takes to answer; that claim was made once on this row
and STRUCK as unmeasured. The budget arm asserts the SHAPE of the answer, never its rarity.

VENUE: `:7999`. No network — every request is injected, every clock is faked. No monopoly.
"""
import os
import re
import sys

import pytest

_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from lupin_mcp import task_store_tools as tst

BASE, KEY = "http://localhost:7999", "test-key"
TICKET    = "4288dd53-6779-460a-88bd-a7365fb734b2"
TASK      = "11111111-2222-3333-4444-555555555555"

SYNCHRONOUS_200 = { "item": { "id": TASK, "status": "queued" }, "event": { "id": 1 } }
ACCEPTED_202    = {
    "status"      : "awaiting_human_approval",
    "ticket_id"   : TICKET,
    "task_id"     : TASK,
    "to_status"   : "queued",
    "resolves_by" : "2026-09-06T12:03:00+00:00",
    "check_with"  : "task_promotion_status",
}


def _ticket( state, **extra ):
    body = { "ticket_id": TICKET, "task_id": TASK, "state": state,
             "refusal": None, "response_body": None }
    body.update( extra )
    return body


class _Transport:
    """
    ⚠️ IT HONOURS THE METHOD rather than returning one canned body, because the arms below
    turn on WHICH endpoint was called and in what order. A transport answering the same
    thing regardless would make every assertion here unfalsifiable.
    """
    def __init__( self, post_body, ticket_bodies=() ):
        self.post_body     = post_body
        self.ticket_bodies = list( ticket_bodies )
        self.calls         = []

    def __call__( self, method, path, api_base_url, api_key, json_body=None, params=None,
                  timeout=None ):
        self.calls.append( ( method, path, json_body ) )
        if method == "POST":   return self.post_body
        if self.ticket_bodies: return self.ticket_bodies.pop( 0 )
        return _ticket( "pending" )


@pytest.fixture
def transport( monkeypatch ):
    def _install( post_body, ticket_bodies=() ):
        t = _Transport( post_body, ticket_bodies )
        monkeypatch.setattr( tst, "task_store_request", t )
        return t
    return _install


def _transition( **kwargs ):
    return tst.task_transition_impl(
        api_base_url=BASE, api_key=KEY, actor="mr radio 21dff055",
        task_id=TASK, to_status="queued", **kwargs )


def _fast_poll( budget=5.0 ):
    """The real poll, with its clock and its sleep replaced so no arm ever waits."""
    ticks = iter( [ 0.5 * i for i in range( 0, 60 ) ] )
    return lambda base, key, accepted: tst._poll_promotion_ticket(
        base, key, accepted, budget_seconds=budget, interval_seconds=0.0,
        sleep_fn=lambda s: None, clock_fn=ticks.__next__ )


# ═══════════════════════════════════════════════════════════════════════════════════
# 1 · THE CALLER THAT SAID NOTHING
# ═══════════════════════════════════════════════════════════════════════════════════

def test_a_caller_that_says_nothing_sends_no_asynchronous_field_at_all( transport ):
    """
    🔴 OMITTED, NOT SENT AS null. The server's field is Optional[StrictBool] defaulting to
    None, so an explicit null would be accepted too — but "the request is unchanged" is a
    stronger claim than "the request is equivalent", and it is the one a reviewer can
    check by eye.
    """
    t = transport( SYNCHRONOUS_200 )
    _transition()
    assert "asynchronous" not in t.calls[ 0 ][ 2 ], (
        f"a caller that never mentioned it sent "
        f"{t.calls[0][2].get('asynchronous')!r} — today's callers no longer send today's "
        f"request" )


def test_a_synchronous_200_is_returned_verbatim_and_nothing_is_polled( transport ):
    t = transport( SYNCHRONOUS_200 )
    assert _transition() == SYNCHRONOUS_200
    assert [ c[ 0 ] for c in t.calls ] == [ "POST" ], "a synchronous answer was polled anyway"


def test_the_field_IS_sent_when_the_caller_asked( transport ):
    """POSITIVE CONTROL. Without it, the omission arm is satisfied by never sending it."""
    t = transport( SYNCHRONOUS_200 )
    _transition( asynchronous=True )
    assert t.calls[ 0 ][ 2 ][ "asynchronous" ] is True


# ═══════════════════════════════════════════════════════════════════════════════════
# 2 · THE 202, AND THE ANSWER IT EVENTUALLY GIVES
# ═══════════════════════════════════════════════════════════════════════════════════

def test_an_approved_ticket_hands_back_the_body_a_synchronous_200_CARRIED( transport ):
    """
    🔴 `response_body`, NOT A RE-READ, AND THAT IS WHY THE COLUMN EXISTS. A poll that
    re-read the row would get a moved `updated_ts`, an event looked up rather than handed
    over, and under a concurrent writer an item describing a LATER state than the event
    beside it (design §5.4.1).
    """
    t = transport( ACCEPTED_202, [
        _ticket( "pending" ),
        _ticket( "approved", response_body=SYNCHRONOUS_200 ) ] )
    got = _transition( asynchronous=True, poll_fn=_fast_poll() )
    assert got == SYNCHRONOUS_200, f"the caller got {got!r} instead of the 200 body"
    assert [ c[ 0 ] for c in t.calls ] == [ "POST", "GET", "GET" ]


def test_a_refusal_comes_back_in_the_shape_todays_403_HAS( transport ):
    """A caller handling the synchronous refusal must not learn a second vocabulary."""
    transport( ACCEPTED_202, [ _ticket( "refused", refusal="Rick answered no." ) ] )
    got = _transition( asynchronous=True, poll_fn=_fast_poll() )
    assert got[ "status" ]      == "error"
    assert got[ "http_status" ] == 403
    assert got[ "detail" ]      == "Rick answered no."


def test_SUPERSEDED_is_not_reported_as_a_refusal( transport ):
    """
    🔴 THE DISCRIMINATING ARM. Rick approved and the row moved underneath. Reporting that
    as a refusal would put a decision in his mouth he did not make — the one thing this
    gate forbids. It must NOT carry a 403, because 403 is the shape meaning "you were told
    no".
    """
    transport( ACCEPTED_202, [
        _ticket( "superseded", refusal="no longer legal (the row is now 'done')" ) ] )
    got = _transition( asynchronous=True, poll_fn=_fast_poll() )
    assert got[ "reason" ]      == "promotion_superseded"
    assert got[ "http_status" ] is None, "a superseded promotion was dressed up as a refusal"
    assert "done" in got[ "detail" ]


def test_a_budget_that_runs_out_returns_the_202_WITH_A_WAY_BACK( transport ):
    """
    ⚠️ THIS ASSERTS THE SHAPE OF THE ANSWER, NEVER ITS RARITY. Whether it is the common
    case is UNKNOWN — nobody has measured Rick's answer latency — and a guard implying
    otherwise would be selling an unmeasured claim.

    What it pins: the caller is not left with nothing. It gets the ticket id and the NAME
    of the verb to come back with, which is the difference between an asynchronous call
    and a dropped one.
    """
    transport( ACCEPTED_202, [ _ticket( "pending" ) ] * 8 )
    got = _transition( asynchronous=True, poll_fn=_fast_poll( budget=1.0 ) )
    assert got[ "status" ]     == "awaiting_human_approval"
    assert got[ "ticket_id" ]  == TICKET
    assert got[ "check_with" ] == "task_promotion_status", (
        "the caller was told to wait and not told what to come back with" )


def test_a_transport_failure_MID_POLL_is_not_an_answer_about_the_promotion( transport ):
    """
    The ticket is persisted; one bad read says nothing about whether Rick answered. The
    BUDGET ends the wait, not a hiccup — treating an error as a resolution would report a
    promotion's outcome from a network blip.
    """
    transport( ACCEPTED_202, [
        { "status": "error", "reason": "server_unreachable", "detail": "boom" },
        _ticket( "approved", response_body=SYNCHRONOUS_200 ) ] )
    assert _transition( asynchronous=True, poll_fn=_fast_poll() ) == SYNCHRONOUS_200


def test_approved_with_no_stored_body_REFUSES_rather_than_inventing_one( transport ):
    """
    🔴 DECLINE RATHER THAN NO-OP. A ticket saying approved that stored nothing is a
    server-side defect; manufacturing an empty { item, event } would hand the caller a
    confident answer nobody computed.
    """
    transport( ACCEPTED_202, [ _ticket( "approved" ) ] )
    got = _transition( asynchronous=True, poll_fn=_fast_poll() )
    assert got[ "status" ] == "error"
    assert got[ "reason" ] == "promotion_resolved_without_a_response_body"


# ═══════════════════════════════════════════════════════════════════════════════════
# 3 · THE TWO SPELLINGS, AND THE VERB THAT MUST BE INSTALLED
# ═══════════════════════════════════════════════════════════════════════════════════

def test_the_client_marker_matches_the_one_the_server_actually_emits():
    """
    🔴 TWO RECORDS OF ONE FACT DRIFT, AND THIS MAKES THE DRIFT LOUD. The client cannot
    import the server's constant — pulling `cosa.rest.*` into the MCP process would drag
    SQLAlchemy and the web stack into a subprocess with no business hosting them, the same
    reason the promotion gate's ask goes at `notify_user_sync` rather than at an MCP verb.
    So the string is written twice and pinned here.

    ⚠️ THE FIRST ASSERTION IS THE POSITIVE CONTROL. A regex finding nothing would make the
    second vacuous, and "no hits" and "no agreement" are different facts wanting opposite
    fixes.
    """
    root   = os.environ.get( "LUPIN_ROOT", os.getcwd() )
    source = open( os.path.join( root, "src", "cosa", "rest", "routers", "tasks.py" ),
                   encoding="utf-8" ).read()
    emitted = re.findall( r'"status"\s*:\s*"(awaiting_human_approval)"', source )

    assert emitted, (
        'found no \'"status": "awaiting_human_approval"\' in the router — this guard did '
        'not fail, it was unable to look. Either the 202 body changed shape or the '
        'pattern is wrong, and those want opposite fixes.' )
    assert tst.AWAITING_HUMAN_APPROVAL in emitted, (
        f"the client watches for {tst.AWAITING_HUMAN_APPROVAL!r} and the server emits "
        f"{set( emitted )!r} — a 202 would reach the caller unpolled, as if it were a "
        f"completed transition" )


def test_the_named_verb_is_REGISTERED_on_the_MCP_server():
    """
    🔴 THE IMPLEMENTED-BUT-NOT-INSTALLED ARM. `task_promotion_status_impl` can be complete,
    correct and fully covered while no MCP verb exposes it — and then the 202 names a verb
    that does not exist, which is worse than naming nothing.

    ⚠️ IT READS THE SOURCE rather than importing `cosa_voice_mcp`, deliberately: importing
    that module starts its stdout-watcher daemon thread, which poisons every
    stdout-parsing test sharing the process.
    """
    root   = os.environ.get( "LUPIN_ROOT", os.getcwd() )
    source = open( os.path.join( root, "src", "lupin_mcp", "cosa_voice_mcp.py" ),
                   encoding="utf-8" ).read()
    assert "def task_promotion_status(" in source, "the verb is not defined"
    marker = source.index( "def task_promotion_status(" )
    assert "@mcp.tool" in source[ max( 0, marker - 200 ):marker ], (
        "task_promotion_status is defined but not decorated with @mcp.tool — it exists in "
        "the file and not on the server, so the 202 names a verb no caller can reach" )


def test_the_transition_verb_actually_forwards_the_opt_in():
    """
    The same class of arm one level up: the parameter can exist on the verb and never
    reach the impl, and every other test here would still pass.
    """
    root   = os.environ.get( "LUPIN_ROOT", os.getcwd() )
    source = open( os.path.join( root, "src", "lupin_mcp", "cosa_voice_mcp.py" ),
                   encoding="utf-8" ).read()
    call = source[ source.index( "return task_transition_impl(" ): ][ :900 ]
    assert re.search( r"asynchronous\s*=\s*asynchronous", call ), (
        "task_transition accepts `asynchronous` and does not pass it on — the caller opts "
        "in, the server never hears about it, and the request is silently synchronous" )
