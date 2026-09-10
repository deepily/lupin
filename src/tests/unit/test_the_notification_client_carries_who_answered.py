"""
Row e20e249a — the notification client carries the server's `answered_by` stamp to its caller.

The door stamps who posted an answer, and the promotion gate refuses any answer not posted on the
operator's own login. Between the two sits this client. If it drops the stamp, every answer
reaches the gate as "nobody the server recorded" and every promotion is refused — so these tests
pin both routes an answer takes back: the live event stream, and the re-attach poll after a
stream dies.

Each stamp below is a distinctive dict, and the stream and re-attach tests compare against it,
so a client that substituted a constant (None, or an empty dict) cannot pass.

⚠️ CALL-SHAPE ONLY. The stream and the poll are faked. These prove the client reads the field;
they do not prove the live server sends it, which the door's own tests cover in-process.

Venue: :7999 — in-process, no server, no network, no persistent-state mutation.
"""

import json

from unittest.mock import MagicMock, patch

from lupin_cli.notifications import notify_user_sync as nus
from lupin_cli.notifications.notification_models import (
    NotificationRequest, NotificationResponse, NotificationPriority, NotificationType,
    RespondedEvent, ResponseType,
)


STAMP = { "user_id": "operator-uid", "account_email": "operator.login@example.com", "method": "jwt" }


def _data_frame( **payload ):
    return ( "data: " + json.dumps( payload ) ).encode( "utf-8" )


def _request():
    return NotificationRequest(
        message           = "may this row leave the holding area?",
        notification_type = NotificationType.CUSTOM,
        priority          = NotificationPriority.HIGH,
        response_type     = ResponseType.YES_NO,
        response_default  = "no",
        timeout_seconds   = 60,
        sender_id         = "test.unit@lupin.deepily.ai",
        target_user       = "test@example.com",
    )


def _send_over_stream( *lines ):
    http = MagicMock()
    http.status_code        = 200
    http.iter_lines.return_value = list( lines )
    with patch( "lupin_cli.notifications.notify_user_sync.requests.post", return_value=http ):
        return nus._send_sync_notification(
            request = _request(), server_url = None, debug = False, api_key = "test-key",
            base_url = "http://x", env = "test", bearer_token = None,
        )


# ── the models ───────────────────────────────────────────────────────────────

def test_a_responded_event_parses_the_stamp():
    event = RespondedEvent.model_validate( { "status": "responded", "response": "yes", "answered_by": STAMP } )
    assert event.answered_by == STAMP


def test_a_responded_event_from_a_server_that_predates_the_stamp_reads_none():
    assert RespondedEvent( response="yes" ).answered_by is None


def test_a_notification_response_defaults_the_stamp_to_none():
    assert NotificationResponse( response_value=None, exit_code=2, status="expired" ).answered_by is None


# ── the live stream ──────────────────────────────────────────────────────────

def test_the_stream_path_hands_the_caller_who_answered():
    response = _send_over_stream(
        _data_frame( status="responded", notification_id="n-1", response="yes", answered_by=STAMP ) )

    assert response.status == "responded"
    assert response.response_value == "yes"
    assert response.answered_by == STAMP


def test_the_stream_path_from_an_older_server_hands_the_caller_none():
    response = _send_over_stream( _data_frame( status="responded", notification_id="n-1", response="yes" ) )

    assert response.status == "responded"
    assert response.answered_by is None


# ── the re-attach poll after the stream died ─────────────────────────────────

def _reattach( row ):
    return nus._reattach_after_stream_death( "N1", 5, "http://x", { }, poll_fn=lambda nid: row, poll_interval=0.0 )


def test_a_reattached_answer_carries_the_stamp_off_the_stored_row():
    response = _reattach( { "responded_at": "2026-09-10T18:00:00+00:00",
                            "response_value": { "value": "yes", "answered_by": STAMP } } )

    assert response.status == "responded"
    assert response.response_value == "yes"
    assert response.answered_by == STAMP


def test_a_reattached_answer_stored_as_a_bare_string_reads_none():
    response = _reattach( { "responded_at": "2026-09-10T18:00:00+00:00", "response_value": "yes" } )

    assert response.status == "responded"
    assert response.response_value == "yes"
    assert response.answered_by is None


def test_a_reattached_answer_whose_row_predates_the_stamp_reads_none():
    response = _reattach( { "responded_at": "2026-09-10T18:00:00+00:00", "response_value": { "value": "yes" } } )

    assert response.status == "responded"
    assert response.answered_by is None
