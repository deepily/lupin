#!/usr/bin/env python3
"""
Row 0c3ad4b5 — offline + no default must return a NAMED user-unavailable
condition, NOT a bare HTTP 503.

THE BUG: when the user is offline and a sync ask carries no default, the server
raised HTTPException(503). notify_user_sync mapped it to status=http_error_503,
and the MCP ask surface returned a bare "error: http_error_503". A 503 reads as
"server down → retry", the OPPOSITE of the correct offline-user response (stop
asking, block the row with a chase). notify already degrades gracefully on its
async path; the sync asks did not.

THE FIX (four layers, tested one class each):
  1. OfflineEvent model accepts the no-default shape (response=None,
     default_used=False).
  2. Server emits that NAMED terminal OfflineEvent instead of raising 503.
     (Server-branch behaviour is exercised at the SSE-parse + mapping layers
     below; the raise-site removal is a one-branch swap verified by the client
     mapping no longer seeing http_error_503.)
  3. notify_user_sync maps an OfflineEvent(default_used=False) to a NAMED
     status "user_not_available" (exit_code=1, response_value=None) — NOT a
     forged default, NOT a transport error.
  4. The MCP ask surface (converse / ask_multiple_choice / ask_open_ended_batch)
     returns that named condition a caller can branch on.

TWO HARD CONSTRAINTS, both pinned here:
  * We do NOT key on the bare 503 — the client keys on OfflineEvent.default_used
    (a typed field), and the guard tests below prove a GENUINE transport error
    is still surfaced verbatim, never masked as "user away".
  * We do NOT make asks carry a default to hide the error — response_value stays
    None on the named path; no substitution occurs.
"""

import json
from unittest.mock import patch, MagicMock

import pytest

from lupin_cli.notifications.notification_models import OfflineEvent
from lupin_cli.notifications.notify_user_sync import (
    consume_sse_stream,
    _send_sync_notification,
)

from lupin_mcp.cosa_voice_mcp import (
    converse,
    ask_multiple_choice,
    ask_open_ended_batch,
)


# ---------------------------------------------------------------------------
# Layer 1 — the OfflineEvent model carries both shapes on one event
# ---------------------------------------------------------------------------
class TestOfflineEventModel:

    def test_no_default_shape_validates( self ):
        """response=None + default_used=False is the NAMED user-unavailable shape."""
        ev = OfflineEvent( status="offline", response=None, default_used=False )
        assert ev.response is None
        assert ev.default_used is False

    def test_with_default_shape_still_validates( self ):
        """The graceful-substitution shape is unchanged (backward compat)."""
        ev = OfflineEvent( status="offline", response="no", default_used=True )
        assert ev.response == "no"
        assert ev.default_used is True

    def test_defaults_are_the_substitution_shape( self ):
        """Bare construction defaults to the historical with-default semantics."""
        ev = OfflineEvent( response="yes" )
        assert ev.default_used is True


# ---------------------------------------------------------------------------
# Layer 2/3 parse — consume_sse_stream turns the server's named event into a
# typed OfflineEvent(default_used=False)
# ---------------------------------------------------------------------------
class _FakeStream:
    """Minimal stand-in for a streaming requests.Response."""
    def __init__( self, lines ):
        self._lines = lines

    def iter_lines( self ):
        for line in self._lines:
            yield line


def _sse( obj ):
    return ( "data: " + json.dumps( obj ) ).encode( "utf-8" )


class TestConsumeSseStream:

    def test_offline_no_default_event_is_parsed( self ):
        """ack then a null-response/default_used=false offline event -> OfflineEvent."""
        stream = _FakeStream( [
            _sse( { "status": "ack", "notification_id": "n1" } ),
            b"",
            _sse( { "status": "offline", "response": None, "default_used": False } ),
        ] )
        event = consume_sse_stream( stream, timeout_seconds=60 )
        assert isinstance( event, OfflineEvent )
        assert event.response is None
        assert event.default_used is False

    def test_offline_with_default_event_still_parses( self ):
        stream = _FakeStream( [
            _sse( { "status": "offline", "response": "no", "default_used": True } ),
        ] )
        event = consume_sse_stream( stream, timeout_seconds=60 )
        assert isinstance( event, OfflineEvent )
        assert event.response == "no"
        assert event.default_used is True


# ---------------------------------------------------------------------------
# Layer 3 map — notify_user_sync maps the two OfflineEvent shapes to distinct
# NotificationResponse statuses
# ---------------------------------------------------------------------------
def _mock_request():
    req = MagicMock()
    req.timeout_seconds       = 60
    req.to_api_params.return_value = {}
    return req


