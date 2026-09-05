#!/usr/bin/env python3
"""
test_task_store_read_timeout_is_not_unreachable.py — a read timeout and an unreachable server
are OPPOSITE facts, and the client used to report both with the same word.

Store row `96cf5cec`. Found by María 🌸 2026-09-05 while approving two workers' rows; mechanism
diagnosed by Krishna 🦚; option (c) ruled by Mr. Radio 🦉 the same day.

=== THE INCIDENT ===

A transition out of `not_approved` blocks server-side while a human is asked to approve the
promotion — INI `task approval promotion ask timeout seconds`, 120s today. The client gives up
at `TASK_STORE_TIMEOUT_SECONDS`, 10s. So on that one edge the client ALWAYS quits first, and it
reported its own abandonment as `server_unreachable`.

The server was reachable, was working, and in all three measured cases the write COMMITTED.
Three managers read "unreachable" as "the approval failed"; one DM'd a worker that a live row
was still blocked and had to retract it. Measured off `lupin_db_dev`: rows `9c3b817a`,
`bfcea79d` and `88f4dfdb` each carry exactly ONE `not_approved->queued` event.

⚠️ THAT EVENT-LOG COUNT ANSWERS ONE QUESTION AND NOT THE OTHER. It settles whether the retry
double-wrote — it did not — and it CANNOT corroborate the promotion-ask mechanism, because a 422
rejection writes no event by construction, so every rival explanation predicts one write too.
Whether the delay was the human ask or plain server load is still unseparated.

=== WHY THE CLAUSE ORDER IS THE WHOLE FIX ===

`requests` raises `ReadTimeout` only after the connection was established and the request was
SENT. `ConnectTimeout` means it never arrived. They are different objects and they license
opposite conclusions — and the exception hierarchy makes the naive catch wrong:

    ConnectTimeout  -> subclasses ConnectionError AND Timeout   ("certainly did not land")
    ReadTimeout     -> subclasses Timeout alone                 ("may have landed")

⇒ Catching `Timeout` would sweep up `ConnectTimeout` and label the ONE case we can still be
certain about as indeterminate. That is why `ReadTimeout` is caught SPECIFICALLY and first.

=== WHY BOTH DIRECTIONS ARE ASSERTED ===

María's own acceptance condition: "an admission that succeeds must not return an error shape,
and a genuinely refused transition must still refuse. Both arms — otherwise 'return success' is
satisfied by never refusing anything." The same trap applies here one level down: a change that
simply stopped ever saying `server_unreachable` would satisfy the first case in this file and be
strictly worse than the defect. The connect-failure cases are what stop that.
"""

import requests

from lupin_mcp.task_store_tools import task_store_request, TASK_STORE_TIMEOUT_SECONDS


BASE = "http://localhost:7999"
KEY  = "probe-key-not-a-real-credential"
PATH = "/api/tasks/00000000-1111-2222-3333-444444444444/transition"


class _FakeResponse:
    """Ensures: the minimum of `requests.Response` that `task_store_request` reads."""

    def __init__( self, status_code, payload ):
        self.status_code = status_code
        self._payload    = payload
        self.text        = str( payload )

    def json( self ):
        return self._payload


def _raise( exc ):
    """Ensures: returns a `requests.request` stand-in that raises `exc` when called."""
    def _stub( *args, **kwargs ):
        raise exc
    return _stub


# ------------------------------------------------------------------ the case the row is about

def test_a_read_timeout_is_not_reported_as_an_unreachable_server( monkeypatch ):
    """
    🔴 THE GUARD. Collapse the two clauses back into one `except RequestException` and this goes
    red by name: the reason becomes `server_unreachable`, which is the defect.

    The assertion is on the REASON rather than on the detail text, because the reason is what a
    caller branches on. A detail that explains the situation under a reason that says the server
    was unreachable is still telling the caller the operation failed.
    """
    monkeypatch.setattr(
        requests, "request",
        _raise( requests.exceptions.ReadTimeout( "HTTPConnectionPool(host='localhost', port=7999): "
                                                 "Read timed out. (read timeout=10.0)" ) )
    )
    out = task_store_request( "POST", PATH, BASE, KEY, json_body={ "to_status": "queued" } )

    assert out[ "status" ] == "error"
    assert out[ "reason" ] == "server_read_timeout", (
        f"a read timeout is still being reported as {out[ 'reason' ]!r} — the server WAS reached "
        "and the write may have committed"
    )
    assert out[ "outcome_indeterminate" ] is True, (
        "the caller is not being told the outcome is unknown, which is the one fact it needs"
    )


