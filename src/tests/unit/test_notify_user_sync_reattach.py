"""
The re-attach-after-stream-death path in `notify_user_sync` — row `e2099400`.

WHY THIS BLOCK. `_poll_notification_response` was entirely dark and
`_reattach_after_stream_death` only partly reached. Together they are what
happens when the SSE stream dies while a human is still deciding — the one path
where the difference between "they answered" and "the server made something up"
has to be got right, because the caller cannot tell them apart afterwards.

THE INVARIANT THE MODULE STATES ABOUT ITSELF, and what these tests hold it to:
the outcome is decided on **`responded_at IS NOT NULL`**, never on `state`
moving and never on `response_value` merely being present. A server that has
manufactured a default on an offline user DOES populate `response_value` —
reading that field as proof of an answer is how a machine default gets reported
as a human decision. That is the single most consequential line in the file and
it now has a test that fails if it moves.

WHAT IS PINNED:

· **`responded_at` set ⇒ `responded`, exit 0, `default_used=False`.** A real
  answer.

· **`responded_at` NULL with a value ⇒ `expired`, exit 2, `default_used=True`,
  `is_timeout=True`.** A manufactured default, and never `responded`. The
  distinguishing test drives both shapes and asserts they do not agree — a
  version reading `response_value` alone would satisfy either one on its own.

· **At least one poll ALWAYS fires, even at a zero or negative budget** (the
  module's E-V3). A dying stream at the deadline still gets its terminal check;
  without it an answer that landed in the last second is thrown away.

· **A missing ack id is surfaced loudly, not silently swallowed** —
  `reattach_state="reattach_unavailable"` with exit 1, so it is assertable
  rather than indistinguishable from a clean timeout.

· **`_poll_notification_response` never raises and never lies.** A non-200, a
  transport failure, and an unparseable body all come back as `None` — the same
  answer as "no row yet", which is what the caller's loop is written against.

· **The wrapper falls back rather than dying when config is unreadable**, and
  retries only on a timeout, only when asked, and never after a real answer.

⚠️ NO WALL-CLOCK WAITING. `time.sleep` is patched out and budgets are set to
zero where a timeout is under test; a test that actually slept would spend the
unit tier's budget proving nothing about the logic.

See: row e2099400
"""

from unittest.mock import MagicMock, patch

import requests

from lupin_cli.notifications.notify_user_sync import (
    _poll_notification_response,
    _reattach_after_stream_death,
    notify_user_sync,
)
from lupin_cli.notifications.notification_models import (
    NotificationRequest,
    NotificationResponse,
    ResponseType,
)


MODULE = "lupin_cli.notifications.notify_user_sync"

NID  = "notif-1234"
BASE = "http://localhost:7999"
HDRS = { "Authorization": "Bearer x" }


def _reattach( row_sequence, remaining=30.0, notification_id=NID ):
    """Drive the re-attach loop with a scripted sequence of poll results."""
    calls = { "n": 0 }

    def poll( nid ):
        i = calls[ "n" ]
        calls[ "n" ] += 1
        return row_sequence[ i ] if i < len( row_sequence ) else row_sequence[ -1 ]

    with patch( f"{MODULE}.time.sleep" ):
        result = _reattach_after_stream_death(
            notification_id, remaining, BASE, HDRS, poll_fn=poll, poll_interval=0.0 )
    return result, calls[ "n" ]


class TestTheAnsweredVersusManufacturedDistinction:
    """The whole point of the module's §3 invariant."""

    def test_a_landed_answer_is_reported_as_responded( self ):
        result, _ = _reattach( [ { "responded_at": "2026-08-26T12:00:00Z",
                                   "response_value": "yes" } ] )
        assert result.status         == "responded"
        assert result.exit_code      == 0
        assert result.response_value == "yes"
        assert result.default_used is False

    def test_a_manufactured_default_is_never_reported_as_responded( self ):
        """responded_at NULL with a value present = the server made it up."""
        result, _ = _reattach( [ { "responded_at": None, "response_value": "no" } ] )
        assert result.status         == "expired"
        assert result.exit_code      == 2
        assert result.response_value == "no"
        assert result.default_used is True
        assert result.is_timeout is True

    def test_the_two_do_not_agree_on_a_single_field( self ):
        """THE CONTROL. Both rows carry a response_value; an implementation
        reading that field as proof of an answer would return the same thing for
        both, and a human decision would be indistinguishable from a machine
        default at the caller."""
        landed, _ = _reattach( [ { "responded_at": "2026-08-26T12:00:00Z",
                                   "response_value": "yes" } ] )
        made_up, _ = _reattach( [ { "responded_at": None, "response_value": "yes" } ] )
        assert ( landed.status, landed.exit_code, landed.default_used ) != \
               ( made_up.status, made_up.exit_code, made_up.default_used )

    def test_a_dict_shaped_value_is_unwrapped_on_the_landed_route( self ):
        """The server may send {"value": …}; the caller expects the scalar."""
        result, _ = _reattach( [ { "responded_at": "2026-08-26T12:00:00Z",
                                   "response_value": { "value": "yes" } } ] )
        assert result.response_value == "yes"

    def test_a_dict_shaped_value_is_unwrapped_on_the_default_route_too( self ):
        result, _ = _reattach( [ { "responded_at": None,
                                   "response_value": { "value": "no" } } ] )
        assert result.response_value == "no"


