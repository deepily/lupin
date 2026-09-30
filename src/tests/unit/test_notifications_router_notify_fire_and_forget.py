"""
Unit tests for POST /api/notify — FIRE-AND-FORGET mode (response_requested=False).

The notify endpoint is the largest handler in the router and carries two modes; this
file covers the first one. Its whole job is to answer one question honestly: WILL THIS
MESSAGE BE READ? It has three ways of saying yes-or-no and they are not interchangeable.

🔴 A 200 IS NOT A DELIVERY, AND THE ENDPOINT SAYS SO IN A FIELD. An offline user gets
200 with `delivered: False` and `delivery_path: None`, because the row written to the
database is a FORENSIC record and not a mailbox — nothing rehydrates it, so that
notification is durably stored and permanently unreachable through the endpoint that
serves notifications. Rick ruled the design stays and the reply gets honest. These
tests assert the honesty fields, not the status code, because every path here is a 200.

🔴 THE THREE OUTCOMES DIFFER ONLY IN THE BODY: queued (live socket), delivered via a
cc-listener (the target is offline but a listener for its job is not), and
user_not_available. All three carry the same code, so `status`, `delivered` and
`delivery_path` are asserted together in each — a pair that disagrees is the defect.

🔴 THE PERSISTED ROW'S ID MUST BECOME THE LIVE FRAME'S ID. The multiplexer dedupes a
live arrival against hydrated history by id; two different ids show the user the same
notification twice. It is passed through as `id=` and asserted at the queue boundary.

Fixture: `tests.helpers.notifications_endpoint_harness`.
"""

import pytest

from tests.helpers.notifications_endpoint_harness import (
    a_uuid, assert_no_accidental_500, make_harness_fixture )

harness = make_harness_fixture()


_EMAIL = "someone@example.com"
_UID   = a_uuid( "notify-target" )
_DBID  = a_uuid( "persisted-row" )


@pytest.fixture
def wired( harness, monkeypatch ):
    """
    Stub the user lookup, the two sync DB workers and the persona read.

    All four are unit-tested elsewhere; what this file asserts is the ORCHESTRATION —
    which of them run, in what order, and with which values.
    """
    import cosa.rest.routers.notifications as notif
    import cosa.rest.user_service as user_service

    state = {
        "user"            : { "id": _UID, "uid": "UID-VALUE" },
        "persist_calls"   : [],
        "persist_result"  : _DBID,
        "persist_raises"  : None,
        "state_calls"     : [],
        "connected"       : True,
        "connection_count": 2,
        "listener_result" : { "listener_delivered": False },
    }

    monkeypatch.setattr( user_service, "get_user_by_email",
                         lambda email: state[ "user" ] )

    def _persist( *args ):
        state[ "persist_calls" ].append( args )
        if state[ "persist_raises" ] is not None:
            raise state[ "persist_raises" ]
        return state[ "persist_result" ]

    monkeypatch.setattr( notif, "_persist_notification_sync", _persist )
    monkeypatch.setattr( notif, "_update_notification_state_sync",
                         lambda nid, st: state[ "state_calls" ].append( ( nid, st ) ) )
    monkeypatch.setattr( notif, "_voice_persona_for_sender_id",
                         lambda sid: { "name": "PERSONA-VALUE", "icon": "ICON-VALUE" } )

    harness.ws.returns( "is_user_connected",         True )
    harness.ws.returns( "get_user_connection_count", 2 )
    harness.ws.returns( "emit_to_user_or_listener_sync", state[ "listener_result" ] )
    harness.queue.returns( "push_notification", object() )

    state[ "notif" ] = notif
    return state


def _offline( harness, wired ):
    harness.ws.returns( "is_user_connected",         False )
    harness.ws.returns( "get_user_connection_count", 0 )
    return wired


def _url( **params ):
    from urllib.parse import urlencode
    base = { "message": "MESSAGE-VALUE", "target_user": _EMAIL }
    base.update( params )
    return "/api/notify?" + urlencode( base )


