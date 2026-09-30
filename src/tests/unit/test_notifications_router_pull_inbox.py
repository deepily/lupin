"""
Unit tests for the three PULL-INBOX endpoints of the notifications router:

    GET  /api/notifications/undelivered        — what you missed while offline
    GET  /api/notifications/answers-owed       — answers waiting to be handed back
    POST /api/notifications/answers-owed/ack   — the consume receipt

These three are one contract read in three places, and the load-bearing claims are
NEGATIVE ones a coverage number rewards you for skipping:

🔴 SERVING IS NOT ACKNOWLEDGING. `answers-owed` must NOT stamp `answer_delivered_at`
— that is the companion `/ack`, on consume. The lines of the serve handler run
identically whether it stamps or not, so the only thing that catches a regression is
naming the whole call list.

🔴 A 404 AND A 500 MEAN OPPOSITE THINGS TO THE CALLER. `ack` on a missing row is a
404 (stop retrying, it will never exist); a repo fault is a 500 (retry, it is
transient). Both are "an error", and the handler's blanket `except Exception` will
happily merge them if the `except HTTPException: raise` clause ahead of it is ever
removed. The tests assert the CODE.

🔴 THE AGE CAP MUST REACH THE QUERY. The undelivered drain has a storm guard — a
configured max-age that bounds how far back the inbox reaches. It is read in one
function and used in another, so it can be silently dropped in between while every
happy-path assertion still passes. Asserted as an argument at the repo boundary.

Fixture: `tests.helpers.notifications_endpoint_harness` — see that module's header for
the `lupin_app.main.config_mgr` trap that turns every 200 into a silent 500.
"""

import uuid

import pytest

from tests.helpers.notifications_endpoint_harness import (
    FROZEN_TIMESTAMP, a_uuid, assert_no_accidental_500, make_harness_fixture )

harness = make_harness_fixture()


# ── Fixtures whose every field names itself, so a crossed pair is visible ────────

class _Stamp:
    def __init__( self, text ):
        self._text = text
    def isoformat( self ):
        return self._text


class _Undelivered:
    """A row for the undelivered projector. Every field carries a DISTINCT value."""
    id         = a_uuid( "undelivered-row" )
    sender_id  = "SENDER-ID-VALUE"
    title      = "TITLE-VALUE"
    message    = "MESSAGE-VALUE"
    abstract   = "ABSTRACT-VALUE"
    type       = "TYPE-VALUE"
    priority   = "PRIORITY-VALUE"
    state      = "STATE-VALUE"
    job_id     = "JOB-ID-VALUE"
    payload    = { "PAYLOAD-KEY": "PAYLOAD-VALUE" }
    created_at = _Stamp( "CREATED-AT-VALUE" )


class _Owed:
    """A row for the owed-answer projector, with an asker hash embedded in sender_id."""
    id              = a_uuid( "owed-row" )
    sender_id       = "claude.code@lupin.deepily.ai#aaaa1111"
    sender_persona  = "PERSONA-VALUE"
    message         = "QUESTION-VALUE"
    title           = "TITLE-VALUE"
    abstract        = "ABSTRACT-VALUE"
    response_value  = "ANSWER-VALUE"
    responded_at    = _Stamp( "RESPONDED-AT-VALUE" )
    created_at      = _Stamp( "CREATED-AT-VALUE" )
    job_id          = "JOB-ID-VALUE"


# ═══════════════════════════════════════════════════════════════════════════════
# GET /api/notifications/undelivered
# ═══════════════════════════════════════════════════════════════════════════════

