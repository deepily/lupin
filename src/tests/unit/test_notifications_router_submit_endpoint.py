"""
Unit tests for POST /api/notify/response — the endpoint the UI calls when a human
answers a response-required notification.

This is an ORCHESTRATOR. Its own sync workers (`_submit_response_sync`,
`_mark_answer_delivered_sync`) are unit-tested elsewhere; what is asserted here is
what it does with them, and the interesting claims are all about ORDER and ABSENCE.

🔴 THE RECEIPT IS SET ONLY WHEN A LIVE WAITER WILL CONSUME THE ANSWER. If an SSE
stream is waiting in THIS process, its event is set — and since row 97ff4426 the
mark itself is left to the stream, which stamps it once the frame is taken. If
nothing is waiting, the answer must stay OWED so
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
_CARD_SCHEMA = { "questions": [ { "header": "SCHEMA-HEADER", "multi_select": True } ] }


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
        "submit_calls"     : [],
        "answered_by_calls": [],
        "delivered_calls"  : [],
        "submit_result"  : { "recipient_id"     : "RECIPIENT-VALUE",
                             "job_id"           : None,
                             "sender_id"        : _SENDER,
                             "response_options" : _CARD_SCHEMA },
        "submit_raises"  : None,
        "ruling_calls"   : [],
        "ruling_raises"  : None,
        "enqueue_calls"  : [],
        "enqueue_raises" : None,
    }

    # `answered_by` joined the worker's signature in row e20e249a (the door now stamps who
    # answered). Recorded apart from `submit_calls` so the id/value assertions stay exact.
    def _submit( notification_id, response_value, answered_by=None, input_route=None ):
        state[ "submit_calls" ].append( ( notification_id, response_value ) )
        state[ "answered_by_calls" ].append( answered_by )
        if state[ "submit_raises" ] is not None:
            raise state[ "submit_raises" ]
        return state[ "submit_result" ]

    def _delivered( notification_id ):
        state[ "delivered_calls" ].append( notification_id )

    monkeypatch.setattr( notif, "_submit_response_sync",       _submit )
    monkeypatch.setattr( notif, "_mark_answer_delivered_sync", _delivered )

    def _ruling( notification_id ):
        state[ "ruling_calls" ].append( notification_id )
        if state[ "ruling_raises" ] is not None: raise state[ "ruling_raises" ]
        return { "rulings_written": 1, "existing": 0, "rejected": [] }
    monkeypatch.setattr( notif, "_record_review_ruling_sync", _ruling )

    def _enqueue( notification_id, submit_result ):
        state[ "enqueue_calls" ].append( ( notification_id, submit_result ) )
        if state[ "enqueue_raises" ] is not None: raise state[ "enqueue_raises" ]
        return { "queued": True, "reason": "queued", "job_id": "pe-test" }
    monkeypatch.setattr( notif, "_enqueue_extractor_sync", _enqueue )
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

    def test_the_worker_is_told_who_answered_as_the_server_knows_it( self, harness, wired ):
        """
        Row e20e249a: the door stamps `answered_by` from the credential, never from the
        body. The user id is a self-naming value the default fixture does not use, and the
        two posts differ only in the X-API-Key header, so a door that ignored the
        credential, or credited the wrong method, would show here.
        """
        harness.as_user( "ANSWERING-USER-ID" )
        harness.client.post( _URL, headers={ "X-API-Key": "KEY-VALUE" },
                             json={ "notification_id": _NID, "response_value": "A",
                                    "answered_by"    : { "user_id": "FORGED" } } )
        harness.client.post( _URL, json={ "notification_id": _NID, "response_value": "B" } )

        assert wired[ "answered_by_calls" ] == [
            { "user_id": "ANSWERING-USER-ID", "account_email": None, "method": "api_key" },
            { "user_id": "ANSWERING-USER-ID", "account_email": None, "method": "jwt" },
        ]

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


class TestTheAnswerIsStoredAsTyped:
    """The door keeps what was typed; every render path escapes it on display."""

    @pytest.mark.parametrize( "typed", [ "<b>bold</b> answer", "<script>steal()</script>ok", "use <T> generics", "a<b and c>d" ] )
    def test_text_inside_angle_brackets_is_persisted_unchanged( self, harness, wired, typed ):
        harness.client.post( _URL, json={ "notification_id": _NID, "response_value": typed } )
        assert wired[ "submit_calls" ][ 0 ][ 1 ] == typed

    def test_the_response_echoes_what_was_typed( self, harness, wired ):
        body = harness.client.post( _URL, json={ "notification_id": _NID, "response_value": "<i>x</i>" } ).json()
        assert body[ "response_value" ] == "<i>x</i>"

    def test_an_answer_that_is_only_tags_is_a_real_answer( self, harness, wired ):
        r = harness.client.post( _URL, json={ "notification_id": _NID, "response_value": "<b></b>" } )
        assert r.status_code == 200
        assert wired[ "submit_calls" ][ 0 ][ 1 ] == "<b></b>"

    def test_a_whitespace_only_answer_is_a_400( self, harness, wired ):
        r = harness.client.post( _URL, json={ "notification_id": _NID,
                                              "response_value" : "   \t " } )
        assert r.status_code == 400
        assert wired[ "submit_calls" ] == []


class TestTheReceiptIsOnlySetForALiveWaiter:

    def test_a_live_waiter_is_woken_but_the_mark_is_LEFT_TO_THE_STREAM( self, harness, wired ):
        """
        🔴 OPTION B (row 97ff4426, Mr. Radio's ruling 2026-09-05). Setting the event is a
        PREDICTION that the stream will resume, not a receipt, so the endpoint no longer
        marks the answer delivered on the wake — the SSE generator stamps it after the
        `responded` frame is taken (see test_the_answer_mark_waits_for_the_consumer.py).
        This test was written against the pre-ruling door and asserted the mark here.
        """
        entry = _add_waiter( wired )
        r = harness.client.post( _URL, json={ "notification_id": _NID,
                                              "response_value" : "ANSWER-VALUE" } )
        assert r.status_code == 200
        assert entry[ "event" ].is_set(), "the waiting SSE stream was never woken"
        assert entry[ "response_data" ] == "ANSWER-VALUE"
        assert wired[ "delivered_calls" ] == [], "the door marked delivered on the wake"

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

    def test_an_outcome_is_recorded_from_memory_when_the_ledger_has_no_row( self, harness, wired, monkeypatch ):
        import cosa.agents.prediction_engine as pe
        seen = []

        class _Engine:
            def record_outcome_from_ledger( self, *a ):
                return False
            def record_outcome( self, **kwargs ):
                seen.append( kwargs )

        monkeypatch.setattr( pe, "get_prediction_engine", lambda: _Engine() )
        _add_waiter( wired, prediction_result=self._Prediction() )
        harness.client.post( _URL, json={ "notification_id": _NID,
                                          "response_value" : "ANSWER-VALUE" } )
        assert len( seen ) == 1
        assert seen[ 0 ][ "actual_value" ]  == "ANSWER-VALUE"
        assert seen[ 0 ][ "response_type" ] == "RESPONSE-TYPE-VALUE"
        assert seen[ 0 ][ "response_options" ] == _CARD_SCHEMA

    def test_the_answer_source_label_reaches_the_engine_on_both_routes( self, harness, wired, monkeypatch ):
        """The door labels a posted answer with the promotion gate's own test."""
        import cosa.agents.prediction_engine as pe
        seen = []

        class _Engine:
            def record_outcome_from_ledger( self, *a ):
                seen.append( ( "ledger", a[ -1 ] ) )
                return len( seen ) > 1
            def record_outcome( self, **kwargs ):
                seen.append( ( "memory", kwargs[ "answer_source" ] ) )

        monkeypatch.setattr( pe, "get_prediction_engine", lambda: _Engine() )
        _add_waiter( wired, prediction_result=self._Prediction() )
        headers = { "X-API-Key": "KEY-VALUE" }
        harness.client.post( _URL, headers=headers, json={ "notification_id": _NID, "response_value": "ANSWER-VALUE" } )
        _add_waiter( wired, prediction_result=self._Prediction() )
        harness.client.post( _URL, headers=headers, json={ "notification_id": _NID, "response_value": "ANSWER-VALUE" } )
        assert seen == [ ( "ledger", "not_operator" ), ( "memory", "not_operator" ), ( "ledger", "not_operator" ) ]

    def test_the_stored_forecast_row_is_used_first_and_memory_is_not_read( self, harness, wired, monkeypatch ):
        import cosa.agents.prediction_engine as pe
        ledger_calls, memory_calls = [], []

        class _Engine:
            def record_outcome_from_ledger( self, *a ):
                ledger_calls.append( a )
                return True
            def record_outcome( self, **kwargs ):
                memory_calls.append( kwargs )

        monkeypatch.setattr( pe, "get_prediction_engine", lambda: _Engine() )
        _add_waiter( wired, prediction_result=self._Prediction() )
        harness.client.post( _URL, json={ "notification_id": _NID, "response_value": "ANSWER-VALUE" } )
        assert ledger_calls == [ ( _NID, "ANSWER-VALUE", ledger_calls[ 0 ][ 2 ], _CARD_SCHEMA, ledger_calls[ 0 ][ 4 ] ) ]
        assert memory_calls == []

    def test_a_restart_that_emptied_memory_still_reaches_the_ledger( self, harness, wired, monkeypatch ):
        """No waiter and no in-memory result: the state a restart leaves. The ledger is still asked."""
        import cosa.agents.prediction_engine as pe
        ledger_calls, memory_calls = [], []

        class _Engine:
            def record_outcome_from_ledger( self, *a ):
                ledger_calls.append( a )
                return True
            def record_outcome( self, **kwargs ):
                memory_calls.append( kwargs )

        monkeypatch.setattr( pe, "get_prediction_engine", lambda: _Engine() )
        r = harness.client.post( _URL, json={ "notification_id": _NID, "response_value": "ANSWER-VALUE" } )
        assert r.status_code == 200
        assert len( ledger_calls ) == 1 and memory_calls == []
        assert ledger_calls[ 0 ][ 3 ] == _CARD_SCHEMA

    def test_no_row_and_nothing_in_memory_means_no_record_outcome_call( self, harness, wired, monkeypatch ):
        import cosa.agents.prediction_engine as pe
        memory_calls = []

        class _Engine:
            def record_outcome_from_ledger( self, *a ):
                return False
            def record_outcome( self, **kwargs ):
                memory_calls.append( kwargs )

        monkeypatch.setattr( pe, "get_prediction_engine", lambda: _Engine() )
        _add_waiter( wired )   # a waiter, but no prediction_result on it
        r = harness.client.post( _URL, json={ "notification_id": _NID,
                                              "response_value" : "ANSWER-VALUE" } )
        assert r.status_code == 200
        assert memory_calls == []

    def test_an_exploding_prediction_engine_does_not_lose_the_answer( self, harness, wired, monkeypatch ):
        import cosa.agents.prediction_engine as pe

        class _Boom:
            def record_outcome_from_ledger( self, *_a ):
                raise RuntimeError( "embedding service down" )

        monkeypatch.setattr( pe, "get_prediction_engine", lambda: _Boom() )
        entry = _add_waiter( wired, prediction_result=self._Prediction() )
        r = harness.client.post( _URL, json={ "notification_id": _NID,
                                              "response_value" : "ANSWER-VALUE" } )
        assert r.status_code == 200
        assert entry[ "event" ].is_set(), "the waiter was never woken after a hook failure"
        assert entry[ "response_data" ] == "ANSWER-VALUE"
        assert wired[ "submit_calls" ] == [ ( _NID, "ANSWER-VALUE" ) ]


class TestAnAnswerToAReviewCardRecordsNoOutcome:

    def test_a_marked_ask_never_reaches_the_prediction_engine( self, harness, wired, monkeypatch ):
        import cosa.agents.prediction_engine as pe
        calls = []

        class _Engine:
            def record_outcome_from_ledger( self, *a ): calls.append( "ledger" ); return True
            def record_outcome( self, **kw ): calls.append( "memory" )

        monkeypatch.setattr( pe, "get_prediction_engine", lambda: _Engine() )
        wired[ "submit_result" ] = { **wired[ "submit_result" ], "response_options": { "review_card": True } }
        _add_waiter( wired, prediction_result=TestThePredictionHookIsNonFatal._Prediction() )
        r = harness.client.post( _URL, json={ "notification_id": _NID, "response_value": "ANSWER-VALUE" } )
        assert r.status_code == 200
        assert calls == [], "a review card has no forecast row and no case to record"
        assert wired[ "submit_calls" ] == [ ( _NID, "ANSWER-VALUE" ) ], "the answer itself is still stored"

    def test_a_marked_answer_is_turned_into_ruling_rows_and_an_unmarked_one_is_not( self, harness, wired ):
        wired[ "submit_result" ] = { **wired[ "submit_result" ], "response_options": { "review_card": True } }
        harness.client.post( _URL, json={ "notification_id": _NID, "response_value": "ANSWER-VALUE" } )
        assert wired[ "ruling_calls" ] == [ _NID ]
        wired[ "ruling_calls" ].clear()
        wired[ "submit_result" ] = { **wired[ "submit_result" ], "response_options": None }
        harness.client.post( _URL, json={ "notification_id": _NID, "response_value": "ANSWER-VALUE" } )
        assert wired[ "ruling_calls" ] == []

    def test_a_failed_ruling_write_never_loses_the_answer_or_wakes_the_waiter_late( self, harness, wired ):
        wired[ "submit_result" ] = { **wired[ "submit_result" ], "response_options": { "review_card": True } }
        wired[ "ruling_raises" ]  = RuntimeError( "database down" )
        entry = _add_waiter( wired )
        r = harness.client.post( _URL, json={ "notification_id": _NID, "response_value": "ANSWER-VALUE" } )
        assert r.status_code == 200 and entry[ "event" ].is_set() and entry[ "response_data" ] == "ANSWER-VALUE"
        assert wired[ "submit_calls" ] == [ ( _NID, "ANSWER-VALUE" ) ]

    def test_an_unmarked_ask_still_reaches_the_ledger( self, harness, wired, monkeypatch ):
        import cosa.agents.prediction_engine as pe
        calls = []

        class _Engine:
            def record_outcome_from_ledger( self, *a ): calls.append( "ledger" ); return True

        monkeypatch.setattr( pe, "get_prediction_engine", lambda: _Engine() )
        harness.client.post( _URL, json={ "notification_id": _NID, "response_value": "ANSWER-VALUE" } )
        assert calls == [ "ledger" ]


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


class TestTheDoorQueuesTheExtractorOncePerAnswer:

    def test_one_answer_calls_the_enqueue_once_with_the_stored_submit_result( self, harness, wired ):
        r = harness.client.post( _URL, json={ "notification_id": _NID, "response_value": "ANSWER-VALUE" } )
        assert r.status_code == 200
        assert wired[ "enqueue_calls" ] == [ ( _NID, wired[ "submit_result" ] ) ]

    def test_a_failed_enqueue_never_loses_the_answer_or_wakes_the_waiter_late( self, harness, wired ):
        wired[ "enqueue_raises" ] = RuntimeError( "queue down" )
        entry = _add_waiter( wired )
        r = harness.client.post( _URL, json={ "notification_id": _NID, "response_value": "ANSWER-VALUE" } )
        assert r.status_code == 200
        assert entry[ "event" ].is_set()
        assert wired[ "submit_calls" ] == [ ( _NID, "ANSWER-VALUE" ) ]


class TestTheContextForecastSettlesAtAnswerTime:

    def test_the_answered_card_is_settled_with_the_apps_sessions( self, harness, wired, monkeypatch, capsys ):
        import cosa.agents.prediction_engine.context_hint as ch
        import cosa.rest.routers.notifications as notif
        seen = []
        monkeypatch.setattr( ch, "settle_unfinished", lambda factory, nid: seen.append( ( factory, nid ) ) or True )
        r = harness.client.post( _URL, json={ "notification_id": _NID, "response_value": "ANSWER-VALUE" } )
        assert r.status_code == 200 and seen == [ ( notif.get_db, _NID ) ]
        assert "stored forecast_timed_out" in capsys.readouterr().out

    def test_a_card_that_needed_no_settle_prints_nothing( self, harness, wired, monkeypatch, capsys ):
        import cosa.agents.prediction_engine.context_hint as ch
        monkeypatch.setattr( ch, "settle_unfinished", lambda factory, nid: False )
        harness.client.post( _URL, json={ "notification_id": _NID, "response_value": "ANSWER-VALUE" } )
        assert "stored forecast_timed_out" not in capsys.readouterr().out

    def test_a_settle_failure_does_not_lose_the_answer( self, harness, wired, monkeypatch ):
        import cosa.agents.prediction_engine.context_hint as ch
        def boom( factory, nid ): raise RuntimeError( "database down" )
        monkeypatch.setattr( ch, "settle_unfinished", boom )
        r = harness.client.post( _URL, json={ "notification_id": _NID, "response_value": "ANSWER-VALUE" } )
        assert r.status_code == 200 and wired[ "submit_calls" ] == [ ( _NID, "ANSWER-VALUE" ) ]
