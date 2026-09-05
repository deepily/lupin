"""
An ask must not be able to wait longer than the budget it was given.

THE DEFECT (row `97ff4426`). `consume_sse_stream` had two guards against a
stream that never finishes, and a stream can defeat BOTH AT ONCE:

  - the socket read timeout is PER-READ. Every byte received resets it, so it
    never fires while anything at all is arriving.
  - the client-side elapsed check is the FIRST STATEMENT OF THE LOOP BODY of
    `for line in response.iter_lines()`, so it can only run WHEN A COMPLETE
    LINE ARRIVES.

A stream that keeps sending bytes WITHOUT ever completing a line is therefore
watched by nothing, and the ask waits forever. Measured before the fix, three
arms, one variable, `timeout_seconds=10`:

    ack then a terminal frame at 2s   ->  returned  2.00s      (control)
    ack then silence                  ->  returned 20.02s      (read timeout fires)
    ack then bytes, never a line      ->  NEVER RETURNED, killed at 45s

SCOPE, AND IT IS NARROWER THAN THE INCIDENT. The third arm is a CAPABILITY
proof, not a reproduction of the 11:04 incident on row `97ff4426`. Every yield
in the ask generator ends with a blank line and that stream sends no keepalive,
so what produced sub-line writes that day is UNKNOWN and this file does not
claim it. What it pins is narrower and sufficient: an ask that CANNOT exceed its
budget costs `timeout_seconds`; one that can costs the whole session.

WHY THE TWO CONTROLS ARE NOT CEREMONY. A "fix" that simply closed the stream
early would satisfy the killer perfectly - it returns, promptly, every time.
`test_an_answer_inside_the_budget_is_still_returned` separates a deadline from a
guillotine, and the late-answer test proves the deadline is DERIVED FROM
`timeout_seconds` rather than hardcoded. Without them the killer passes a client
that is fast and wrong.

Venue: :7999 bucket. A loopback HTTP server on an ephemeral port; no database,
no fleet traffic, no notification row, nothing reaches a human. The killer costs
its own budget by construction (~6s) - that budget is the quantity under test.

See: row `97ff4426` - src/lupin_cli/notifications/notify_user_sync.py
"""

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from lupin_cli.notifications.notification_models import NotificationRequest
from lupin_cli.notifications.notify_user_sync import notify_user_sync

NID = "11111111-2222-3333-4444-555555555555"


def _server( behaviour ):
    """A loopback /api/notify speaking the real wire shape: CHUNKED, because the
    real endpoint is a Starlette StreamingResponse. An earlier cut of this
    harness used HTTP/1.0 with a close-delimited body; urllib3 then buffered the
    small ack flush, the ack never reached the parser, and the fixture quietly
    stopped reproducing "ack received, THEN ...". A fixture better-formed than
    the real producer measures the fixture."""

    class Handler( BaseHTTPRequestHandler ):
        protocol_version = "HTTP/1.1"

        def log_message( self, *args ):
            pass

        def do_POST( self ):
            self.send_response( 200 )
            self.send_header( "Content-Type", "text/event-stream" )
            self.send_header( "Transfer-Encoding", "chunked" )
            self.end_headers()
            self._frame( { "status": "ack", "notification_id": NID } )
            behaviour( self )

        def _frame( self, obj ):
            self._raw( f"data: {json.dumps( obj )}\n\n".encode() )

        def _raw( self, payload ):
            self.wfile.write( f"{len( payload ):X}\r\n".encode() + payload + b"\r\n" )
            self.wfile.flush()

    srv = ThreadingHTTPServer( ( "127.0.0.1", 0 ), Handler )
    threading.Thread( target=srv.serve_forever, daemon=True ).start()
    return srv


