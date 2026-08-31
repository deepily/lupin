"""
Unit tests for POST /api/notify — RESPONSE-REQUIRED mode (the blocking ask).

This is the path every fleet ask_* lands on. It answers over Server-Sent Events, so
the assertions are about FRAMES, in order, and about the state each frame leaves
behind.

🔴 THE ACK FRAME IS A LIFELINE, NOT A COURTESY. It is emitted BEFORE the handler
blocks, and it carries this ask's notification_id — which is the only way a client
whose stream dies can re-attach by polling. If it were emitted after the answer it
would arrive exactly when it is no longer needed, and the tests assert it is FIRST
rather than merely present.

🔴 A DEFAULT IS DELIVERED, NEVER FORGED. Every substituted answer carries
`default_used: True`, and a real one carries False. That flag is what lets the caller
stamp "answered: false" — without it a timeout is indistinguishable from a human
saying yes, which is the worst possible confusion for an ask.

🔴 AND THE WAITER MUST BE CLEANED UP ON EVERY EXIT. `pending_responses` is a
module-level dict; an entry left behind after a timeout is a slow leak AND a
correctness bug, because the submit endpoint treats a live entry as "somebody is
listening" and marks the answer delivered to nobody.

Fixture: `tests.helpers.notifications_endpoint_harness`.
"""

import json

import pytest

from tests.helpers.notifications_endpoint_harness import (
    a_uuid, make_harness_fixture )

harness = make_harness_fixture()


_EMAIL = "someone@example.com"
_UID   = a_uuid( "ask-target" )
_NID   = a_uuid( "ask-notification" )


# `_persist_response_required_sync` is called POSITIONALLY, and an index written into
# an assertion is a coordinate that goes stale the moment somebody inserts a parameter.
# The names are listed once, here, and read by name everywhere below — so a signature
# change breaks this list loudly instead of shifting every assertion silently.
_PERSIST_ARGS = (
    "sender_id", "recipient_id", "message", "type", "priority", "title", "abstract",
    "response_type", "response_default", "response_options", "timeout_seconds",
    "job_id", "progress_group_id", "state", "sender_persona", "sender_icon",
)


def _persisted( wired, field ):
    """Read one field of the first persist call by NAME."""
    args = wired[ "persist_calls" ][ 0 ]
    assert len( args ) == len( _PERSIST_ARGS ), (
        f"_persist_response_required_sync now takes {len( args )} positional args, not "
        f"{len( _PERSIST_ARGS )} — update _PERSIST_ARGS before trusting this test" )
    return dict( zip( _PERSIST_ARGS, args ) )[ field ]


class _Item:
    """What push_notification hands back — the handler reads two fields off it."""
    response_default = "DEFAULT-VALUE"

    def to_dict( self ):
        return { "id": _NID }


@pytest.fixture
def wired( harness, monkeypatch ):
    import cosa.rest.routers.notifications as notif
    import cosa.rest.user_service as user_service
    import cosa.agents.prediction_engine as pe

    state = {
        "user"           : { "id": _UID, "uid": "UID-VALUE" },
        "persist_calls"  : [],
        "expired_calls"  : [],
    }

    monkeypatch.setattr( user_service, "get_user_by_email", lambda email: state[ "user" ] )

    def _persist( *args ):
        state[ "persist_calls" ].append( args )
        return _NID

    monkeypatch.setattr( notif, "_persist_response_required_sync", _persist )
    monkeypatch.setattr( notif, "_mark_notification_expired_sync",
                         lambda nid: state[ "expired_calls" ].append( nid ) )
    monkeypatch.setattr( notif, "_voice_persona_for_sender_id",
                         lambda sid: { "name": "PERSONA-VALUE", "icon": "ICON-VALUE" } )
    monkeypatch.setattr( notif, "pending_responses", {} )

    class _Engine:
        enabled = False
        hint_voting_enabled = False

    monkeypatch.setattr( pe, "get_prediction_engine", lambda: _Engine() )

    harness.ws.returns( "is_user_connected",         True )
    harness.ws.returns( "get_user_connection_count", 1 )
    harness.ws.returns( "emit_to_user_or_listener_sync", { "listener_delivered": False } )
    harness.queue.returns( "push_notification", _Item() )

    state[ "waiters" ] = notif.pending_responses
    state[ "notif" ]   = notif
    return state


def _url( **params ):
    from urllib.parse import urlencode
    base = { "message"           : "MESSAGE-VALUE",
             "target_user"       : _EMAIL,
             "response_requested": "true",
             "response_type"     : "yes_no",
             "timeout_seconds"   : 1 }
    base.update( params )
    return "/api/notify?" + urlencode( base )


