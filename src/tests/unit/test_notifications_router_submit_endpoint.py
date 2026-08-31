"""
Unit tests for POST /api/notify/response — the endpoint the UI calls when a human
answers a response-required notification.

This is an ORCHESTRATOR. Its own sync workers (`_submit_response_sync`,
`_mark_answer_delivered_sync`) are unit-tested elsewhere; what is asserted here is
what it does with them, and the interesting claims are all about ORDER and ABSENCE.

🔴 THE RECEIPT IS SET ONLY WHEN A LIVE WAITER WILL CONSUME THE ANSWER. If an SSE
stream is waiting in THIS process, its event is set and the answer is marked
delivered — a genuine receipt. If nothing is waiting, the answer must stay OWED so
catch-up re-delivers it. Both halves run the same lines to the same 200, so only
asserting the absence of the mark catches a regression that quietly loses answers.

🔴 THE SANITISED VALUE MUST BE THE ONE THAT TRAVELS, NOT JUST THE ONE RETURNED. Tags
are stripped from a string answer; a handler that sanitised for the response envelope
but persisted the raw text would look correct from outside and store the script.

🔴 THE WEBSOCKET ROUTING KEY FALLS BACK TO THE ASKING SESSION'S HASH. Every MCP ask
carries job_id None, so without the fallback the event never reaches the asking
session's listener. The fixture gives job_id and hash8 different values, so "used the
job id" and "used the fallback" are different calls.

🔴 TWO STEPS ARE DELIBERATELY NON-FATAL — the prediction-outcome hook and the
WebSocket broadcast. An answer the human already gave must not be lost because a GPU
embedding or a socket failed. Each is posed exploding, and the assertion is that the
response still succeeds AND was still persisted.

Fixture: `tests.helpers.notifications_endpoint_harness`.
"""

import asyncio

import pytest

from tests.helpers.notifications_endpoint_harness import (
    a_uuid, assert_no_accidental_500, make_harness_fixture )

harness = make_harness_fixture()


_NID    = a_uuid( "submitted-notification" )
_URL    = "/api/notify/response"
_SENDER = "claude.code@lupin.deepily.ai#aaaa1111"


@pytest.fixture
def wired( harness, monkeypatch ):
    """
    Stub the two sync workers and clear the module's in-memory waiter registry.

    `pending_responses` is a module-level dict that survives between tests, so a
    waiter left behind by one test would silently satisfy the next one's "a live
    waiter exists" branch — and that is the branch whose ABSENCE is load-bearing here.
    """
    import cosa.rest.routers.notifications as notif

    state = {
        "submit_calls"   : [],
        "delivered_calls": [],
        "submit_result"  : { "recipient_id": "RECIPIENT-VALUE",
                             "job_id"      : None,
                             "sender_id"   : _SENDER },
        "submit_raises"  : None,
    }

    def _submit( notification_id, response_value ):
        state[ "submit_calls" ].append( ( notification_id, response_value ) )
        if state[ "submit_raises" ] is not None:
            raise state[ "submit_raises" ]
        return state[ "submit_result" ]

    def _delivered( notification_id ):
        state[ "delivered_calls" ].append( notification_id )

    monkeypatch.setattr( notif, "_submit_response_sync",       _submit )
    monkeypatch.setattr( notif, "_mark_answer_delivered_sync", _delivered )
    monkeypatch.setattr( notif, "get_formatted_time_display",  lambda: "TIME-DISPLAY-VALUE" )
    monkeypatch.setattr( notif, "get_formatted_date_display",  lambda: "DATE-DISPLAY-VALUE" )
    monkeypatch.setattr( notif, "pending_responses", {} )

    state[ "waiters" ] = notif.pending_responses
    state[ "notif" ]   = notif
    return state


def _add_waiter( wired, notification_id=_NID, prediction_result=None ):
    """Register a live SSE waiter the way the ask path does."""
    entry = { "event": asyncio.Event() }
    if prediction_result is not None:
        entry[ "prediction_result" ] = prediction_result
    wired[ "waiters" ][ notification_id ] = entry
    return entry