class TestSyncClientMapping:

    def _run( self, event ):
        resp200 = MagicMock()
        resp200.status_code = 200
        with patch( "lupin_cli.notifications.notify_user_sync.requests.post", return_value=resp200 ), \
             patch( "lupin_cli.notifications.notify_user_sync.consume_sse_stream", return_value=event ):
            return _send_sync_notification(
                request      = _mock_request(),
                server_url   = None,
                debug        = False,
                api_key      = "test-key",
                base_url     = "http://localhost:7999",
                env          = "test",
                bearer_token = None,
            )

    def test_offline_no_default_maps_to_user_not_available( self ):
        out = self._run( OfflineEvent( response=None, default_used=False ) )
        assert out.status         == "user_not_available"
        assert out.exit_code      == 1
        assert out.response_value is None
        assert out.default_used   is False

    def test_offline_with_default_still_maps_to_offline_success( self ):
        out = self._run( OfflineEvent( response="no", default_used=True ) )
        assert out.status       == "offline"
        assert out.exit_code    == 0
        assert out.response_value == "no"
        assert out.default_used is True


# ---------------------------------------------------------------------------
# Layer 4 — the MCP ask surface returns a branchable named condition, and does
# NOT mask a genuine transport error (the house-finding guard)
# ---------------------------------------------------------------------------
def _mock_notify_response( status, exit_code=1, is_timeout=False ):
    m               = MagicMock()
    m.exit_code     = exit_code
    m.response_value = None
    m.status        = status
    m.is_timeout    = is_timeout
    m.default_used  = False
    return m


SINGLE_QUESTION = [ {
    "question"    : "Which database?",
    "header"      : "Database",
    "multiSelect" : False,
    "options"     : [ { "label": "PostgreSQL" }, { "label": "MongoDB" } ],
} ]

BATCH_QUESTIONS = [ { "question": "What is the goal?", "header": "Goal" } ]


class TestMcpAskSurface:

    @patch( "lupin_mcp.cosa_voice_mcp.NotificationRequest" )
    @patch( "lupin_mcp.cosa_voice_mcp._normalize_abstract", return_value=None )
    @patch( "lupin_mcp.cosa_voice_mcp._wait_for_sender_id", return_value="claude.code@lupin.deepily.ai#t" )
    @patch( "lupin_mcp.cosa_voice_mcp.notify_user_sync" )
    def test_ask_multiple_choice_named_offline( self, mock_notify, *_ ):
        mock_notify.return_value = _mock_notify_response( "user_not_available" )
        result = ask_multiple_choice.fn( questions=SINGLE_QUESTION )
        assert result == { "status": "user_not_available" }

    @patch( "lupin_mcp.cosa_voice_mcp.NotificationRequest" )
    @patch( "lupin_mcp.cosa_voice_mcp._normalize_abstract", return_value=None )
    @patch( "lupin_mcp.cosa_voice_mcp._wait_for_sender_id", return_value="claude.code@lupin.deepily.ai#t" )
    @patch( "lupin_mcp.cosa_voice_mcp.notify_user_sync" )
    def test_ask_multiple_choice_real_error_not_masked( self, mock_notify, *_ ):
        """A genuine transport failure must still surface verbatim — never as 'user away'."""
        mock_notify.return_value = _mock_notify_response( "connection_error" )
        result = ask_multiple_choice.fn( questions=SINGLE_QUESTION )
        assert result == { "error": "error: connection_error" }

    @patch( "lupin_mcp.cosa_voice_mcp.NotificationRequest" )
    @patch( "lupin_mcp.cosa_voice_mcp._normalize_abstract", return_value=None )
    @patch( "lupin_mcp.cosa_voice_mcp._wait_for_sender_id", return_value="claude.code@lupin.deepily.ai#t" )
    @patch( "lupin_mcp.cosa_voice_mcp.notify_user_sync" )
    def test_converse_named_offline( self, mock_notify, *_ ):
        mock_notify.return_value = _mock_notify_response( "user_not_available" )
        result = converse.fn( message="Which way?" )
        assert result == "[user_not_available]"

    @patch( "lupin_mcp.cosa_voice_mcp.NotificationRequest" )
    @patch( "lupin_mcp.cosa_voice_mcp._normalize_abstract", return_value=None )
    @patch( "lupin_mcp.cosa_voice_mcp._wait_for_sender_id", return_value="claude.code@lupin.deepily.ai#t" )
    @patch( "lupin_mcp.cosa_voice_mcp.notify_user_sync" )
    def test_converse_real_error_not_masked( self, mock_notify, *_ ):
        mock_notify.return_value = _mock_notify_response( "connection_error" )
        result = converse.fn( message="Which way?" )
        assert result == "[error: connection_error]"

    @patch( "lupin_mcp.cosa_voice_mcp.NotificationRequest" )
    @patch( "lupin_mcp.cosa_voice_mcp._normalize_abstract", return_value=None )
    @patch( "lupin_mcp.cosa_voice_mcp._wait_for_sender_id", return_value="claude.code@lupin.deepily.ai#t" )
    @patch( "lupin_mcp.cosa_voice_mcp.notify_user_sync" )
    def test_ask_open_ended_batch_named_offline( self, mock_notify, *_ ):
        mock_notify.return_value = _mock_notify_response( "user_not_available" )
        result = ask_open_ended_batch.fn( questions=BATCH_QUESTIONS )
        assert result == { "status": "user_not_available" }


if __name__ == "__main__":
    import sys
    sys.exit( pytest.main( [ __file__, "-v" ] ) )