def _frames( response ):
    """Parse an SSE body into the list of decoded `data:` payloads, in order."""
    return [ json.loads( line[ len( "data: " ) : ] )
             for line in response.text.splitlines()
             if line.startswith( "data: " ) ]


class TestTheAckFrame:

    def test_the_first_frame_is_an_ack_carrying_this_asks_id( self, harness, wired ):
        """
        🔴 ORDER IS THE CLAIM. The ack exists so a client whose stream dies can
        re-attach by polling that id; emitted after the answer it would arrive exactly
        when it is no longer needed. So the assertion is on frame ZERO, not on
        presence anywhere in the stream.
        """
        r = harness.client.post( _url() )
        frames = _frames( r )
        assert frames[ 0 ][ "status" ]          == "ack"
        assert frames[ 0 ][ "notification_id" ] == _NID

    def test_the_stream_is_served_as_an_event_stream( self, harness, wired ):
        r = harness.client.post( _url() )
        assert r.headers[ "content-type" ].startswith( "text/event-stream" )
        assert r.headers[ "cache-control" ] == "no-cache"


class TestTheTimeoutPath:

    def test_a_timeout_yields_an_expired_frame_MARKED_as_a_substitution( self, harness, wired ):
        """
        🔴 THE FLAG IS WHAT SEPARATES A DEFAULT FROM AN ANSWER. Without
        `default_used: True` the caller cannot tell a timeout from a human saying yes,
        and it would stamp a forged answer as real.
        """
        frames = _frames( harness.client.post( _url( response_default="DEFAULT-VALUE" ) ) )
        final  = frames[ -1 ]
        assert final[ "status" ]       == "expired"
        assert final[ "response" ]     == "DEFAULT-VALUE"
        assert final[ "default_used" ] is True
        assert final[ "timeout" ]      is True

    def test_a_timeout_marks_the_row_expired( self, harness, wired ):
        harness.client.post( _url( response_default="DEFAULT-VALUE" ) )
        assert wired[ "expired_calls" ] == [ _NID ]

    def test_a_timeout_broadcasts_the_expiry_so_the_card_stops_waiting( self, harness, wired ):
        """Without this the UI card sits asking a question nobody can answer any more."""
        harness.client.post( _url( response_default="DEFAULT-VALUE", job_id="JOB-ID-VALUE" ) )
        call = harness.ws.call_to( "emit_to_user_or_listener_sync" )
        assert call.kwargs[ "event" ]  == "notification_expired"
        assert call.kwargs[ "job_id" ] == "JOB-ID-VALUE"
        assert call.kwargs[ "data" ][ "notification_id" ] == _NID
        assert call.kwargs[ "data" ][ "timeout" ] is True

    def test_a_broadcast_failure_does_not_swallow_the_default( self, harness, wired ):
        """
        The default is the answer the caller is waiting for. Losing it to a socket
        error would hang the ask, so the catch around the broadcast is deliberate.
        """
        harness.ws.raises( "emit_to_user_or_listener_sync", RuntimeError( "socket gone" ) )
        frames = _frames( harness.client.post( _url( response_default="DEFAULT-VALUE" ) ) )
        assert frames[ -1 ][ "status" ]       == "expired"
        assert frames[ -1 ][ "default_used" ] is True

    def test_the_waiter_is_cleaned_up_after_a_timeout( self, harness, wired ):
        """
        🔴 A LEFTOVER ENTRY IS NOT ONLY A LEAK. The submit endpoint reads this dict to
        decide whether anybody is listening, so a stale entry makes it mark an answer
        delivered to nobody — and catch-up then never re-delivers it.
        """
        harness.client.post( _url( response_default="DEFAULT-VALUE" ) )
        assert wired[ "waiters" ] == {}