class TestTheHappyPath:

    def test_it_persists_the_answer_and_reports_success( self, harness, wired ):
        r = harness.client.post( _URL, json={ "notification_id": _NID,
                                              "response_value" : "ANSWER-VALUE" } )
        assert_no_accidental_500( r )
        body = r.json()
        assert body[ "status" ]          == "success"
        assert body[ "notification_id" ] == _NID
        assert body[ "response_value" ]  == "ANSWER-VALUE"
        assert wired[ "submit_calls" ] == [ ( _NID, "ANSWER-VALUE" ) ]

    def test_the_envelope_carries_the_formatted_displays( self, harness, wired ):
        body = harness.client.post( _URL, json={ "notification_id": _NID,
                                                 "response_value" : "X" } ).json()
        assert body[ "time_display" ] == "TIME-DISPLAY-VALUE"
        assert body[ "date_display" ] == "DATE-DISPLAY-VALUE"

    def test_a_dict_answer_travels_unchanged( self, harness, wired ):
        """Only string answers are sanitised; a structured answer must not be mangled."""
        payload = { "choice": "yes", "confidence": 3 }
        harness.client.post( _URL, json={ "notification_id": _NID,
                                          "response_value" : payload } )
        assert wired[ "submit_calls" ][ 0 ][ 1 ] == payload

    def test_a_false_answer_is_not_treated_as_missing( self, harness, wired ):
        """
        🔴 THE GUARD IS `is None`, AND IT HAS TO BE. `False` and `0` are legitimate
        answers to a yes/no and to a numeric ask; a truthiness check would refuse both
        with a 422 and the human's answer would be lost at the door.
        """
        r = harness.client.post( _URL, json={ "notification_id": _NID,
                                              "response_value" : False } )
        assert r.status_code == 200
        assert wired[ "submit_calls" ][ 0 ][ 1 ] is False


class TestTheSanitiser:

    def test_html_tags_are_stripped_from_a_string_answer( self, harness, wired ):
        harness.client.post( _URL, json={ "notification_id": _NID,
                                          "response_value" : "<b>bold</b> answer" } )
        assert wired[ "submit_calls" ][ 0 ][ 1 ] == "bold answer"

    def test_a_script_tag_is_stripped_before_it_is_PERSISTED( self, harness, wired ):
        """
        🔴 THE ASSERTION IS AT THE PERSISTENCE BOUNDARY, NOT ON THE RESPONSE. A handler
        that sanitised only what it echoed back would look correct from outside and
        would still store the script for every later reader of the conversation.
        """
        harness.client.post( _URL, json={ "notification_id": _NID,
                                          "response_value" : "<script>steal()</script>ok" } )
        persisted = wired[ "submit_calls" ][ 0 ][ 1 ]
        assert "<" not in persisted and "script" not in persisted
        assert persisted == "steal()ok"

    def test_the_sanitised_value_is_what_the_response_echoes( self, harness, wired ):
        body = harness.client.post( _URL, json={ "notification_id": _NID,
                                                 "response_value" : "<i>x</i>" } ).json()
        assert body[ "response_value" ] == "x"

    def test_an_answer_that_is_ONLY_tags_becomes_empty_and_is_a_400( self, harness, wired ):
        """
        The two guards are ordered: sanitise, then check empty. An answer that arrives
        non-empty and is emptied BY the stripping must still be refused — checking
        emptiness first would let a bare `<b></b>` through as a real answer.
        """
        r = harness.client.post( _URL, json={ "notification_id": _NID,
                                              "response_value" : "<b></b>" } )
        assert r.status_code == 400
        assert "empty" in r.json()[ "detail" ].lower()
        assert wired[ "submit_calls" ] == []

    def test_a_whitespace_only_answer_is_a_400( self, harness, wired ):
        r = harness.client.post( _URL, json={ "notification_id": _NID,
                                              "response_value" : "   \t " } )
        assert r.status_code == 400
        assert wired[ "submit_calls" ] == []


