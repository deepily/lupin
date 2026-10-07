#!/usr/bin/env python3
"""
Unit tests for the scripted answers a live-pipeline smoke gives to a parked ask.

The ask door parks when a query leaves out an argument, and only POST /api/v2/resume answers it.
These tests mock the HTTP layer, so they need no server and spend no tokens.
"""

from unittest.mock import MagicMock, patch

import tests.smoke.utilities.live_pipeline_base as lpb
from tests.smoke.utilities.live_pipeline_base import LivePipelineTestBase


class _Harness( LivePipelineTestBase ):
    """Minimal concrete subclass; skips the base setup so only the answering is under test."""
    BASE_URL        = "http://test-server"
    POLL_INTERVAL   = 1
    REQUEST_TIMEOUT = 5
    PARKED_ANSWERS  = { "pytest_args": "none" }

    def __init__( self ):
        pass

    def get_submit_payload( self, scenario, ws_id ):
        return { "question": scenario[ "query" ] }

    def get_submit_headers( self, headers, ws_id ):
        return headers


HEADERS = { "Authorization": "Bearer t" }
PARKED  = { "status": "parked", "pending_id": "p-1", "args_missing": [ "pytest_args" ], "answer": "Any extra pytest arguments?" }
DONE    = { "status": "done", "answer": "dry run complete" }


def _resp( status, body, text="" ):
    r = MagicMock()
    r.status_code = status
    r.json.return_value = body
    r.text = text
    return r


def test_a_scripted_question_is_answered_through_resume():
    h = _Harness()
    with patch.object( lpb.requests, "post", return_value=_resp( 200, DONE ) ) as post:
        data, error = h._answer_parked( dict( PARKED ), HEADERS, "ws" )
    assert ( data, error ) == ( DONE, None )
    assert post.call_count == 1
    url = post.call_args.args[ 0 ]
    assert url == "http://test-server/api/v2/resume"
    assert post.call_args.kwargs[ "json" ] == { "pending_id": "p-1", "answer": "none", "websocket_id": "ws" }


def test_a_question_with_no_scripted_answer_is_left_alone():
    h = _Harness()
    other = dict( PARKED, args_missing=[ "dry_run" ] )
    with patch.object( lpb.requests, "post" ) as post:
        data, error = h._answer_parked( other, HEADERS, "ws" )
    assert ( data, error ) == ( other, None )
    post.assert_not_called()


def test_a_harness_with_no_scripted_answers_never_resumes():
    h = _Harness()
    h.PARKED_ANSWERS = {}
    with patch.object( lpb.requests, "post" ) as post:
        data, error = h._answer_parked( dict( PARKED ), HEADERS, "ws" )
    assert ( data, error ) == ( PARKED, None )
    post.assert_not_called()


def test_a_response_that_is_not_parked_is_left_alone():
    h = _Harness()
    with patch.object( lpb.requests, "post" ) as post:
        assert h._answer_parked( dict( DONE ), HEADERS, "ws" ) == ( DONE, None )
        assert h._answer_parked( dict( PARKED, pending_id=None ), HEADERS, "ws" )[ 1 ] is None
    post.assert_not_called()


def test_a_failed_resume_is_reported():
    h = _Harness()
    with patch.object( lpb.requests, "post", return_value=_resp( 404, {}, "gone" ) ):
        data, error = h._answer_parked( dict( PARKED ), HEADERS, "ws" )
    assert data is None and error == "Resume HTTP 404: gone"


def test_a_resume_that_cannot_connect_is_reported():
    h = _Harness()
    with patch.object( lpb.requests, "post", side_effect=OSError( "refused" ) ):
        data, error = h._answer_parked( dict( PARKED ), HEADERS, "ws" )
    assert data is None and error == "Resume error: refused"


def test_a_flow_that_keeps_asking_is_answered_once_per_scripted_answer():
    h = _Harness()
    with patch.object( lpb.requests, "post", return_value=_resp( 200, dict( PARKED ) ) ) as post:
        data, error = h._answer_parked( dict( PARKED ), HEADERS, "ws" )
    assert post.call_count == 1 and error is None and data[ "status" ] == "parked"


def test_submit_and_wait_answers_the_park_and_returns_the_finished_result():
    h = _Harness()
    posts = [ _resp( 200, dict( PARKED ) ), _resp( 200, dict( DONE ) ) ]
    with patch.object( lpb.requests, "post", side_effect=posts ) as post:
        job, error = h._submit_and_wait( { "query": "run tests" }, HEADERS, "ws" )
    assert error is None
    assert job[ "response_text" ] == "dry run complete"
    assert [ c.args[ 0 ].rsplit( "/", 1 )[ -1 ] for c in post.call_args_list ] == [ "ask", "resume" ]


def test_submit_and_wait_without_scripted_answers_still_fails_a_park():
    h = _Harness()
    h.PARKED_ANSWERS = {}
    with patch.object( lpb.requests, "post", return_value=_resp( 200, dict( PARKED ) ) ):
        job, error = h._submit_and_wait( { "query": "run tests" }, HEADERS, "ws" )
    assert job is None and "missing=['pytest_args']" in error


def test_the_test_suite_smoke_answers_pytest_args_and_sets_no_mode():
    from tests.smoke.test_test_suite_live_pipeline import TestSuitePipelineTest
    t = TestSuitePipelineTest()
    assert t.PARKED_ANSWERS == { "pytest_args": "none" }
    assert t.get_mode_for_scenario( t.SCENARIOS[ 0 ] ) is None