def test_the_read_timeout_detail_refuses_the_immediate_re_read_remedy( monkeypatch ):
    """
    ⚠️ THE REMEDY THE DETAIL MUST NOT LEAVE A READER TO INVENT.

    "Re-read the row after a timeout" is the obvious next move and María had already told two
    workers to do it before measuring that it does not work: on row `88f4dfdb` a read taken
    immediately after the timeout returned the PRE-WRITE value on a write that landed anyway.
    A detail that says "outcome unknown" and stops sends the reader straight to that check.
    """
    monkeypatch.setattr( requests, "request", _raise( requests.exceptions.ReadTimeout( "boom" ) ) )
    detail = task_store_request( "POST", PATH, BASE, KEY )[ "detail" ]

    assert "IMMEDIATE re-read is NOT a reliable check" in detail, (
        f"the detail does not warn against the obvious wrong remedy:\n{detail}"
    )
    assert str( TASK_STORE_TIMEOUT_SECONDS ) in detail, (
        f"the detail never says how long this client waited:\n{detail}"
    )


# ------------------------------------- the controls, without which the case above is worthless

def test_a_connect_timeout_still_reports_an_unreachable_server( monkeypatch ):
    """
    🔴 THE CONTROL THAT MATTERS MOST, AND IT GUARDS AN EXCEPTION-HIERARCHY TRAP.

    `ConnectTimeout` subclasses BOTH `ConnectionError` and `Timeout`. A fix written as
    `except requests.exceptions.Timeout` — the natural thing to type — would catch it here and
    report the outcome as INDETERMINATE. It is not indeterminate: the request never reached the
    server, so it certainly did not land, and that certainty is worth keeping.
    """
    monkeypatch.setattr( requests, "request", _raise( requests.exceptions.ConnectTimeout( "no route" ) ) )
    out = task_store_request( "GET", PATH, BASE, KEY )

    assert out[ "reason" ] == "server_unreachable", (
        f"a CONNECT timeout is being reported as {out[ 'reason' ]!r} — it never reached the "
        "server and certainly did not land, and that certainty has been thrown away"
    )
    assert "outcome_indeterminate" not in out


def test_a_plain_connection_error_still_reports_an_unreachable_server( monkeypatch ):
    """
    THE SECOND CONTROL. Without these two, "stop saying server_unreachable" is satisfied by
    never saying it — which would be strictly worse than the defect this file closes.
    """
    monkeypatch.setattr( requests, "request", _raise( requests.exceptions.ConnectionError( "refused" ) ) )
    out = task_store_request( "GET", PATH, BASE, KEY )

    assert out[ "reason" ] == "server_unreachable"
    assert out[ "status" ] == "error"


def test_a_successful_call_still_returns_the_body_verbatim( monkeypatch ):
    """THE SUCCESS PATH IS UNTOUCHED — an error-shape change must not reach it."""
    body = { "item": { "id": "abc", "status": "queued" }, "event": { "id": 1 } }
    monkeypatch.setattr( requests, "request", lambda *a, **k: _FakeResponse( 200, body ) )

    assert task_store_request( "POST", PATH, BASE, KEY ) == body


def test_a_genuine_rejection_still_refuses( monkeypatch ):
    """
    MARÍA'S ACCEPTANCE CONDITION, VERBATIM: "a genuinely refused transition must still refuse."

    The 422 path carries the server's `errors` list UNEDITED — the no-confabulation rule — and a
    change to the timeout clauses must not disturb it.
    """
    detail = { "errors": [ "no-op transition 'queued'->'queued' rejected — not a legal edge" ] }
    monkeypatch.setattr( requests, "request", lambda *a, **k: _FakeResponse( 422, { "detail": detail } ) )
    out = task_store_request( "POST", PATH, BASE, KEY )

    assert out[ "http_status" ] == 422
    assert out[ "errors" ] == detail[ "errors" ]
