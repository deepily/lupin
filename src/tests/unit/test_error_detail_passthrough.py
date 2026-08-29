#!/usr/bin/env python3
"""
The server's reason must reach the caller — row cd283a77.

WHAT THIS PINS. On a non-200 the notification client built a NotificationResponse
carrying `status="http_error_<code>"` and nothing else; the server's own sentence
was printed to stderr and dropped. An MCP caller never sees stderr, so a seat got
`{"error": "error: http_error_503"}` — a status code that reads as "the service is
down."

THE COST, on 2026-08-19: a manager spent six ask_multiple_choice attempts across
two server boots, built a careful set of interleaved controls, filed a P1 row and
formed a wrong hypothesis (a regression from that evening's force-recreate), while
the 503 body had read "User is offline and no default response provided" the whole
time — the one sentence that names both the cause and the fix.

WHAT IS DELIBERATELY UNCHANGED: `status` is still the bare `http_error_<code>`
string. Callers match on it (test_mcp_timeout_detection.py keys "User is offline"
handling off exactly that), so the reason rides ALONGSIDE it rather than replacing
it. Purely additive.

Venue: :7999-eligible — pure function calls, no network, no mutation.
"""

import json

import pytest

from lupin_cli.notifications.notify_user_sync import _extract_error_detail
from lupin_cli.notifications.notification_models import NotificationResponse
from lupin_mcp.cosa_voice_mcp import _error_dict


# ────────────────────────────────────────────── the extractor

class TestExtractErrorDetail:

    def test_pulls_fastapi_detail_out_of_a_json_body( self ):
        """The real shape: FastAPI's HTTPException body."""
        body = json.dumps( { "detail": "User is offline and no default response provided" } )
        assert _extract_error_detail( body ) == "User is offline and no default response provided"

    def test_a_non_json_body_is_returned_whole_rather_than_swallowed( self ):
        """A proxy's HTML or a bare string still carries information."""
        assert _extract_error_detail( "502 Bad Gateway" ) == "502 Bad Gateway"

    def test_json_without_a_detail_key_falls_back_to_the_raw_body( self ):
        """Not every error body is FastAPI-shaped."""
        body = json.dumps( { "message": "something else" } )
        assert _extract_error_detail( body ) == body

    @pytest.mark.parametrize( "empty", [ "", "   ", None ] )
    def test_an_empty_body_yields_none_because_there_is_nothing_to_say( self, empty ):
        assert _extract_error_detail( empty ) is None

    def test_a_long_body_is_truncated_rather_than_dumped( self ):
        detail = _extract_error_detail( "x" * 5000 )
        assert len( detail ) == 303                      # 300 + the ellipsis
        assert detail.endswith( "..." )


# ────────────────────────────────────────────── the caller-facing dict

class TestErrorDictCarriesTheReason:

    def test_the_incident_shape_now_names_its_own_cause( self ):
        """This is the exact response that cost an evening, and what it says now."""
        response = NotificationResponse(
            response_value = None,
            exit_code      = 1,
            status         = "http_error_503",
            error_detail   = "User is offline and no default response provided",
        )
        out = _error_dict( response )

        assert out[ "error" ]  == "error: http_error_503"      # unchanged — callers match this
        assert out[ "detail" ] == "User is offline and no default response provided"

    def test_detail_is_omitted_when_the_server_said_nothing( self ):
        """A connection failure has no server sentence; do not invent an empty one."""
        response = NotificationResponse(
            response_value = None,
            exit_code      = 1,
            status         = "connection_error",
        )
        out = _error_dict( response )

        assert out == { "error": "error: connection_error" }
        assert "detail" not in out
