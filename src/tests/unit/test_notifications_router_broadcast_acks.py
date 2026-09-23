"""
Unit tests for the per-broadcast ack read (row 4f320c27 S4):

    GET /api/notifications/broadcast-acks/{broadcast_id}

plus `_project_broadcast_ack`, the projector it answers through.

WHAT THIS ENDPOINT IS FOR, AND WHY IT IS NOT THE UNDELIVERED INBOX. A broadcast's
ack tally lives in page memory today: reload, and it is gone. The fix saves each ack
as a notifications row (S3); this is the read that rebuilds the tally from those rows.

🔴 THE LOAD-BEARING NEGATIVE — IT MUST NOT FILTER ON DELIVERY STATE. The obvious
place to hang "catch up on what I missed" is the undelivered drain, and that drain
skips anything already delivered to a socket. An ack that lands while a browser is
open is marked delivered instantly, so a tally rebuilt from the undelivered inbox
comes back EMPTY for exactly the acks the user already half-saw — a recovery that
looks fixed and recovers nothing. This is María's condition on the plan, and it is
asserted here twice: once at the wire (a delivered row comes back) and once at the
boundary (the handler forwards no state argument at all).

🔴 THE AUTHORIZATION BOUNDARY IS THE CREDENTIAL. There is no user id in the path.
The recipient comes from the token and nowhere else, so one seat cannot read another
account's acks by guessing a broadcast id.

Fixture: `tests.helpers.notifications_endpoint_harness` — see that module's header for
the `lupin_app.main.config_mgr` trap that turns every 200 into a silent 500.
"""

import uuid

import pytest

import cosa.rest.routers.notifications as notif
from tests.helpers.notifications_endpoint_harness import (
    FROZEN_TIMESTAMP, a_uuid, assert_no_accidental_500, make_harness_fixture )

harness = make_harness_fixture()


_BROADCAST_ID = "BROADCAST-ID-VALUE"

# A sentinel distinct from None, because None is itself a MEANINGFUL payload here
# (the pre-S3 / corrupted-write case) and must be passable.
_MISSING = object()


class _Stamp:
    def __init__( self, text ):
        self._text = text
    def isoformat( self ):
        return self._text


class _AckRow:
    """
    A saved ack row. Every field carries a DISTINCT, self-naming value so a crossed
    pair — persona_icon landing in persona_color, say — is visible on sight rather
    than plausible.
    """
    def __init__( self, session_id="SESSION-ID-VALUE", state="STATE-VALUE",
                  created="CREATED-AT-VALUE", row_id="ack-row", payload=_MISSING ):
        self.id      = a_uuid( row_id )
        self.state   = state
        self.created_at = _Stamp( created )
        self.payload = {
            "broadcast_id"  : _BROADCAST_ID,
            "session_id"    : session_id,
            "persona_name"  : "PERSONA-NAME-VALUE",
            "persona_icon"  : "PERSONA-ICON-VALUE",
            "persona_color" : "PERSONA-COLOR-VALUE",
            "status"        : "ACK-STATUS-VALUE",
            "body_summary"  : "BODY-SUMMARY-VALUE",
        } if payload is _MISSING else payload


def _get( harness, broadcast_id=_BROADCAST_ID, query="" ):
    return harness.client.get( f"/api/notifications/broadcast-acks/{broadcast_id}{query}" )


# ═══════════════════════════════════════════════════════════════════════════════
# _project_broadcast_ack
# ═══════════════════════════════════════════════════════════════════════════════