class TestTheUndeliveredInbox:

    def test_it_returns_the_projected_rows_under_a_counted_envelope( self, harness ):
        harness.repo.returns( "get_undelivered_for_recipient", [ _Undelivered() ] )
        r = harness.client.get( "/api/notifications/undelivered" )
        assert_no_accidental_500( r )
        body = r.json()
        assert body[ "status" ]            == "success"
        assert body[ "undelivered_count" ] == 1
        assert body[ "timestamp" ]         == FROZEN_TIMESTAMP
        assert body[ "notifications" ][ 0 ][ "message" ] == "MESSAGE-VALUE"

    def test_the_count_is_the_length_and_not_a_separately_derived_number( self, harness ):
        """
        🔴 A COUNT THAT IS COMPUTED TWICE CAN DISAGREE WITH ITSELF. One row makes
        every plausible wrong answer (1, len(...), a hardcoded 1) identical, so the
        discriminating fixture is THREE rows against a one-row control.
        """
        harness.repo.returns( "get_undelivered_for_recipient",
                              [ _Undelivered(), _Undelivered(), _Undelivered() ] )
        body = harness.client.get( "/api/notifications/undelivered" ).json()
        assert body[ "undelivered_count" ]     == 3
        assert len( body[ "notifications" ] )  == 3

    def test_an_empty_inbox_is_a_success_with_zero_and_not_a_404( self, harness ):
        """Nothing missed is an ANSWER, not an absence — a 404 would read as broken."""
        harness.repo.returns( "get_undelivered_for_recipient", [] )
        r = harness.client.get( "/api/notifications/undelivered" )
        assert r.status_code == 200
        assert r.json()[ "undelivered_count" ] == 0
        assert r.json()[ "notifications" ]     == []

    def test_the_query_is_keyed_by_the_AUTHENTICATED_user_not_a_parameter( self, harness ):
        """
        🔴 THIS IS THE AUTHORIZATION BOUNDARY. The recipient comes from the credential
        and from nowhere else — there is no user_id in the path or the query — so a
        handler taking it from anywhere else would let one seat read another's inbox.
        """
        harness.as_user( a_uuid( "the-authenticated-caller" ) )
        harness.repo.returns( "get_undelivered_for_recipient", [] )
        harness.client.get( "/api/notifications/undelivered" )
        call = harness.repo.call_to( "get_undelivered_for_recipient" )
        assert call.first == uuid.UUID( a_uuid( "the-authenticated-caller" ) )

    def test_the_storm_guard_age_cap_reaches_the_query( self, harness ):
        """
        🔴 THE CAP IS READ IN ONE FUNCTION AND USED IN ANOTHER. Dropping it between
        the two leaves every other assertion here passing while the 2026-06-03 storm
        guard is gone. The configured value is deliberately NOT the default, so
        "it forwarded the cap" and "it forwarded a constant 24" are different answers.
        """
        harness.config.set( "notification undelivered max age hours", 7 )
        harness.repo.returns( "get_undelivered_for_recipient", [] )
        harness.client.get( "/api/notifications/undelivered" )
        assert harness.repo.call_to( "get_undelivered_for_recipient" ).kwargs[ "max_age_hours" ] == 7

    def test_the_limit_query_param_reaches_the_query( self, harness ):
        harness.repo.returns( "get_undelivered_for_recipient", [] )
        harness.client.get( "/api/notifications/undelivered?limit=5" )
        assert harness.repo.call_to( "get_undelivered_for_recipient" ).kwargs[ "limit" ] == 5

    def test_it_is_a_pure_read( self, harness ):
        """Pulling the inbox must not mutate it — the drain is not the acknowledgement."""
        harness.repo.returns( "get_undelivered_for_recipient", [ _Undelivered() ] )
        harness.client.get( "/api/notifications/undelivered" )
        harness.repo.assert_only_called( "get_undelivered_for_recipient" )

    def test_a_credential_that_is_not_a_uuid_is_a_400_and_not_a_500( self, harness ):
        """
        A malformed caller identity is the CALLER's fault (400), not the server's
        (500). Merging them sends a client into a retry loop over a request that can
        never succeed.
        """
        harness.as_user( "not-a-uuid" )
        r = harness.client.get( "/api/notifications/undelivered" )
        assert r.status_code == 400
        assert "uuid" in r.json()[ "detail" ].lower()

    def test_the_bad_credential_is_refused_BEFORE_the_database_is_touched( self, harness ):
        """The 400 must be a guard, not a caught exception from a query that ran."""
        harness.as_user( "not-a-uuid" )
        harness.client.get( "/api/notifications/undelivered" )
        assert harness.repo.calls == []
        assert harness.sessions   == []

    def test_a_repo_fault_is_a_500( self, harness ):
        harness.repo.raises( "get_undelivered_for_recipient", RuntimeError( "connection reset" ) )
        r = harness.client.get( "/api/notifications/undelivered" )
        assert r.status_code == 500

    def test_a_dead_database_is_a_500_and_not_an_empty_inbox( self, harness ):
        """
        🔴 THE WORST POSSIBLE ANSWER HERE IS 200 WITH AN EMPTY LIST. "You missed
        nothing" and "I could not look" are indistinguishable to the caller, and one
        of them silently discards the durable outbox.
        """
        harness.fail_db()
        r = harness.client.get( "/api/notifications/undelivered" )
        assert r.status_code == 500


# ═══════════════════════════════════════════════════════════════════════════════
# GET /api/notifications/answers-owed
# ═══════════════════════════════════════════════════════════════════════════════