def _ask( srv, timeout_seconds, hard_cap=None ):
    """Drive one real ask against the loopback server.

    The call runs on a worker thread with a HARD CAP so that a client which
    never returns FAILS this test instead of HANGING it. That distinction is
    the whole reason the cap exists: the defect under test is an unbounded
    wait, so the naive shape of this guard inherits the very failure it is
    meant to report - a suite that hangs tells CI nothing and blocks everyone,
    while a suite that fails names the defect.
    """
    request = NotificationRequest(
        message         = "deadline guard - never reaches a human",
        response_type   = "yes_no",
        target_user     = "guard@example.com",
        timeout_seconds = timeout_seconds,
    )
    cap     = hard_cap if hard_cap is not None else timeout_seconds + 15
    box     = {}
    started = time.time()

    def _run():
        try:
            box[ "response" ] = notify_user_sync(
                request    = request,
                server_url = f"http://127.0.0.1:{srv.server_address[ 1 ]}",
                debug      = False,
            )
        except Exception as e:                     # pragma: no cover - reported below
            box[ "error" ] = e

    worker        = threading.Thread( target=_run )
    worker.daemon = True
    worker.start()
    worker.join( cap )

    if worker.is_alive():
        raise AssertionError(
            f"the ask did not return within {cap}s on a {timeout_seconds}s budget - "
            "it is waiting without a deadline, which is the unbounded wait of row "
            "97ff4426. Reported as a failure rather than left to hang, because a "
            "hanging guard tells you nothing and blocks the tier."
        )
    if "error" in box:
        raise box[ "error" ]                       # pragma: no cover - surfaced verbatim
    return box[ "response" ], time.time() - started


def _answer_after( seconds, value ):
    def behaviour( handler ):
        time.sleep( seconds )
        handler._frame( { "status": "responded", "response": value, "default_used": False } )
    return behaviour


def _dribble_forever( handler ):
    """Bytes that never complete a line. Each write resets the socket read
    timeout; `iter_lines` never yields, so the in-loop deadline check never
    evaluates. This is the shape that was unbounded."""
    for _ in range( 400 ):
        time.sleep( 0.25 )
        try:
            handler._raw( b"." )
        except Exception:
            return   # the client hung up, which is the whole point


@pytest.fixture
def serve():
    made = []

    def _make( behaviour ):
        srv = _server( behaviour )
        made.append( srv )
        return srv

    yield _make
    for srv in made:
        srv.shutdown()


class TestTheDeadlineIsReal:

    def test_a_stream_that_never_completes_a_line_cannot_outlive_the_deadline( self, serve ):
        """THE KILLER. Before the fix this did not return at all."""
        srv               = serve( _dribble_forever )
        response, elapsed = _ask( srv, timeout_seconds=1, hard_cap=20 )

        assert elapsed < 9, (
            f"the ask ran {elapsed:.1f}s on a 1s budget - a stream sending bytes "
            "without ever completing a line is outliving its deadline again, which "
            "is the unbounded wait row 97ff4426 was filed for."
        )
        assert response.response_value is None, (
            "a stream that never sent an answer produced one - this guard is "
            "measuring something other than the deadline."
        )


class TestTheDeadlineIsNotAGuillotine:

    def test_an_answer_inside_the_budget_is_still_returned( self, serve ):
        """CONTROL. Without this, a 'fix' that closes the stream immediately
        satisfies the killer perfectly and breaks every real ask."""
        srv               = serve( _answer_after( 0.2, "THE-ANSWER" ) )
        response, elapsed = _ask( srv, timeout_seconds=10 )

        assert response.response_value == "THE-ANSWER", (
            f"a prompt answer was lost (status={response.status!r}) - the deadline "
            "is cutting streams that were about to succeed."
        )
        assert elapsed < 5, f"a 0.2s answer took {elapsed:.1f}s to come back"

    def test_a_late_answer_well_inside_a_long_budget_is_still_returned( self, serve ):
        """CONTROL. The deadline must be DERIVED FROM `timeout_seconds`, never
        hardcoded. A fixed short cap passes the test above and fails here."""
        srv               = serve( _answer_after( 3, "LATE-BUT-IN-TIME" ) )
        response, elapsed = _ask( srv, timeout_seconds=30 )

        assert response.response_value == "LATE-BUT-IN-TIME", (
            f"an answer at 3s inside a 30s budget was lost (status={response.status!r}) "
            "- the deadline is not being derived from timeout_seconds."
        )
        assert 2.5 < elapsed < 8, f"expected a return near 3s, got {elapsed:.1f}s"