class TestTheAskItself:

    def test_the_row_is_persisted_as_DELIVERED_when_the_user_is_online( self, harness, wired ):
        harness.client.post( _url( response_default="D" ) )
        assert _persisted( wired, "state" ) == "delivered"

    def test_the_card_carries_the_ask_fields_the_ui_needs( self, harness, wired ):
        harness.client.post( _url( response_default="DEFAULT-VALUE", human_only="true",
                                   timeout_seconds=1 ) )
        kw = harness.queue.call_to( "push_notification" ).kwargs
        assert kw[ "response_requested" ] is True
        assert kw[ "response_type" ]      == "yes_no"
        assert kw[ "response_default" ]   == "DEFAULT-VALUE"
        assert kw[ "human_only" ]         is True
        assert kw[ "id" ]                 == _NID

    def test_human_only_defaults_to_false_so_the_proxy_may_answer( self, harness, wired ):
        """
        🔴 THE DEFAULT DECIDES WHO MAY ANSWER. human_only reserves an ask for a person;
        defaulting it True would silently stop the auto-answer proxy on every ask in
        the fleet, and nothing else in the response would change.
        """
        harness.client.post( _url( response_default="D" ) )
        assert harness.queue.call_to( "push_notification" ).kwargs[ "human_only" ] is False

    def test_a_missing_title_falls_back_to_the_message( self, harness, wired ):
        """A card with no title renders blank — the message is the honest stand-in."""
        harness.client.post( _url( response_default="D", message="MESSAGE-VALUE" ) )
        assert harness.queue.call_to( "push_notification" ).kwargs[ "title" ] == "MESSAGE-VALUE"

    def test_a_supplied_title_is_used_as_given( self, harness, wired ):
        harness.client.post( _url( response_default="D", title="TITLE-VALUE" ) )
        assert harness.queue.call_to( "push_notification" ).kwargs[ "title" ] == "TITLE-VALUE"

    def test_a_prediction_hint_override_survives_and_is_STAMPED_not_replaced( self, harness, wired ):
        """
        I wrote this asserting the override arrived verbatim, and it does not — the
        auto-submit gate stamps its own three keys onto whatever hint is in hand,
        override included. Pinned as it BEHAVES: the caller's value survives AND the
        gate fields are present, which is what the UI needs to decide whether it may
        answer on its own. An equality assertion would have been a false claim about
        the contract.
        """
        harness.client.post( _url( response_default="D",
                                   prediction_hint_override='{"predicted_value": "yes"}' ) )
        hint = harness.queue.call_to( "push_notification" ).kwargs[ "prediction_hint" ]
        assert hint[ "predicted_value" ] == "yes"
        assert "auto_submit_enabled"                  in hint
        assert "auto_submit_min_confidence_threshold" in hint
        assert "auto_submit_grace_window_seconds"     in hint

    def test_no_override_and_a_disabled_engine_leaves_the_card_hintless( self, harness, wired ):
        """
        The other side: with the engine off and nothing supplied there is no hint at
        all, and the auto-submit stamping must not manufacture one out of None.
        """
        harness.client.post( _url( response_default="D" ) )
        assert harness.queue.call_to( "push_notification" ).kwargs[ "prediction_hint" ] is None


class TestTheOfflineAsk:

    def _offline( self, harness ):
        harness.ws.returns( "is_user_connected",         False )
        harness.ws.returns( "get_user_connection_count", 0 )

    def test_an_offline_user_with_a_default_gets_it_as_a_REAL_SSE_FRAME( self, harness, wired ):
        """
        🔴 THIS USED TO BE PLAIN JSON AND THE CLIENT COULD NOT READ IT. The caller
        streams the POST and parses only `data: `-prefixed lines, so a JSONResponse
        here was invisible — the offline default was never delivered at all. The
        assertion is therefore on the parsed FRAME, which is what proves it is SSE.
        """
        self._offline( harness )
        frames = _frames( harness.client.post( _url( response_default="DEFAULT-VALUE" ) ) )
        assert frames[ 0 ][ "status" ]  == "ack"
        assert frames[ -1 ][ "status" ] == "offline"
        assert frames[ -1 ][ "response" ]     == "DEFAULT-VALUE"
        assert frames[ -1 ][ "default_used" ] is True

    def test_the_offline_ask_is_persisted_as_EXPIRED_not_delivered( self, harness, wired ):
        """The audit trail must not claim a card reached a screen nobody was watching."""
        self._offline( harness )
        harness.client.post( _url( response_default="DEFAULT-VALUE" ) )
        assert _persisted( wired, "state" ) == "expired"

    def test_an_offline_ask_never_pushes_a_card( self, harness, wired ):
        self._offline( harness )
        harness.client.post( _url( response_default="DEFAULT-VALUE" ) )
        assert harness.queue.calls == []

    def test_an_offline_user_with_NO_default_is_a_503( self, harness, wired ):
        """
        Nothing can be answered and nothing can be substituted, so this is the one
        outcome on this path that is honestly an error rather than a substitution.
        """
        self._offline( harness )
        r = harness.client.post( _url() )
        assert r.status_code == 503
        assert "offline" in r.json()[ "detail" ].lower()
        assert wired[ "persist_calls" ] == []