class TestTheAckProjector:

    def test_it_lifts_every_identity_field_out_of_the_payload( self ):
        """
        A consumer folding a tally must not have to know the broadcast id lives one
        level down. Each assertion names a DIFFERENT source value, so two fields
        reading the same key would fail rather than agree.
        """
        out = notif._project_broadcast_ack( _AckRow() )
        assert out[ "broadcast_id" ]  == _BROADCAST_ID
        assert out[ "session_id" ]    == "SESSION-ID-VALUE"
        assert out[ "persona_name" ]  == "PERSONA-NAME-VALUE"
        assert out[ "persona_icon" ]  == "PERSONA-ICON-VALUE"
        assert out[ "persona_color" ] == "PERSONA-COLOR-VALUE"
        assert out[ "ack_status" ]    == "ACK-STATUS-VALUE"
        assert out[ "body_summary" ]  == "BODY-SUMMARY-VALUE"

    def test_it_carries_the_row_id_and_state_and_stamp_from_the_row_itself( self ):
        out = notif._project_broadcast_ack( _AckRow() )
        assert out[ "id" ]         == a_uuid( "ack-row" )
        assert out[ "state" ]      == "STATE-VALUE"
        assert out[ "created_at" ] == "CREATED-AT-VALUE"

    def test_it_does_NOT_echo_the_payload_blob_as_well( self ):
        """
        Everything the payload holds is named on the envelope. A second copy under
        another key is a second thing to keep in step, and the two would diverge the
        first time a field was renamed on one side.
        """
        assert "payload" not in notif._project_broadcast_ack( _AckRow() )

    def test_a_row_with_a_NULL_payload_projects_nulls_rather_than_raising( self ):
        """
        🔴 ONE UNATTRIBUTABLE ROW MUST NOT 500 THE WHOLE BROADCAST. A pre-S3 ack (or
        a corrupted write) has no payload; the honest answer is an ack with no
        attribution, not a broadcast whose tally cannot be read at all.
        """
        out = notif._project_broadcast_ack( _AckRow( payload=None ) )
        assert out[ "broadcast_id" ] is None
        assert out[ "session_id" ]   is None
        assert out[ "id" ]           == a_uuid( "ack-row" )

    def test_a_row_with_no_stamp_projects_a_null_created_at( self ):
        row            = _AckRow()
        row.created_at = None
        assert notif._project_broadcast_ack( row )[ "created_at" ] is None


# ═══════════════════════════════════════════════════════════════════════════════
# GET /api/notifications/broadcast-acks/{broadcast_id}
# ═══════════════════════════════════════════════════════════════════════════════