class TestThePollingLoop:

    def test_it_keeps_polling_while_the_row_is_unanswered( self ):
        """responded_at NULL and no value = not answered YET, not a verdict."""
        result, polls = _reattach( [
            { "responded_at": None, "response_value": None },
            { "responded_at": None, "response_value": None },
            { "responded_at": "2026-08-26T12:00:00Z", "response_value": "yes" },
        ] )
        assert result.status == "responded"
        assert polls == 3

    def test_a_missing_row_is_not_a_verdict_either( self ):
        """None means "no row yet" — a poll against a server mid-restart must
        not be read as an expiry."""
        result, polls = _reattach( [ None, { "responded_at": "t", "response_value": "yes" } ] )
        assert result.status == "responded"
        assert polls == 2

    def test_an_exhausted_budget_expires_with_no_value( self ):
        result, _ = _reattach( [ { "responded_at": None, "response_value": None } ],
                               remaining=0.0 )
        assert result.status         == "expired"
        assert result.exit_code      == 2
        assert result.is_timeout is True
        assert result.response_value is None

    def test_one_poll_always_fires_even_at_a_zero_budget( self ):
        """E-V3, stated in the docstring. An answer that landed in the last
        second is still there to be found."""
        result, polls = _reattach( [ { "responded_at": "t", "response_value": "yes" } ],
                                   remaining=0.0 )
        assert polls == 1
        assert result.status == "responded"

    def test_one_poll_fires_even_at_a_negative_budget( self ):
        _, polls = _reattach( [ { "responded_at": None, "response_value": None } ],
                              remaining=-5.0 )
        assert polls == 1

    def test_every_return_carries_the_armed_state( self ):
        """`reattach_state` is what makes the path assertable from outside."""
        for rows in ( [ { "responded_at": "t", "response_value": "y" } ],
                      [ { "responded_at": None, "response_value": "y" } ],
                      [ { "responded_at": None, "response_value": None } ] ):
            result, _ = _reattach( rows, remaining=0.0 )
            assert result.reattach_state == "reattach_armed"


class TestNoAckIdMeansNoReattach:

    def test_it_returns_unavailable_rather_than_pretending_to_poll( self ):
        result = _reattach_after_stream_death( None, 30.0, BASE, HDRS )
        assert result.reattach_state == "reattach_unavailable"
        assert result.status         == "stream_error"
        assert result.exit_code      == 1

    def test_unavailable_is_distinguishable_from_a_plain_timeout( self ):
        """Both are failures; only one of them means the client never learned
        the ask's id. Collapsing them hides a client-side defect."""
        unavailable = _reattach_after_stream_death( None, 30.0, BASE, HDRS )
        timed_out, _ = _reattach( [ { "responded_at": None, "response_value": None } ],
                                  remaining=0.0 )
        assert unavailable.reattach_state != timed_out.reattach_state
        assert unavailable.exit_code      != timed_out.exit_code

    def test_an_empty_string_id_is_treated_as_absent( self ):
        result = _reattach_after_stream_death( "", 30.0, BASE, HDRS )
        assert result.reattach_state == "reattach_unavailable"


class TestThePollRead:
    """`_poll_notification_response` — never raises, never invents a row."""

    def _get( self, **kwargs ):
        with patch( f"{MODULE}.requests.get", **kwargs ) as get:
            return _poll_notification_response( NID, BASE, HDRS ), get

    def test_a_200_returns_the_parsed_row( self ):
        reply = MagicMock( status_code=200 )
        reply.json.return_value = { "state": "responded", "responded_at": "t" }
        row, _ = self._get( return_value=reply )
        assert row == { "state": "responded", "responded_at": "t" }

    def test_a_non_200_returns_none( self ):
        row, _ = self._get( return_value=MagicMock( status_code=404 ) )
        assert row is None

    def test_a_transport_failure_returns_none_rather_than_raising( self ):
        row, _ = self._get( side_effect=requests.exceptions.ConnectionError( "down" ) )
        assert row is None

    def test_an_unparseable_body_returns_none_rather_than_raising( self ):
        reply = MagicMock( status_code=200 )
        reply.json.side_effect = ValueError( "not json" )
        row, _ = self._get( return_value=reply )
        assert row is None

    def test_it_asks_the_response_by_id_endpoint( self ):
        reply = MagicMock( status_code=200 )
        reply.json.return_value = {}
        _, get = self._get( return_value=reply )
        assert get.call_args.args[ 0 ] == f"{BASE}/api/notifications/response/{NID}"

    def test_it_sends_the_headers_it_was_given( self ):
        """Without them the endpoint answers 401 and every poll reads as "no
        row yet" — a silent, permanent no-answer."""
        reply = MagicMock( status_code=200 )
        reply.json.return_value = {}
        _, get = self._get( return_value=reply )
        assert get.call_args.kwargs[ "headers" ] == HDRS


