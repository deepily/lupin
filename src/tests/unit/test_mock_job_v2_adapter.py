"""
The adapter the four door-14 callers share (`tests/helpers/mock_job_v2.py`, row 432511fd).
Pure functions; the composition with a REAL v2 response is in
test_v2_submit_mock_job_through_path.py (last section).
"""

from tests.helpers.mock_job_v2 import MOCK_COMMAND, legacy_response, submit_body


def test_fields_split_between_args_and_the_top_level():
    body = submit_body( { "fixed_iterations": 1, "description": "d", "websocket_id": "ws",
                          "scheduled_at": "2026-01-01T00:00:00", "monopolize": True } )
    assert body == { "command": MOCK_COMMAND, "speak": False,
                     "args": { "fixed_iterations": 1, "description": "d" },
                     "websocket_id": "ws", "scheduled_at": "2026-01-01T00:00:00", "monopolize": True }


def test_an_empty_body_is_a_command_with_no_args():
    assert submit_body( { } ) == { "command": MOCK_COMMAND, "speak": False, "args": { } }


def test_waiting_maps_to_queued_and_config_and_message_come_from_submit_details():
    out = legacy_response( { "status": "waiting", "job_id": "mock-1", "queue_position": 3,
                             "submit_details": { "config": { "iterations": 2 }, "message": "m" } } )
    assert out == { "status": "queued", "job_id": "mock-1", "queue_position": 3,
                    "config": { "iterations": 2 }, "message": "m" }


def test_a_cancelled_interview_maps_to_cancelled_with_the_old_placeholder_job_id():
    out = legacy_response( { "status": "failed", "route_reason": "expeditor_cancelled", "job_id": None,
                             "error": "cancelled",
                             "submit_details": { "config": { "notification_status": "no_response" } } } )
    assert out[ "status" ] == "cancelled" and out[ "job_id" ] == "expeditor-test-cancelled"
    assert out[ "config" ][ "notification_status" ] == "no_response"


def test_any_other_outcome_is_an_error_and_keeps_the_error_text():
    out = legacy_response( { "status": "failed", "route_reason": "agentic_build_error", "error": "boom" } )
    assert out[ "status" ] == "error" and out[ "message" ] == "boom" and out[ "config" ] == { }


def test_a_failure_with_no_error_text_has_an_empty_message():
    assert legacy_response( { "status": "failed" } )[ "message" ] == ""


def test_the_parent_id_travels_top_level_only_when_given():
    assert submit_body( { }, parent_id_hash="abc" )[ "parent_id_hash" ] == "abc"
    assert "parent_id_hash" not in submit_body( { }, parent_id_hash=None )
    assert "parent_id_hash" not in submit_body( { }, parent_id_hash="" )
