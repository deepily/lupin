"""
Debug, auth-header, unknown-event and transport-error arms of `notify_user_sync`.

Every test patches the transport, so nothing reaches a human.
Each test names the arm it reaches and asserts what the caller or log reader sees.
"""

from unittest.mock import MagicMock, patch

import pytest
import requests

from lupin_cli.notifications import notify_user_sync as mod
from lupin_cli.notifications.notification_models import (
    ErrorEvent,
    ExpiredEvent,
    NotificationRequest,
    NotificationResponse,
    OfflineEvent,
    RespondedEvent,
    ResponseType,
)

MODULE = "lupin_cli.notifications.notify_user_sync"
BASE   = "http://localhost:7999"


def _request():
    return NotificationRequest(
        message="Approve?", response_type=ResponseType.YES_NO, response_default="no",
        timeout_seconds=60, sender_id="test.unit@lupin.deepily.ai", target_user="test@example.com",
    )


def _send( *, event=None, post_side_effect=None, debug=False, api_key="k" * 40, bearer_token=None ):
    ok = MagicMock( status_code=200 )
    with patch( f"{MODULE}.requests.post", return_value=ok, side_effect=post_side_effect ) as post, \
         patch( f"{MODULE}.consume_sse_stream", return_value=event ):
        resp = mod._send_sync_notification( _request(), None, debug, api_key, BASE, "test", bearer_token )
    return resp, post


class TestAuthHeaders:

    def test_a_bearer_token_wins_and_no_api_key_header_is_sent( self ):
        _, post = _send( event=RespondedEvent( response="yes" ), bearer_token="jwt-abc" )
        assert post.call_args.kwargs[ "headers" ] == { "Authorization": "Bearer jwt-abc" }

    def test_with_neither_credential_no_auth_header_is_sent( self ):
        _, post = _send( event=RespondedEvent( response="yes" ), api_key=None )
        assert post.call_args.kwargs[ "headers" ] == { }


class TestDebugNarration:

    def test_the_request_is_narrated_on_stderr( self, capsys ):
        _send( event=RespondedEvent( response="yes" ), debug=True )
        err = capsys.readouterr().err
        assert f"Sending notification to: {BASE}/api/notify" in err
        assert "[DEBUG] Environment: test" in err
        assert "API key: " + "k" * 20 + "..." + "k" * 10 in err
        assert "SSE stream connected" in err
        assert "Response received: yes" in err

    def test_a_timeout_with_default_is_narrated( self, capsys ):
        resp, _ = _send( event=ExpiredEvent( response="no", default_used=True ), debug=True )
        assert ( resp.exit_code, resp.status ) == ( 2, "expired" )
        assert "Timeout - using default: no" in capsys.readouterr().err

    def test_an_offline_default_is_narrated( self, capsys ):
        resp, _ = _send( event=OfflineEvent( response="no" ), debug=True )
        assert ( resp.exit_code, resp.status, resp.default_used ) == ( 0, "offline", True )
        assert "User offline - used default: no" in capsys.readouterr().err

    def test_a_terminal_event_is_dumped_as_json_in_debug( self, capsys ):
        _send( event=ErrorEvent( message="kaput" ), debug=True )
        assert "Final event: " in capsys.readouterr().err


class TestUnknownEventAndTransportErrors:

    def test_an_event_of_no_known_type_is_reported_as_unknown_event( self, capsys ):
        resp, _ = _send( event=MagicMock() )
        assert ( resp.exit_code, resp.status ) == ( 1, "unknown_event" )
        assert "Unknown event type" in capsys.readouterr().err

    def test_a_generic_request_exception_is_request_exception( self, capsys ):
        resp, _ = _send( post_side_effect=requests.exceptions.InvalidURL( "bad url" ) )
        assert ( resp.exit_code, resp.status ) == ( 1, "request_exception" )
        assert "Request error: bad url" in capsys.readouterr().err

    def test_a_non_request_exception_is_unexpected_exception_without_a_traceback( self, capsys ):
        resp, _ = _send( post_side_effect=ValueError( "weird" ) )
        err = capsys.readouterr().err
        assert ( resp.exit_code, resp.status ) == ( 1, "unexpected_exception" )
        assert "Unexpected error: weird" in err and "Traceback" not in err

    def test_with_debug_the_unexpected_exception_also_prints_the_traceback( self, capsys ):
        resp, _ = _send( post_side_effect=ValueError( "weird" ), debug=True )
        err = capsys.readouterr().err
        assert resp.status == "unexpected_exception"
        assert "Traceback (most recent call last)" in err and "ValueError: weird" in err


class TestReattachDebugNarration:

    def test_no_ack_id_is_narrated( self, capsys ):
        resp = mod._reattach_after_stream_death( None, 5, BASE, { }, debug=True )
        assert resp.status == "stream_error" and resp.reattach_state == "reattach_unavailable"
        assert "Re-attach unavailable: no ack notification_id captured" in capsys.readouterr().err

    def test_a_landed_answer_is_narrated( self, capsys ):
        poll = lambda nid: { "responded_at": "2026-10-26T01:00:00", "response_value": "yes" }
        resp = mod._reattach_after_stream_death( "n1", 5, BASE, { }, poll_fn=poll, debug=True )
        assert ( resp.status, resp.response_value ) == ( "responded", "yes" )
        assert "Re-attach LANDED" in capsys.readouterr().err


class TestWrapperNarration:

    def _run( self, responses, **kwargs ):
        sent = MagicMock( side_effect=responses )
        with patch( f"{MODULE}.get_api_config", side_effect=RuntimeError( "no file" ) ), \
             patch( f"{MODULE}._send_sync_notification", sent ), \
             patch.dict( "os.environ", { "LUPIN_ALLOW_HUMAN_ASK_IN_TESTS": "1" } ):
            return mod.notify_user_sync( _request(), server_url=BASE, **kwargs ), sent

    def test_config_failure_and_each_retry_are_narrated( self, capsys ):
        timed_out = NotificationResponse( response_value=None, exit_code=2, status="expired", is_timeout=True )
        answered  = NotificationResponse( response_value="yes", exit_code=0, status="responded" )
        resp, sent = self._run( [ timed_out, answered ], debug=True, retry_on_timeout=True, max_attempts=2 )
        err = capsys.readouterr().err
        assert resp.status == "responded" and sent.call_count == 2
        assert "Config loading failed, using fallback: no file" in err
        assert "[SYNC] Attempt 1/2, timeout=60s" in err
        assert "[SYNC] Timeout on attempt 1, retrying with 120s..." in err

    def test_zero_attempts_returns_none_without_sending( self ):
        resp, sent = self._run( [], max_attempts=0 )
        assert resp is None
        sent.assert_not_called()