class TestTheAskValidation:
    """
    🔴 FOUR GUARDS RUN BEFORE ANY WORK, AND I FOUND THEM BY WRITING A TEST WRONG.
    My first pass set timeout_seconds=0 to make the timeout tests instant; every
    request came back 400 and nothing in the SSE assertions could say why. Reading
    the refusal is what turned a broken fixture into five tests.

    All four are 400s — the caller's request is malformed, not the server's fault —
    and each asserts nothing was persisted, because a refused ask that still wrote a
    row would leave an unanswerable question in the audit trail.
    """

    def test_response_requested_without_a_type_is_a_400( self, harness, wired ):
        from urllib.parse import urlencode
        r = harness.client.post( "/api/notify?" + urlencode( {
            "message": "M", "target_user": _EMAIL, "response_requested": "true" } ) )
        assert r.status_code == 400
        assert "response_type is required" in r.json()[ "detail" ]
        assert wired[ "persist_calls" ] == []

    def test_an_unknown_response_type_is_a_400_that_names_the_valid_ones( self, harness, wired ):
        """A caller cannot fix a rejection it cannot read, so the message lists them."""
        r = harness.client.post( _url( response_type="telepathy", response_default="D" ) )
        assert r.status_code == 400
        detail = r.json()[ "detail" ]
        assert "telepathy" in detail
        for valid in ( "yes_no", "open_ended", "multiple_choice", "open_ended_batch" ):
            assert valid in detail

    def test_multiple_choice_without_options_is_a_400( self, harness, wired ):
        """
        A multiple-choice card with no options renders a question and no way to
        answer it — worse than a refusal, because the ask then blocks until timeout.
        """
        r = harness.client.post( _url( response_type="multiple_choice", response_default="D" ) )
        assert r.status_code == 400
        assert "response_options" in r.json()[ "detail" ]
        assert wired[ "persist_calls" ] == []

    def test_multiple_choice_WITH_options_is_accepted( self, harness, wired ):
        """The other side of the guard — otherwise "always refuse" would pass above."""
        r = harness.client.post( _url(
            response_type="multiple_choice", response_default="D",
            response_options='{"questions": [{"question": "Q", "options": []}]}' ) )
        assert r.status_code == 200

    def test_a_zero_timeout_is_a_400_rather_than_an_instant_expiry( self, harness, wired ):
        """
        🔴 ZERO IS THE DANGEROUS VALUE, NOT A NEGATIVE ONE. `timeout_seconds=0` would
        otherwise sail into `asyncio.wait_for` and expire before the card could even
        render — an ask that answers itself with its default and looks like a real
        timeout. The guard is `<= 0`, and this is the half a `< 0` check would miss.
        """
        r = harness.client.post( _url( timeout_seconds=0, response_default="D" ) )
        assert r.status_code == 400
        assert "positive" in r.json()[ "detail" ]
        assert wired[ "persist_calls" ] == []

    def test_a_negative_timeout_is_also_a_400( self, harness, wired ):
        r = harness.client.post( _url( timeout_seconds=-5, response_default="D" ) )
        assert r.status_code == 400


class TestAskIdempotency:

    def test_a_repeated_key_re_attaches_instead_of_minting_a_second_card( self, harness, wired ):
        """
        🔴 THE BLOCKING VERBS ALWAYS STAMP A KEY, SO EVERY RETRY LANDS HERE. Without
        the re-attach a timed-out ask that the caller retries puts a SECOND question
        on the user's screen for something they were already asked. The second POST
        must persist nothing and push nothing.
        """
        key = a_uuid( "ask-key" )
        harness.client.post( _url( response_default="D", idempotency_key=key ) )
        before_persist = len( wired[ "persist_calls" ] )
        before_push    = len( harness.queue.calls_to( "push_notification" ) )

        harness.client.post( _url( response_default="D", idempotency_key=key ) )
        assert len( wired[ "persist_calls" ] )                      == before_persist
        assert len( harness.queue.calls_to( "push_notification" ) ) == before_push

    def test_the_re_attached_stream_still_opens_with_an_ack_for_the_ORIGINAL_ask( self, harness, wired ):
        """
        The re-attach hands back the FIRST ask's id, which is what makes it a
        re-attach rather than a new question. A generated id here would look fine and
        would point the client at a row that does not exist.
        """
        key = a_uuid( "ask-key-two" )
        harness.client.post( _url( response_default="D", idempotency_key=key ) )
        harness.repo.returns( "get_by_id", None )
        frames = _frames( harness.client.post( _url( response_default="D", idempotency_key=key ) ) )
        assert frames[ 0 ][ "status" ]          == "ack"
        assert frames[ 0 ][ "notification_id" ] == _NID

    def test_a_DIFFERENT_key_mints_a_new_ask( self, harness, wired ):
        harness.client.post( _url( response_default="D", idempotency_key=a_uuid( "k1" ) ) )
        harness.client.post( _url( response_default="D", idempotency_key=a_uuid( "k2" ) ) )
        assert len( wired[ "persist_calls" ] ) == 2