class TestTheReceiptIsOnlySetForALiveWaiter:

    def test_a_live_waiter_is_woken_AND_the_answer_is_marked_delivered( self, harness, wired ):
        entry = _add_waiter( wired )
        r = harness.client.post( _URL, json={ "notification_id": _NID,
                                              "response_value" : "ANSWER-VALUE" } )
        assert r.status_code == 200
        assert entry[ "event" ].is_set(), "the waiting SSE stream was never woken"
        assert entry[ "response_data" ] == "ANSWER-VALUE"
        assert wired[ "delivered_calls" ] == [ _NID ]

    def test_NO_waiter_means_the_answer_STAYS_OWED( self, harness, wired ):
        """
        🔴 THE LOAD-BEARING NEGATIVE CLAIM. With nobody waiting, nothing consumed the
        answer, so answer_delivered_at must stay NULL and catch-up must re-deliver it.
        The response is a 200 either way and the lines run identically, so only this
        absence catches a mark-on-send regression — which silently loses answers to
        sessions that were not listening.
        """
        r = harness.client.post( _URL, json={ "notification_id": _NID,
                                              "response_value" : "ANSWER-VALUE" } )
        assert r.status_code == 200
        assert wired[ "delivered_calls" ] == [], (
            "the answer was marked delivered with no waiter to consume it — it is now "
            "lost to catch-up" )

    def test_a_waiter_for_a_DIFFERENT_notification_does_not_count( self, harness, wired ):
        """
        Membership must be keyed by THIS notification. A handler testing "any waiter
        exists" would mark an answer delivered that nobody read — and one seat waiting
        on anything is the normal state of this server.
        """
        other = _add_waiter( wired, notification_id=a_uuid( "some-other-notification" ) )
        harness.client.post( _URL, json={ "notification_id": _NID,
                                          "response_value" : "ANSWER-VALUE" } )
        assert wired[ "delivered_calls" ] == []
        assert not other[ "event" ].is_set()


class TestTheWebsocketRouting:

    def test_the_event_is_emitted_to_the_recipient( self, harness, wired ):
        harness.client.post( _URL, json={ "notification_id": _NID,
                                          "response_value" : "ANSWER-VALUE" } )
        call = harness.ws.call_to( "emit_to_user_or_listener_sync" )
        assert call.kwargs[ "user_id" ] == "RECIPIENT-VALUE"
        assert call.kwargs[ "event" ]   == "notification_responded"
        assert call.kwargs[ "data" ][ "response_value" ] == "ANSWER-VALUE"

    def test_a_job_id_is_used_as_the_routing_key_when_there_is_one( self, harness, wired ):
        wired[ "submit_result" ] = { "recipient_id": "RECIPIENT-VALUE",
                                     "job_id"      : "JOB-ID-VALUE",
                                     "sender_id"   : _SENDER }
        harness.client.post( _URL, json={ "notification_id": _NID, "response_value": "X" } )
        assert harness.ws.call_to( "emit_to_user_or_listener_sync" ).kwargs[ "job_id" ] == "JOB-ID-VALUE"

    def test_without_a_job_id_it_falls_back_to_the_askers_session_hash( self, harness, wired ):
        """
        🔴 EVERY MCP ASK CARRIES job_id None. Without this fallback the
        notification_responded event never reaches the asking session's listener and
        the answer appears to vanish. The job id and the hash are different strings in
        this fixture, so the two paths produce different calls.
        """
        harness.client.post( _URL, json={ "notification_id": _NID, "response_value": "X" } )
        assert harness.ws.call_to( "emit_to_user_or_listener_sync" ).kwargs[ "job_id" ] == "aaaa1111"

    def test_a_sender_with_no_hash_suffix_routes_with_no_key_rather_than_a_guess( self, harness, wired ):
        """A root session has no #suffix; None is correct and an invented key is not."""
        wired[ "submit_result" ] = { "recipient_id": "RECIPIENT-VALUE",
                                     "job_id"      : None,
                                     "sender_id"   : "claude.code@lupin.deepily.ai" }
        harness.client.post( _URL, json={ "notification_id": _NID, "response_value": "X" } )
        assert harness.ws.call_to( "emit_to_user_or_listener_sync" ).kwargs[ "job_id" ] is None

    def test_a_broadcast_failure_is_NON_FATAL_and_the_answer_survives( self, harness, wired ):
        """
        🔴 THE HUMAN ALREADY ANSWERED. Losing that to a socket error would make them
        answer twice, and the persistence has already happened by this point — so the
        catch here is deliberate and its removal must be visible.
        """
        harness.ws.raises( "emit_to_user_or_listener_sync", RuntimeError( "socket gone" ) )
        r = harness.client.post( _URL, json={ "notification_id": _NID,
                                              "response_value" : "ANSWER-VALUE" } )
        assert r.status_code == 200
        assert wired[ "submit_calls" ] == [ ( _NID, "ANSWER-VALUE" ) ]