class TestTheAnswersOwedInbox:

    def _get( self, harness, query="persona=krishna" ):
        return harness.client.get( f"/api/notifications/answers-owed?{query}" )

    def test_it_returns_owed_envelopes_under_a_counted_envelope( self, harness ):
        harness.repo.returns( "get_answers_owed_for_persona", [ _Owed(), _Owed() ] )
        r = self._get( harness )
        assert_no_accidental_500( r )
        body = r.json()
        assert body[ "status" ]     == "success"
        assert body[ "owed_count" ] == 2
        assert body[ "timestamp" ]  == FROZEN_TIMESTAMP

    def test_each_envelope_carries_the_question_beside_the_answer( self, harness ):
        """
        🔴 A BARE ANSWER IS WORSE THAN NOTHING — the model binds it to whatever it is
        doing now. The question text travelling with the answer is the whole point of
        the envelope, and the two fields carry different values so a handler emitting
        the answer twice is visible.
        """
        harness.repo.returns( "get_answers_owed_for_persona", [ _Owed() ] )
        item = self._get( harness ).json()[ "answers" ][ 0 ]
        assert item[ "question" ]       == "QUESTION-VALUE"
        assert item[ "response_value" ] == "ANSWER-VALUE"
        assert item[ "responded_at" ]   == "RESPONDED-AT-VALUE"

    def test_the_persona_is_the_retrieval_key_and_is_matched_alone( self, harness ):
        """Ruling 6: persona alone selects; the caller's own identity is not a filter."""
        harness.repo.returns( "get_answers_owed_for_persona", [] )
        self._get( harness, "persona=PERSONA-QUERY-VALUE" )
        assert harness.repo.call_to( "get_answers_owed_for_persona" ).first == "PERSONA-QUERY-VALUE"

    def test_session_hash8_flags_but_NEVER_filters( self, harness ):
        """
        🔴 THE TWO HALVES OF RULING 6, ASSERTED TOGETHER. A hash that filtered would
        also flag correctly on the rows it let through, so flagging alone cannot
        prove it. The row is returned AND flagged: it survived a hash it does not
        match.
        """
        harness.repo.returns( "get_answers_owed_for_persona", [ _Owed() ] )
        body = self._get( harness, "persona=krishna&session_hash8=bbbb2222" ).json()
        assert body[ "owed_count" ] == 1, "a non-matching session_hash8 must not filter"
        assert body[ "answers" ][ 0 ][ "from_earlier_session" ] is True
        assert "bbbb2222" not in str( harness.repo.call_to( "get_answers_owed_for_persona" ) )

    def test_the_asking_session_itself_is_not_flagged_as_earlier( self, harness ):
        """The other side of the same fork — same hash, so the flag must go False."""
        harness.repo.returns( "get_answers_owed_for_persona", [ _Owed() ] )
        body = self._get( harness, "persona=krishna&session_hash8=aaaa1111" ).json()
        assert body[ "answers" ][ 0 ][ "from_earlier_session" ] is False

    def test_a_missing_persona_is_a_422( self, harness ):
        """persona is Query(...) — required. Omitting it is a validation error."""
        r = harness.client.get( "/api/notifications/answers-owed" )
        assert r.status_code == 422

    def test_an_iso_since_cursor_reaches_the_query_as_a_datetime( self, harness ):
        """
        The cursor is parsed at the edge, not passed as a string — a repo comparing a
        str to a timestamp column would either error or silently match nothing.
        """
        from datetime import datetime
        harness.repo.returns( "get_answers_owed_for_persona", [] )
        self._get( harness, "persona=krishna&since=2026-08-30T12:34:56" )
        since = harness.repo.call_to( "get_answers_owed_for_persona" ).kwargs[ "since" ]
        assert since == datetime( 2026, 8, 30, 12, 34, 56 )

    def test_no_since_cursor_forwards_none_rather_than_omitting_it( self, harness ):
        harness.repo.returns( "get_answers_owed_for_persona", [] )
        self._get( harness )
        assert harness.repo.call_to( "get_answers_owed_for_persona" ).kwargs[ "since" ] is None

    def test_an_unparseable_since_is_a_400_and_not_a_500( self, harness ):
        """
        🔴 THE 400 IS INSIDE A try/except THAT CONVERTS EVERYTHING ELSE TO 500. The
        `except HTTPException: raise` clause is the only thing keeping this a 400,
        and a caller reads them oppositely: fix your cursor vs retry later.
        """
        r = self._get( harness, "persona=krishna&since=not-a-timestamp" )
        assert r.status_code == 400
        assert "ISO-8601" in r.json()[ "detail" ]

    def test_a_bad_cursor_is_refused_before_the_database_is_touched( self, harness ):
        self._get( harness, "persona=krishna&since=not-a-timestamp" )
        assert harness.repo.calls == []

    def test_SERVING_DOES_NOT_ACKNOWLEDGE( self, harness ):
        """
        🔴 THE LOAD-BEARING NEGATIVE CLAIM. Ack-on-consume, never on serve: a dropped
        serve response must leave the answer still owed. The handler's lines run
        identically whether it stamps the receipt or not, so the whole call list is
        named rather than one absence spot-checked.
        """
        harness.repo.returns( "get_answers_owed_for_persona", [ _Owed() ] )
        self._get( harness )
        harness.repo.assert_only_called( "get_answers_owed_for_persona" )
        harness.repo.assert_never_called( "mark_answer_delivered", "update_state",
                                          "mark_expired", "delete" )

    def test_a_repo_fault_is_a_500( self, harness ):
        harness.repo.raises( "get_answers_owed_for_persona", RuntimeError( "boom" ) )
        assert self._get( harness ).status_code == 500