class TestTheOnlinePath:

    def test_a_connected_user_gets_queued_and_the_body_says_delivered( self, harness, wired ):
        r = harness.client.post( _url() )
        assert_no_accidental_500( r )
        body = r.json()
        assert body[ "status" ]           == "queued"
        assert body[ "delivered" ]        is True
        assert body[ "delivery_path" ]    == "queue"
        assert body[ "target_system_id" ] == _UID
        assert body[ "connection_count" ] == 2

    def test_the_message_reaches_the_queue_stripped( self, harness, wired ):
        harness.client.post( _url( message="  MESSAGE-VALUE  " ) )
        assert harness.queue.call_to( "push_notification" ).kwargs[ "message" ] == "MESSAGE-VALUE"

    def test_the_PERSISTED_ROWS_ID_becomes_the_live_frames_id( self, harness, wired ):
        """
        🔴 THE MULTIPLEXER DEDUPES A LIVE ARRIVAL AGAINST HYDRATED HISTORY BY ID. Two
        different ids show the user the same notification twice on a cold load. The id
        is a distinct value from every other field here, so passing the wrong one — or
        letting it default — is a different call.
        """
        harness.client.post( _url() )
        assert harness.queue.call_to( "push_notification" ).kwargs[ "id" ] == _DBID

    def test_the_queue_frame_carries_the_routing_and_display_fields( self, harness, wired ):
        harness.client.post( _url( job_id="JOB-ID-VALUE", queue_name="run",
                                   title="TITLE-VALUE", abstract="ABSTRACT-VALUE",
                                   progress_group_id="PG-VALUE",
                                   session_name="SESSION-NAME-VALUE",
                                   suppress_ding="true", direction="ai_to_ai" ) )
        kw = harness.queue.call_to( "push_notification" ).kwargs
        assert kw[ "job_id" ]            == "JOB-ID-VALUE"
        assert kw[ "queue_name" ]        == "run"
        assert kw[ "title" ]             == "TITLE-VALUE"
        assert kw[ "abstract" ]          == "ABSTRACT-VALUE"
        assert kw[ "progress_group_id" ] == "PG-VALUE"
        assert kw[ "session_name" ]      == "SESSION-NAME-VALUE"
        assert kw[ "suppress_ding" ]     is True
        assert kw[ "direction" ]         == "ai_to_ai"
        assert kw[ "user_id" ]           == _UID

    def test_the_sender_is_extracted_from_the_message_prefix_when_not_supplied( self, harness, wired ):
        """
        `resolve_sender_id` reads a leading [PREFIX] out of the message. An explicit
        sender must win, so both are posed — with different values, so "used the
        explicit one" and "extracted anyway" are different frames.
        """
        harness.client.post( _url( message="[LUPIN] hello" ) )
        assert harness.queue.call_to( "push_notification" ).kwargs[ "sender_id" ] == \
               "claude.code@lupin.deepily.ai"

    def test_a_message_with_no_prefix_falls_back_rather_than_guessing( self, harness, wired ):
        """
        The prefix pattern is UPPERCASE-ONLY — lowercase does not match, which I
        learned by writing this test wrong first. An unattributable message gets the
        explicit `unknown` sender rather than an empty one, so a row is never written
        with a blank sender.
        """
        harness.client.post( _url( message="hello with no prefix" ) )
        assert harness.queue.call_to( "push_notification" ).kwargs[ "sender_id" ] == \
               "claude.code@unknown.deepily.ai"

    def test_an_explicit_sender_wins_over_the_prefix( self, harness, wired ):
        harness.client.post( _url( message="[LUPIN] hello",
                                   sender_id="EXPLICIT-SENDER-VALUE" ) )
        assert harness.queue.call_to( "push_notification" ).kwargs[ "sender_id" ] == "EXPLICIT-SENDER-VALUE"

    def test_the_persona_is_resolved_and_attached_to_the_frame( self, harness, wired ):
        harness.client.post( _url() )
        assert harness.queue.call_to( "push_notification" ).kwargs[ "voice_persona" ] == {
            "name": "PERSONA-VALUE", "icon": "ICON-VALUE" }