class TestThePredictionHookIsNonFatal:

    class _Prediction:
        response_type = "RESPONSE-TYPE-VALUE"

    def test_an_outcome_is_recorded_when_a_prediction_was_pending( self, harness, wired, monkeypatch ):
        import cosa.agents.prediction_engine as pe
        seen = []

        class _Engine:
            def record_outcome( self, **kwargs ):
                seen.append( kwargs )

        monkeypatch.setattr( pe, "get_prediction_engine", lambda: _Engine() )
        _add_waiter( wired, prediction_result=self._Prediction() )
        harness.client.post( _URL, json={ "notification_id": _NID,
                                          "response_value" : "ANSWER-VALUE" } )
        assert len( seen ) == 1
        assert seen[ 0 ][ "actual_value" ]  == "ANSWER-VALUE"
        assert seen[ 0 ][ "response_type" ] == "RESPONSE-TYPE-VALUE"

    def test_no_pending_prediction_means_no_engine_call( self, harness, wired, monkeypatch ):
        import cosa.agents.prediction_engine as pe

        def _never():
            raise AssertionError( "the prediction engine was reached with nothing pending" )

        monkeypatch.setattr( pe, "get_prediction_engine", _never )
        _add_waiter( wired )   # a waiter, but no prediction_result on it
        r = harness.client.post( _URL, json={ "notification_id": _NID,
                                              "response_value" : "ANSWER-VALUE" } )
        assert r.status_code == 200

    def test_an_exploding_prediction_engine_does_not_lose_the_answer( self, harness, wired, monkeypatch ):
        import cosa.agents.prediction_engine as pe

        class _Boom:
            def record_outcome( self, **_kw ):
                raise RuntimeError( "embedding service down" )

        monkeypatch.setattr( pe, "get_prediction_engine", lambda: _Boom() )
        entry = _add_waiter( wired, prediction_result=self._Prediction() )
        r = harness.client.post( _URL, json={ "notification_id": _NID,
                                              "response_value" : "ANSWER-VALUE" } )
        assert r.status_code == 200
        assert entry[ "event" ].is_set(), "the waiter was never woken after a hook failure"
        assert wired[ "delivered_calls" ] == [ _NID ]


class TestTheRefusals:

    def test_a_missing_notification_id_is_a_422( self, harness, wired ):
        r = harness.client.post( _URL, json={ "response_value": "X" } )
        assert r.status_code == 422
        assert "notification_id" in r.json()[ "detail" ]
        assert wired[ "submit_calls" ] == []

    def test_a_missing_response_value_is_a_422( self, harness, wired ):
        r = harness.client.post( _URL, json={ "notification_id": _NID } )
        assert r.status_code == 422
        assert "response_value" in r.json()[ "detail" ]
        assert wired[ "submit_calls" ] == []

    def test_the_workers_own_HTTPException_is_not_swallowed_into_a_500( self, harness, wired ):
        """
        `_submit_response_sync` raises 404 for an unknown row and 400 outside the grace
        period. Both must survive the blanket handler — a caller reads "no such
        notification" and "too late" very differently from "try again".
        """
        from fastapi import HTTPException
        wired[ "submit_raises" ] = HTTPException( status_code=404, detail="not found" )
        r = harness.client.post( _URL, json={ "notification_id": _NID, "response_value": "X" } )
        assert r.status_code == 404

    def test_an_expired_ask_keeps_its_400( self, harness, wired ):
        from fastapi import HTTPException
        wired[ "submit_raises" ] = HTTPException( status_code=400, detail="expired" )
        r = harness.client.post( _URL, json={ "notification_id": _NID, "response_value": "X" } )
        assert r.status_code == 400

    def test_any_other_persistence_fault_is_a_500( self, harness, wired ):
        wired[ "submit_raises" ] = RuntimeError( "connection reset" )
        r = harness.client.post( _URL, json={ "notification_id": _NID, "response_value": "X" } )
        assert r.status_code == 500
