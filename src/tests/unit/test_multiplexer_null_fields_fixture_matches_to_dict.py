"""
THE MULTIPLEXER'S NO-PERSONA FRAME IS WHAT THE SERVER BUILDS (2026-09-10, found by the slider E2E ts-720cc046).

src/tests/unit/multiplexer/notification_store_server_null_fields.test.ts feeds NotificationStore the frame in
src/tests/unit/multiplexer/fixtures/notification_queue_update_no_persona.json. The store's older tests built
their frames by hand and left an unsupplied field OUT; the server sends it as null. That difference hid a
silent defect: `voice_persona: null` stopped every persona-less high/urgent notification from being spoken,
and `prediction_hint: null` threw inside the card render.

This test rebuilds the frame with the server's own NotificationItem.to_dict() and _stamp_manager_persona, using
the arguments notify_user's fire-and-forget branch passes for that request, and fails if the file has drifted.
"""

import json

import cosa.utils.util as cu
from cosa.rest.notification_fifo_queue import NotificationFifoQueue, NotificationItem

FIXTURE_PATH = cu.get_project_root() + "/src/tests/unit/multiplexer/fixtures/notification_queue_update_no_persona.json"

# Clock-derived, so the fixture pins them rather than the producer.
CLOCK_KEYS = { "timestamp", "time_display" }


def _fixture():
    """
    Load the fixture the multiplexer store test reads.

    Requires:
        - FIXTURE_PATH exists and holds JSON

    Ensures:
        - returns the parsed fixture dict
    """
    with open( FIXTURE_PATH, encoding="utf-8" ) as f:
        return json.load( f )


def _rebuild( notification ):
    """
    Build the live frame's notification dict the way the fire-and-forget /api/notify path does.

    Requires:
        - notification is the fixture's frame.notification dict

    Ensures:
        - returns NotificationItem.to_dict() plus the manager-persona stamp, for the same request
    """
    item = NotificationItem(
        message                  = notification[ "message" ],
        type                     = notification[ "type" ],
        priority                 = notification[ "priority" ],
        source                   = "claude_code",
        user_id                  = notification[ "user_id" ],
        id                       = notification[ "id" ],
        title                    = None,
        sender_id                = notification[ "sender_id" ],
        abstract                 = None,
        suppress_ding            = notification[ "suppress_ding" ],
        job_id                   = None,
        queue_name               = None,
        progress_group_id        = None,
        display_qualifier_widget = False,
        session_name             = None,
        voice_persona            = None,
        direction                = notification[ "direction" ],
    )
    built = item.to_dict()
    NotificationFifoQueue._stamp_manager_persona( None, built, built[ "sender_id" ] )
    return built


def test_the_fixture_frame_is_what_to_dict_builds_for_a_sender_without_a_persona():
    notification = _fixture()[ "frame" ][ "notification" ]
    built        = _rebuild( notification )
    assert set( notification ) == set( built ), f"key sets differ: { set( notification ) ^ set( built ) }"
    for key in set( built ) - CLOCK_KEYS:
        assert notification[ key ] == built[ key ], key


def test_the_fixture_carries_the_nulls_that_broke_the_multiplexer():
    notification = _fixture()[ "frame" ][ "notification" ]
    assert notification[ "priority" ] == "high"
    for key in ( "voice_persona", "prediction_hint", "title", "abstract", "progress_group_id",
                 "response_type", "response_default", "timeout_seconds", "session_name" ):
        assert key in notification and notification[ key ] is None, key


def test_the_frame_envelope_matches_emit_notification_added():
    frame = _fixture()[ "frame" ]
    assert set( frame ) == { "queue_name", "value", "notification" }
    assert frame[ "queue_name" ] == "notification"