# ═══════════════════════════════════════════════════════════════════════════════
# POST /api/notifications/answers-owed/ack
# ═══════════════════════════════════════════════════════════════════════════════

class TestTheAckReceipt:

    _URL = "/api/notifications/answers-owed/ack"
    _NID = a_uuid( "acked-notification" )

    def test_it_stamps_the_receipt_for_the_id_it_was_given( self, harness ):
        harness.repo.returns( "mark_answer_delivered", object() )
        r = harness.client.post( self._URL, json={ "notification_id": self._NID } )
        assert_no_accidental_500( r )
        assert r.status_code == 200
        assert harness.repo.call_to( "mark_answer_delivered" ).first == uuid.UUID( self._NID )

    def test_the_success_envelope_echoes_the_id_and_the_timestamp( self, harness ):
        harness.repo.returns( "mark_answer_delivered", object() )
        body = harness.client.post( self._URL, json={ "notification_id": self._NID } ).json()
        assert body[ "status" ]          == "success"
        assert body[ "notification_id" ] == self._NID
        assert body[ "timestamp" ]       == FROZEN_TIMESTAMP

    def test_the_row_is_stamped_and_NEVER_deleted( self, harness ):
        """Ruling 2: the row survives the ack. Only naming the call list catches a delete."""
        harness.repo.returns( "mark_answer_delivered", object() )
        harness.client.post( self._URL, json={ "notification_id": self._NID } )
        harness.repo.assert_only_called( "mark_answer_delivered" )

    def test_a_missing_notification_id_is_a_422( self, harness ):
        r = harness.client.post( self._URL, json={} )
        assert r.status_code == 422
        assert "notification_id" in r.json()[ "detail" ]

    def test_an_empty_notification_id_is_a_422_and_not_a_lookup( self, harness ):
        """
        Empty string is falsy, so it takes the same guard as absent — asserted
        because a handler switching to `is None` would send "" to uuid.UUID and
        produce a 500 for what is plainly a client error.
        """
        r = harness.client.post( self._URL, json={ "notification_id": "" } )
        assert r.status_code == 422
        assert harness.repo.calls == []

    def test_an_unknown_row_is_a_404_and_not_a_200( self, harness ):
        """
        🔴 THE REPO RETURNS None FOR A ROW THAT IS NOT THERE, AND None IS NOT AN
        ERROR. Nothing raises; the handler must notice and convert. A 200 here tells
        the client its answer was acknowledged when nothing was written.
        """
        harness.repo.returns( "mark_answer_delivered", None )
        r = harness.client.post( self._URL, json={ "notification_id": self._NID } )
        assert r.status_code == 404
        assert self._NID in r.json()[ "detail" ]

    def test_a_malformed_uuid_is_a_500_not_a_404( self, harness ):
        """
        The current contract, asserted as it stands rather than as it might ideally
        be: `uuid.UUID` raises inside the worker and the blanket handler makes it a
        500. It is NOT a 404 — the row's existence was never established — and
        pinning that keeps a later refactor from quietly turning a fault into
        "no such notification".
        """
        r = harness.client.post( self._URL, json={ "notification_id": "not-a-uuid" } )
        assert r.status_code == 500

    def test_a_repo_fault_is_a_500( self, harness ):
        harness.repo.raises( "mark_answer_delivered", RuntimeError( "connection reset" ) )
        r = harness.client.post( self._URL, json={ "notification_id": self._NID } )
        assert r.status_code == 500

    def test_a_dead_database_is_a_500_and_not_a_404( self, harness ):
        """
        🔴 THE TWO FAILURES POINT OPPOSITE WAYS. A 404 tells the client to stop — the
        answer stays owed forever and nothing ever acks it. A 500 tells it to retry,
        which is the correct response to a connection that dropped.
        """
        harness.fail_db()
        r = harness.client.post( self._URL, json={ "notification_id": self._NID } )
        assert r.status_code == 500