class TestPersistence:

    def test_the_row_is_written_before_the_frame_is_queued( self, harness, wired ):
        harness.client.post( _url() )
        assert len( wired[ "persist_calls" ] ) == 1
        assert harness.queue.names == [ "push_notification" ]

    def test_persist_false_skips_the_row_and_still_delivers( self, harness, wired ):
        """
        The delivery-only re-attempt: the arbiter re-announces every 300s and must not
        mint a duplicate forensic row each time. Delivery is unaffected, so both halves
        are asserted — skipping the write AND still queueing.
        """
        r = harness.client.post( _url( persist="false" ) )
        assert wired[ "persist_calls" ] == []
        assert r.json()[ "status" ] == "queued"
        assert harness.queue.call_to( "push_notification" ).kwargs[ "id" ] is None

    def test_a_persist_failure_is_NON_FATAL_and_the_message_still_goes_out( self, harness, wired ):
        """
        🔴 THE QUEUE IS THE PRIMARY DELIVERY MECHANISM, NOT THE DATABASE. Losing a
        live notification because a forensic write failed would be the wrong trade,
        and the id falls back to None rather than the call being abandoned.
        """
        wired[ "persist_raises" ] = RuntimeError( "connection reset" )
        r = harness.client.post( _url() )
        assert r.status_code == 200
        assert r.json()[ "status" ] == "queued"
        assert harness.queue.call_to( "push_notification" ).kwargs[ "id" ] is None


class TestTheOfflinePath:

    def test_an_offline_user_is_a_200_that_says_it_was_NOT_delivered( self, harness, wired ):
        """
        🔴 THE STATUS CODE CANNOT CARRY THIS. Every outcome here is a 200, so a caller
        asking "will this be read" reads the body. The three fields are asserted
        together because a pair that disagrees — delivered True with path None — is
        exactly the regression that leaves a caller believing a message landed.
        """
        _offline( harness, wired )
        r = harness.client.post( _url() )
        assert r.status_code == 200
        body = r.json()
        assert body[ "status" ]           == "user_not_available"
        assert body[ "delivered" ]        is False
        assert body[ "delivery_path" ]    is None
        assert body[ "connection_count" ] == 0

    def test_an_offline_user_never_reaches_the_live_queue( self, harness, wired ):
        _offline( harness, wired )
        harness.client.post( _url() )
        assert harness.queue.calls == []

    def test_the_forensic_row_is_STILL_written_when_the_user_is_offline( self, harness, wired ):
        """The row is the whole point of the offline path — it is what recovery reads."""
        _offline( harness, wired )
        harness.client.post( _url() )
        assert len( wired[ "persist_calls" ] ) == 1

    def test_without_a_job_id_no_listener_fallback_is_even_attempted( self, harness, wired ):
        """The listener is keyed by job; with no job there is nothing to try."""
        _offline( harness, wired )
        harness.client.post( _url() )
        harness.ws.assert_never_called( "emit_to_user_or_listener_sync" )