class TestThePerBroadcastAckRead:

    def test_it_returns_the_projected_acks_under_a_counted_envelope( self, harness ):
        harness.repo.returns( "get_latest_acks_for_broadcast", [ _AckRow() ] )
        r = _get( harness )
        assert_no_accidental_500( r )
        body = r.json()
        assert body[ "status" ]       == "success"
        assert body[ "broadcast_id" ] == _BROADCAST_ID
        assert body[ "ack_count" ]    == 1
        assert body[ "timestamp" ]    == FROZEN_TIMESTAMP
        assert body[ "acks" ][ 0 ][ "persona_name" ] == "PERSONA-NAME-VALUE"

    def test_the_count_is_the_length_and_not_a_separately_derived_number( self, harness ):
        """
        One row makes every plausible wrong answer (1, len(...), a hardcoded 1)
        identical, so the discriminating fixture is THREE against a one-row control.
        """
        harness.repo.returns( "get_latest_acks_for_broadcast",
                              [ _AckRow( session_id="a" ), _AckRow( session_id="b" ), _AckRow( session_id="c" ) ] )
        body = _get( harness ).json()
        assert body[ "ack_count" ]     == 3
        assert len( body[ "acks" ] )   == 3

    def test_a_broadcast_nobody_acked_is_a_success_with_zero_and_not_a_404( self, harness ):
        """Nobody has acked YET is an answer; a 404 would read as "no such broadcast"."""
        harness.repo.returns( "get_latest_acks_for_broadcast", [] )
        r = _get( harness )
        assert r.status_code == 200
        assert r.json()[ "ack_count" ] == 0
        assert r.json()[ "acks" ]      == []

    # ── the negative this endpoint exists for ────────────────────────────────────

    def test_an_ack_ALREADY_DELIVERED_to_a_live_socket_still_comes_back( self, harness ):
        """
        🔴 MARÍA'S CONDITION, AT THE WIRE. This is the case the undelivered drain
        cannot answer: the socket was open, the row was marked delivered on the spot,
        and the tally still has to survive the reload. A handler that reached for the
        undelivered inbox returns [] here and passes every other test in this file.
        """
        harness.repo.returns( "get_latest_acks_for_broadcast", [ _AckRow( state="delivered" ) ] )
        body = _get( harness ).json()
        assert body[ "ack_count" ] == 1
        assert body[ "acks" ][ 0 ][ "state" ] == "delivered"

    def test_the_handler_forwards_NO_state_or_age_filter_to_the_query( self, harness ):
        """
        🔴 THE SAME CONDITION, AT THE BOUNDARY. The wire test above passes on any
        stub that hands back a row; this one names the whole argument list, so a
        state= or max_age_hours= filter smuggled in later is a failure rather than a
        silently narrower answer.
        """
        harness.repo.returns( "get_latest_acks_for_broadcast", [] )
        _get( harness )
        call = harness.repo.call_to( "get_latest_acks_for_broadcast" )
        assert set( call.kwargs ) == { "limit" }, call
        assert len( call.args ) == 2, call

    def test_it_does_not_reach_the_undelivered_drain_at_all( self, harness ):
        harness.repo.returns( "get_latest_acks_for_broadcast", [] )
        _get( harness )
        harness.repo.assert_never_called( "get_undelivered_for_recipient",
                                          "count_undelivered_for_recipient" )

    # ── scope, parameters, purity ────────────────────────────────────────────────

    def test_the_query_is_keyed_by_the_AUTHENTICATED_user_not_a_parameter( self, harness ):
        """
        🔴 THE AUTHORIZATION BOUNDARY. There is no user id in the path — the
        recipient comes from the credential, so a caller cannot read another
        account's acks by guessing a broadcast id.
        """
        harness.as_user( a_uuid( "the-authenticated-caller" ) )
        harness.repo.returns( "get_latest_acks_for_broadcast", [] )
        _get( harness )
        call = harness.repo.call_to( "get_latest_acks_for_broadcast" )
        assert call.args[ 0 ] == uuid.UUID( a_uuid( "the-authenticated-caller" ) )

    def test_the_broadcast_id_from_the_path_reaches_the_query( self, harness ):
        harness.repo.returns( "get_latest_acks_for_broadcast", [] )
        _get( harness, broadcast_id="THE-PATH-BROADCAST" )
        assert harness.repo.call_to( "get_latest_acks_for_broadcast" ).args[ 1 ] == "THE-PATH-BROADCAST"

    def test_the_broadcast_id_is_echoed_from_the_path_and_not_from_a_row( self, harness ):
        """
        With zero rows there is no payload to read it back out of, so an echo that
        came from a row would be None here.
        """
        harness.repo.returns( "get_latest_acks_for_broadcast", [] )
        assert _get( harness, broadcast_id="ECHO-ME" ).json()[ "broadcast_id" ] == "ECHO-ME"

    def test_the_limit_query_param_reaches_the_query( self, harness ):
        harness.repo.returns( "get_latest_acks_for_broadcast", [] )
        _get( harness, query="?limit=7" )
        assert harness.repo.call_to( "get_latest_acks_for_broadcast" ).kwargs[ "limit" ] == 7

    def test_it_is_a_pure_read( self, harness ):
        """
        Rebuilding a tally must not mutate it. The handler runs identical lines
        whether it writes or not, so only naming the WHOLE call list catches a write
        added later.
        """
        harness.repo.returns( "get_latest_acks_for_broadcast", [ _AckRow() ] )
        _get( harness )
        harness.repo.assert_only_called( "get_latest_acks_for_broadcast" )

    def test_the_repository_is_built_on_the_session_get_db_handed_out( self, harness ):
        harness.repo.returns( "get_latest_acks_for_broadcast", [] )
        _get( harness )
        harness.assert_repo_built_on_the_open_session()

    # ── the routing trap ─────────────────────────────────────────────────────────

    def test_broadcast_acks_is_not_swallowed_as_a_user_id_path_parameter( self, harness ):
        """
        🔴 A ROUTE-ORDER DEFECT LOOKS LIKE A DATA DEFECT. `/notifications/{user_id}/next`
        is registered in the same router and matches the same two-segment shape; if it
        were declared first, this request would land THERE and the caller would get a
        confusing 200 full of the wrong thing. The discriminator is which repo method
        the handler reached.
        """
        harness.repo.returns( "get_latest_acks_for_broadcast", [] )
        r = _get( harness )
        assert r.status_code == 200
        assert harness.repo.names == [ "get_latest_acks_for_broadcast" ]

    # ── the failure arcs ─────────────────────────────────────────────────────────

    def test_a_credential_that_is_not_a_uuid_is_a_400_and_not_a_500( self, harness ):
        harness.as_user( "not-a-uuid" )
        r = _get( harness )
        assert r.status_code == 400
        assert "uuid" in r.json()[ "detail" ].lower()

    def test_the_bad_credential_is_refused_BEFORE_the_database_is_touched( self, harness ):
        harness.as_user( "not-a-uuid" )
        _get( harness )
        assert harness.repo.calls == []
        assert harness.sessions   == []

    def test_a_repo_fault_is_a_500( self, harness ):
        harness.repo.raises( "get_latest_acks_for_broadcast", RuntimeError( "connection reset" ) )
        assert _get( harness ).status_code == 500

    def test_a_dead_database_is_a_500_and_not_an_empty_tally( self, harness ):
        """
        🔴 THE WORST POSSIBLE ANSWER IS 200 WITH AN EMPTY LIST. "Nobody acked" and
        "I could not look" are indistinguishable to the caller, and one of them
        silently reports a broadcast as ignored by the entire fleet.
        """
        harness.fail_db()
        assert _get( harness ).status_code == 500