def _request( timeout=5 ):
    return NotificationRequest(
        message         = "Approve?",
        response_type   = ResponseType( "yes_no" ),
        target_user     = "someone@example.com",
        timeout_seconds = timeout,
    )


class TestTheWrapperSurvivesBrokenConfig:

    def test_a_config_failure_does_not_stop_the_send( self ):
        """The config supplies a base URL and an API key; when it raises, the
        env-var fallback is used and the send still happens."""
        sent = MagicMock( return_value=NotificationResponse(
            response_value="yes", exit_code=0, status="responded" ) )
        with patch( f"{MODULE}.get_api_config", side_effect=RuntimeError( "no file" ) ), \
             patch( f"{MODULE}._send_sync_notification", sent ):
            result = notify_user_sync( _request(), server_url="http://localhost:8000" )
        assert result.status == "responded"
        assert sent.call_args.args[ 4 ] == "http://localhost:8000"   # base_url
        assert sent.call_args.args[ 5 ] == "fallback"                # env

    def test_a_trailing_slash_is_stripped_from_the_fallback_url( self ):
        """Otherwise every constructed path carries a double slash."""
        sent = MagicMock( return_value=NotificationResponse(
            response_value="yes", exit_code=0, status="responded" ) )
        with patch( f"{MODULE}.get_api_config", side_effect=RuntimeError( "no file" ) ), \
             patch( f"{MODULE}._send_sync_notification", sent ):
            notify_user_sync( _request(), server_url="http://localhost:8000/" )
        assert sent.call_args.args[ 4 ] == "http://localhost:8000"


class TestRetryOnTimeout:

    def _run( self, responses, **kwargs ):
        sent = MagicMock( side_effect=responses )
        with patch( f"{MODULE}.get_api_config", side_effect=RuntimeError( "no file" ) ), \
             patch( f"{MODULE}._send_sync_notification", sent ):
            result = notify_user_sync( _request(), server_url=BASE, **kwargs )
        return result, sent

    def test_a_timeout_is_retried_with_a_longer_budget( self ):
        timed_out = NotificationResponse( response_value=None, exit_code=2,
                                          status="expired", is_timeout=True )
        answered  = NotificationResponse( response_value="yes", exit_code=0,
                                          status="responded" )
        result, sent = self._run( [ timed_out, answered ], retry_on_timeout=True,
                                  max_attempts=2, backoff_multiplier=2.0 )
        assert result.status == "responded"
        assert sent.call_count == 2
        assert sent.call_args_list[ 0 ].args[ 0 ].timeout_seconds == 5
        assert sent.call_args_list[ 1 ].args[ 0 ].timeout_seconds == 10

    def test_a_timeout_is_not_retried_when_retrying_is_off( self ):
        timed_out = NotificationResponse( response_value=None, exit_code=2,
                                          status="expired", is_timeout=True )
        result, sent = self._run( [ timed_out ], retry_on_timeout=False, max_attempts=2 )
        assert result.is_timeout is True
        assert sent.call_count == 1

    def test_an_answer_is_never_retried( self ):
        """Retrying a delivered answer would ask the user the same question
        twice and keep only the second reply."""
        answered = NotificationResponse( response_value="yes", exit_code=0,
                                         status="responded" )
        result, sent = self._run( [ answered ], retry_on_timeout=True, max_attempts=3 )
        assert result.status == "responded"
        assert sent.call_count == 1

    def test_a_non_timeout_failure_is_not_retried( self ):
        """An offline user or a transport error will not improve on a second
        attempt; only a timeout will."""
        offline = NotificationResponse( response_value=None, exit_code=1,
                                        status="offline", is_timeout=False )
        result, sent = self._run( [ offline ], retry_on_timeout=True, max_attempts=3 )
        assert result.status == "offline"
        assert sent.call_count == 1

    def test_the_last_attempt_is_returned_rather_than_retried_forever( self ):
        timed_out = NotificationResponse( response_value=None, exit_code=2,
                                          status="expired", is_timeout=True )
        result, sent = self._run( [ timed_out, timed_out ], retry_on_timeout=True,
                                  max_attempts=2 )
        assert result.is_timeout is True
        assert sent.call_count == 2