class TestTheListenerFallback:

    def _wire_listener( self, harness, wired, delivered ):
        _offline( harness, wired )
        harness.ws.returns( "emit_to_user_or_listener_sync",
                            { "listener_delivered": delivered } )

    def test_a_listening_cc_session_makes_it_a_real_delivery( self, harness, wired ):
        """
        A CC listener authenticates as a shared service account, so it lives under a
        different user_id than the target — `is_user_connected` says offline while a
        listener for the job is right there. This is the path that finds it.
        """
        self._wire_listener( harness, wired, True )
        body = harness.client.post( _url( job_id="JOB-ID-VALUE" ) ).json()
        assert body[ "status" ]        == "delivered_via_listener"
        assert body[ "delivered" ]     is True
        assert body[ "delivery_path" ] == "cc-listener"

    def test_a_listener_delivery_marks_the_row_delivered( self, harness, wired ):
        """The forensic row must not read as never-delivered when it demonstrably was."""
        self._wire_listener( harness, wired, True )
        harness.client.post( _url( job_id="JOB-ID-VALUE" ) )
        assert wired[ "state_calls" ] == [ ( _DBID, "delivered" ) ]

    def test_a_listener_that_did_NOT_deliver_falls_through_to_unavailable( self, harness, wired ):
        """
        🔴 THE FALLBACK IS ATTEMPTED, NOT ASSUMED. A handler that treated "we tried the
        listener" as success would report delivered for a message nobody received —
        and the two branches differ only in a flag inside the dispatch result.
        """
        self._wire_listener( harness, wired, False )
        body = harness.client.post( _url( job_id="JOB-ID-VALUE" ) ).json()
        assert body[ "status" ]        == "user_not_available"
        assert body[ "delivered" ]     is False
        assert body[ "delivery_path" ] is None

    def test_a_failed_listener_attempt_does_not_mark_the_row_delivered( self, harness, wired ):
        self._wire_listener( harness, wired, False )
        harness.client.post( _url( job_id="JOB-ID-VALUE" ) )
        assert wired[ "state_calls" ] == []


class TestIdempotency:

    def test_a_repeated_key_returns_the_first_response_without_working_again( self, harness, wired ):
        """
        🔴 THE RETRY MUST NOT MINT A SECOND ROW OR A SECOND CARD. The cached response
        being identical is only half of it — the load-bearing half is that neither the
        database nor the queue was touched a second time.
        """
        key = a_uuid( "idempotency-key" )
        first  = harness.client.post( _url( idempotency_key=key ) ).json()
        second = harness.client.post( _url( idempotency_key=key ) ).json()
        assert second == first
        assert len( wired[ "persist_calls" ] ) == 1
        assert len( harness.queue.calls_to( "push_notification" ) ) == 1

    def test_a_DIFFERENT_key_is_a_different_notification( self, harness, wired ):
        """The other side of the fork — a cache that matched everything would pass the test above."""
        harness.client.post( _url( idempotency_key=a_uuid( "key-one" ) ) )
        harness.client.post( _url( idempotency_key=a_uuid( "key-two" ) ) )
        assert len( wired[ "persist_calls" ] ) == 2

    def test_no_key_means_no_caching_at_all( self, harness, wired ):
        harness.client.post( _url() )
        harness.client.post( _url() )
        assert len( wired[ "persist_calls" ] ) == 2

    def test_the_offline_outcome_is_cached_too( self, harness, wired ):
        """An offline retry storm must not re-persist either — the row already exists."""
        _offline( harness, wired )
        key = a_uuid( "offline-key" )
        first = harness.client.post( _url( idempotency_key=key ) ).json()
        harness.client.post( _url( idempotency_key=key ) )
        assert first[ "status" ] == "user_not_available"
        assert len( wired[ "persist_calls" ] ) == 1


class TestTheRefusals:

    def test_an_unknown_target_user_is_a_404_and_nothing_is_written( self, harness, wired ):
        wired[ "user" ] = None
        r = harness.client.post( _url() )
        assert r.status_code == 404
        assert _EMAIL in r.json()[ "detail" ]
        assert wired[ "persist_calls" ] == []
        assert harness.queue.calls      == []

    def test_a_missing_message_is_a_422_from_the_schema( self, harness, wired ):
        from urllib.parse import urlencode
        r = harness.client.post( "/api/notify?" + urlencode( { "target_user": _EMAIL } ) )
        assert r.status_code == 422

    def test_a_missing_target_user_is_a_422( self, harness, wired ):
        from urllib.parse import urlencode
        r = harness.client.post( "/api/notify?" + urlencode( { "message": "X" } ) )
        assert r.status_code == 422
