"""
Unit tests for the notification LIFECYCLE endpoints — the six that read, play,
dismiss and delete rather than create:

    POST   /api/notifications/undelivered/dismiss   — zero the missed-while-away badge
    GET    /api/notifications/{user_id}             — the in-memory queue listing
    GET    /api/notifications/{user_id}/next        — the next unplayed, without playing it
    POST   /api/notifications/{notification_id}/played
    DELETE /api/notifications/{notification_id}
    DELETE /api/notifications/bulk/{user_email}     — the Clear All button

Five of them share one hazard: THE HANDLER DECIDES ON A BOOLEAN THE COLLABORATOR
RETURNS, and `False` is not an exception. Nothing raises when a row is missing — the
handler must notice and convert to a 404 itself. A regression there returns 200 for
work that never happened, which is invisible to any test that only asks "did it not
blow up".

🔴 THE DISMISS ENDPOINT REPORTS TWO NUMBERS FROM TWO SEPARATE QUERIES, and the tests
give them DIFFERENT values on purpose. `dismissed_count` and `undelivered_count` come
from `dismiss_undelivered_for_recipient` and `count_undelivered_for_recipient`
respectively; if a fixture returned the same number for both, a handler that echoed
one into both fields would pass.

🔴 AND THE `{user_id}` ROUTE IS A CATCH-ALL SITTING BENEATH THE STATIC ONES. FastAPI
matches in declaration order, so `/notifications/undelivered` is only NOT captured as
a user id because it is declared first. That ordering is a property of the file, not
of any one handler, so it is asserted here directly.

Fixture: `tests.helpers.notifications_endpoint_harness`.
"""

import uuid

import pytest

from tests.helpers.notifications_endpoint_harness import (
    FROZEN_TIMESTAMP, a_uuid, assert_no_accidental_500, make_harness_fixture )

harness = make_harness_fixture()


_USER  = a_uuid( "lifecycle-user" )
_NID   = "notification-id-value"
_EMAIL = "someone@example.com"


# ═══════════════════════════════════════════════════════════════════════════════
# POST /api/notifications/undelivered/dismiss
# ═══════════════════════════════════════════════════════════════════════════════

class TestDismissingTheMissedBadge:

    _URL = "/api/notifications/undelivered/dismiss"

    def _wire( self, harness, dismissed=3, remaining=0 ):
        harness.repo.returns( "dismiss_undelivered_for_recipient", dismissed )
        harness.repo.returns( "count_undelivered_for_recipient",   remaining )

    def test_it_reports_both_counts_from_their_own_queries( self, harness ):
        """
        🔴 THE TWO NUMBERS MUST COME FROM DIFFERENT PLACES. Given 3 and 0 a handler
        echoing one into both fields is visible; given 0 and 0 it is not.
        """
        self._wire( harness, dismissed=3, remaining=0 )
        r = harness.client.post( self._URL )
        assert_no_accidental_500( r )
        body = r.json()
        assert body[ "status" ]            == "success"
        assert body[ "dismissed_count" ]   == 3
        assert body[ "undelivered_count" ] == 0
        assert body[ "timestamp" ]         == FROZEN_TIMESTAMP

    def test_the_reported_remainder_is_the_POST_dismiss_count( self, harness ):
        """
        The badge is redrawn from `undelivered_count`, so it must be counted AFTER the
        dismiss, not before. A non-zero remainder distinguishes "counted again" from
        "assumed zero because we just dismissed".
        """
        self._wire( harness, dismissed=2, remaining=5 )
        body = harness.client.post( self._URL ).json()
        assert body[ "undelivered_count" ] == 5
        assert harness.repo.names == [ "dismiss_undelivered_for_recipient",
                                       "count_undelivered_for_recipient" ]

    def test_both_queries_are_scoped_to_the_authenticated_recipient( self, harness ):
        harness.as_user( _USER )
        self._wire( harness )
        harness.client.post( self._URL )
        for name in ( "dismiss_undelivered_for_recipient", "count_undelivered_for_recipient" ):
            assert harness.repo.call_to( name ).first == uuid.UUID( _USER )

    def test_the_age_cap_reaches_BOTH_queries( self, harness ):
        """
        The dismiss mirrors the count query, cap included — otherwise the badge and
        the drain disagree about which rows exist and the badge never reaches zero.
        Two call sites, so forwarding it to only one is a real and reachable defect.
        """
        harness.config.set( "notification undelivered max age hours", 9 )
        self._wire( harness )
        harness.client.post( self._URL )
        for name in ( "dismiss_undelivered_for_recipient", "count_undelivered_for_recipient" ):
            assert harness.repo.call_to( name ).kwargs[ "max_age_hours" ] == 9

    def test_the_state_is_preserved_and_nothing_is_deleted( self, harness ):
        """Soft-dismiss: the never-delivered audit trail must survive the button."""
        self._wire( harness )
        harness.client.post( self._URL )
        harness.repo.assert_never_called( "delete", "bulk_delete_by_user",
                                          "update_state", "mark_expired" )

    def test_a_credential_that_is_not_a_uuid_is_a_400_before_any_query( self, harness ):
        """
        🔴 THIS HANDLER HAS NO `except HTTPException: raise` CLAUSE, unlike its twin.
        The 400 survives only because it is raised OUTSIDE the try. Moving it inside —
        an innocuous-looking tidy-up — turns it into a 500, so both the code and the
        untouched database are asserted.
        """
        harness.as_user( "not-a-uuid" )
        r = harness.client.post( self._URL )
        assert r.status_code == 400
        assert harness.repo.calls == []

    def test_a_repo_fault_is_a_500( self, harness ):
        harness.repo.raises( "dismiss_undelivered_for_recipient", RuntimeError( "boom" ) )
        assert harness.client.post( self._URL ).status_code == 500


# ═══════════════════════════════════════════════════════════════════════════════
# GET /api/notifications/{user_id}
# ═══════════════════════════════════════════════════════════════════════════════

class TestListingAUsersNotifications:

    def _wire( self, harness, items ):
        harness.queue.strict().returns( "get_user_notifications", items )

    def test_it_returns_the_queues_items_under_a_counted_envelope( self, harness ):
        self._wire( harness, [ { "id": "A" }, { "id": "B" } ] )
        r = harness.client.get( f"/api/notifications/{_USER}" )
        assert_no_accidental_500( r )
        body = r.json()
        assert body[ "status" ]             == "success"
        assert body[ "user_id" ]            == _USER
        assert body[ "notification_count" ] == 2
        assert body[ "notifications" ]      == [ { "id": "A" }, { "id": "B" } ]
        assert body[ "timestamp" ]          == FROZEN_TIMESTAMP

    def test_the_user_id_reaches_the_queue_as_a_keyword( self, harness ):
        self._wire( harness, [] )
        harness.client.get( f"/api/notifications/{_USER}" )
        assert harness.queue.call_to( "get_user_notifications" ).kwargs[ "user_id" ] == _USER

    def test_include_played_defaults_to_true_and_is_forwarded( self, harness ):
        self._wire( harness, [] )
        harness.client.get( f"/api/notifications/{_USER}" )
        assert harness.queue.call_to( "get_user_notifications" ).kwargs[ "include_played" ] is True

    def test_include_played_false_is_forwarded_as_false_not_dropped( self, harness ):
        """
        🔴 A DROPPED FILTER IS THE DEFAULT, AND THE DEFAULT IS `True`. So "forwarded
        false" and "forgot to forward it" differ by exactly this assertion — every
        other observable in the response is identical.
        """
        self._wire( harness, [] )
        harness.client.get( f"/api/notifications/{_USER}?include_played=false" )
        call = harness.queue.call_to( "get_user_notifications" )
        assert call.kwargs[ "include_played" ] is False
        assert call.kwargs[ "include_played" ] != "false", "the string 'false' is truthy"

    def test_the_limit_truncates_and_the_count_follows_the_truncation( self, harness ):
        """
        The queue is asked for everything and the slice happens here, so the count
        must be of what is RETURNED. Three items to a limit of two makes "counted
        before slicing" (3) and "counted after" (2) different answers.
        """
        self._wire( harness, [ { "id": "A" }, { "id": "B" }, { "id": "C" } ] )
        body = harness.client.get( f"/api/notifications/{_USER}?limit=2" ).json()
        assert body[ "notification_count" ] == 2
        assert body[ "notifications" ]      == [ { "id": "A" }, { "id": "B" } ]
        assert body[ "limit" ]              == 2

    def test_a_limit_larger_than_the_result_truncates_nothing( self, harness ):
        """The other side of `limit < len(...)` — the guard, not just the slice."""
        self._wire( harness, [ { "id": "A" } ] )
        body = harness.client.get( f"/api/notifications/{_USER}?limit=50" ).json()
        assert body[ "notification_count" ] == 1

    def test_the_limit_is_NOT_pushed_down_to_the_queue( self, harness ):
        """
        Pinning today's contract: the queue is asked for the unlimited set and the
        endpoint slices. Worth stating, because pushing the limit down would look like
        an optimisation and would silently change which items an offset ever reaches.
        """
        self._wire( harness, [] )
        harness.client.get( f"/api/notifications/{_USER}?limit=2" )
        assert "limit" not in harness.queue.call_to( "get_user_notifications" ).kwargs

    def test_a_queue_fault_is_a_500( self, harness ):
        harness.queue.strict().raises( "get_user_notifications", RuntimeError( "boom" ) )
        assert harness.client.get( f"/api/notifications/{_USER}" ).status_code == 500


# ═══════════════════════════════════════════════════════════════════════════════
# GET /api/notifications/{user_id}/next
# ═══════════════════════════════════════════════════════════════════════════════

class TestTheNextUnplayed:

    def test_a_hit_reports_found_and_carries_the_item( self, harness ):
        harness.queue.strict().returns( "get_next_unplayed", { "id": "NEXT-ITEM" } )
        r = harness.client.get( f"/api/notifications/{_USER}/next" )
        assert_no_accidental_500( r )
        body = r.json()
        assert body[ "status" ]       == "found"
        assert body[ "notification" ] == { "id": "NEXT-ITEM" }

    def test_a_miss_reports_none_available_with_a_null_and_still_a_200( self, harness ):
        """
        🔴 "NOTHING TO PLAY" IS AN ANSWER, NOT AN ERROR. A 404 here would make an idle
        client indistinguishable from a broken one, and the poller backs off on 404.
        The two branches differ in `status` AND in `notification`, so both are read.
        """
        harness.queue.strict().returns( "get_next_unplayed", None )
        r = harness.client.get( f"/api/notifications/{_USER}/next" )
        assert r.status_code == 200
        assert r.json()[ "status" ]       == "none_available"
        assert r.json()[ "notification" ] is None

    def test_reading_the_next_one_does_not_play_it( self, harness ):
        """The docstring's promise: fetch without modifying played state."""
        harness.queue.strict().returns( "get_next_unplayed", { "id": "NEXT-ITEM" } )
        harness.client.get( f"/api/notifications/{_USER}/next" )
        harness.queue.assert_only_called( "get_next_unplayed" )

    def test_it_asks_for_the_path_users_next_item( self, harness ):
        harness.queue.strict().returns( "get_next_unplayed", None )
        harness.client.get( f"/api/notifications/{_USER}/next" )
        assert harness.queue.call_to( "get_next_unplayed" ).first == _USER

    def test_a_queue_fault_is_a_500( self, harness ):
        harness.queue.strict().raises( "get_next_unplayed", RuntimeError( "boom" ) )
        assert harness.client.get( f"/api/notifications/{_USER}/next" ).status_code == 500


# ═══════════════════════════════════════════════════════════════════════════════
# POST /api/notifications/{notification_id}/played
# ═══════════════════════════════════════════════════════════════════════════════

class TestMarkingPlayed:

    _URL = f"/api/notifications/{_NID}/played"

    def test_a_true_return_is_a_200_naming_the_notification( self, harness ):
        harness.queue.strict().returns( "mark_played", True )
        r = harness.client.post( self._URL )
        assert_no_accidental_500( r )
        assert r.status_code == 200
        assert r.json()[ "notification_id" ] == _NID
        assert r.json()[ "timestamp" ]       == FROZEN_TIMESTAMP

    def test_a_FALSE_return_is_a_404_and_not_a_200( self, harness ):
        """
        🔴 `False` IS NOT AN EXCEPTION. Nothing raises when the row is absent, so the
        handler has to notice. A 200 here tells the browser the playback was recorded
        when nothing was written, and it never retries.
        """
        harness.queue.strict().returns( "mark_played", False )
        r = harness.client.post( self._URL )
        assert r.status_code == 404
        assert _NID in r.json()[ "detail" ]

    def test_the_404_is_not_swallowed_into_a_500( self, harness ):
        """
        The 404 is raised INSIDE the try, so only `except HTTPException: raise` keeps
        it a 404. Deleting that clause converts every miss into a server error — and
        a client reads the two oppositely.
        """
        harness.queue.strict().returns( "mark_played", False )
        assert harness.client.post( self._URL ).status_code != 500

    def test_the_path_id_is_what_gets_marked( self, harness ):
        harness.queue.strict().returns( "mark_played", True )
        harness.client.post( self._URL )
        assert harness.queue.call_to( "mark_played" ).first == _NID

    def test_a_queue_fault_is_a_500( self, harness ):
        harness.queue.strict().raises( "mark_played", RuntimeError( "boom" ) )
        assert harness.client.post( self._URL ).status_code == 500


# ═══════════════════════════════════════════════════════════════════════════════
# DELETE /api/notifications/{notification_id}
# ═══════════════════════════════════════════════════════════════════════════════

class TestDeletingOne:

    _URL = f"/api/notifications/{_NID}"

    def test_a_true_return_is_a_200( self, harness ):
        harness.queue.strict().returns( "delete_by_id_hash", True )
        r = harness.client.delete( self._URL )
        assert_no_accidental_500( r )
        assert r.status_code == 200
        assert r.json()[ "notification_id" ] == _NID

    def test_a_FALSE_return_is_a_404( self, harness ):
        harness.queue.strict().returns( "delete_by_id_hash", False )
        r = harness.client.delete( self._URL )
        assert r.status_code == 404
        assert _NID in r.json()[ "detail" ]

    def test_the_delete_is_keyed_by_the_id_HASH( self, harness ):
        """
        The queue is keyed by id_hash, not by row id. Naming the method is the
        assertion: a handler reaching for a plain `delete` would remove a different
        row, or none, and still return a perfectly ordinary 200.
        """
        harness.queue.strict().returns( "delete_by_id_hash", True )
        harness.client.delete( self._URL )
        harness.queue.assert_only_called( "delete_by_id_hash" )
        assert harness.queue.call_to( "delete_by_id_hash" ).first == _NID

    def test_a_queue_fault_is_a_500( self, harness ):
        harness.queue.strict().raises( "delete_by_id_hash", RuntimeError( "boom" ) )
        assert harness.client.delete( self._URL ).status_code == 500


# ═══════════════════════════════════════════════════════════════════════════════
# DELETE /api/notifications/bulk/{user_email}  — the Clear All button
# ═══════════════════════════════════════════════════════════════════════════════

class TestClearAll:

    _URL = f"/api/notifications/bulk/{_EMAIL}"

    @pytest.fixture( autouse=True )
    def _user_lookup( self, monkeypatch ):
        """
        `get_user_by_email` is imported INSIDE the handler, so it must be patched on
        its own module rather than on the router's namespace — patching the router
        would leave the real lookup running and the test would hit a database.
        """
        import cosa.rest.user_service as user_service
        self.found = { "id": a_uuid( "clear-all-user" ), "uid": "UID-VALUE" }
        self.lookup_calls = []

        def _fake( email ):
            self.lookup_calls.append( email )
            return self.found

        monkeypatch.setattr( user_service, "get_user_by_email", _fake )

    def test_it_deletes_and_reports_the_count( self, harness ):
        harness.repo.returns( "bulk_delete_by_user", 7 )
        r = harness.client.delete( self._URL )
        assert_no_accidental_500( r )
        body = r.json()
        assert body[ "status" ]        == "success"
        assert body[ "deleted_count" ] == 7
        assert body[ "user_email" ]    == _EMAIL

    def test_the_delete_is_scoped_to_the_looked_up_user_not_the_email_alone( self, harness ):
        """
        Both the email AND the resolved uuid go down to the repo. The uuid is the one
        that actually scopes the delete, so asserting only the email would pass while
        a wrong (or missing) recipient_id cleared somebody else's rows.
        """
        harness.repo.returns( "bulk_delete_by_user", 0 )
        harness.client.delete( self._URL )
        call = harness.repo.call_to( "bulk_delete_by_user" )
        assert call.kwargs[ "user_email" ]   == _EMAIL
        assert call.kwargs[ "recipient_id" ] == uuid.UUID( a_uuid( "clear-all-user" ) )
        assert self.lookup_calls == [ _EMAIL ]

    def test_no_hours_filter_forwards_none_meaning_all_time( self, harness ):
        harness.repo.returns( "bulk_delete_by_user", 0 )
        harness.client.delete( self._URL )
        assert harness.repo.call_to( "bulk_delete_by_user" ).kwargs[ "hours" ] is None

    def test_an_hours_filter_is_forwarded( self, harness ):
        harness.repo.returns( "bulk_delete_by_user", 0 )
        harness.client.delete( f"{self._URL}?hours=6" )
        assert harness.repo.call_to( "bulk_delete_by_user" ).kwargs[ "hours" ] == 6

    def test_zero_hours_is_a_400_and_deletes_nothing( self, harness ):
        """
        🔴 THE DANGEROUS INPUT IS `0`, NOT A NEGATIVE ONE. `hours=0` is falsy, so a
        handler guarding with `if not hours` would read it as "no filter" and delete
        ALL TIME instead of refusing. The guard is `<= 0`, and this pins it.
        """
        r = harness.client.delete( f"{self._URL}?hours=0" )
        assert r.status_code == 400
        assert harness.repo.calls == []

    def test_a_negative_hours_is_also_a_400( self, harness ):
        r = harness.client.delete( f"{self._URL}?hours=-1" )
        assert r.status_code == 400

    def test_an_unknown_user_is_a_404_and_deletes_nothing( self, harness ):
        self.found = None
        r = harness.client.delete( self._URL )
        assert r.status_code == 404
        assert _EMAIL in r.json()[ "detail" ]
        assert harness.repo.calls == []

    def test_not_mine_forwards_the_users_own_job_ids_as_an_exclusion( self, harness ):
        """
        The "not mine" filter is an EXCLUSION list, so the ids that travel are the
        user's OWN jobs — the rows to spare. A handler forwarding them as an inclusion
        would delete exactly the set the button promises to keep.
        """
        import cosa.rest.queue_extensions as qx

        class _Tracker:
            def get_jobs_for_user( self, uid ):
                assert uid == "UID-VALUE"
                return [ "JOB-A", "JOB-B" ]

        original = qx.user_job_tracker
        qx.user_job_tracker = _Tracker()
        try:
            harness.repo.returns( "bulk_delete_by_user", 1 )
            harness.client.delete( f"{self._URL}?exclude_own_jobs=true" )
        finally:
            qx.user_job_tracker = original
        call = harness.repo.call_to( "bulk_delete_by_user" )
        assert call.kwargs[ "exclude_job_ids" ] == [ "JOB-A", "JOB-B" ]

    def test_without_the_not_mine_filter_the_exclusion_is_none_not_empty( self, harness ):
        """
        `None` and `[]` are different instructions to the repo: "no exclusion" versus
        "exclude nothing from this empty list". They happen to behave alike today,
        which is exactly why the distinction erodes silently.
        """
        harness.repo.returns( "bulk_delete_by_user", 0 )
        harness.client.delete( self._URL )
        assert harness.repo.call_to( "bulk_delete_by_user" ).kwargs[ "exclude_job_ids" ] is None

    def test_the_echoed_filters_describe_the_request_that_ran( self, harness ):
        harness.repo.returns( "bulk_delete_by_user", 0 )
        body = harness.client.delete( f"{self._URL}?hours=3" ).json()
        assert body[ "hours_filter" ]     == 3
        assert body[ "exclude_own_jobs" ] is False

    def test_a_repo_fault_is_a_500( self, harness ):
        harness.repo.raises( "bulk_delete_by_user", RuntimeError( "boom" ) )
        assert harness.client.delete( self._URL ).status_code == 500


# ═══════════════════════════════════════════════════════════════════════════════
# Route ordering — a property of the FILE, not of any one handler
# ═══════════════════════════════════════════════════════════════════════════════

class TestTheCatchAllRouteIsDeclaredLast:

    def test_the_static_routes_are_declared_before_the_user_id_catch_all( self ):
        """
        🔴 `/notifications/{user_id}` WOULD SWALLOW `/notifications/undelivered`.
        FastAPI matches in declaration order, so the static routes work only because
        they are registered first. Nothing in either handler expresses that, and a
        re-ordering during a tidy-up would route the AFK inbox into the queue listing
        — which answers 200 with an empty list rather than failing.
        """
        import cosa.rest.routers.notifications as notif
        paths    = [ r.path for r in notif.router.routes ]
        catchall = paths.index( "/api/notifications/{user_id}" )
        for static in ( "/api/notifications/undelivered",
                        "/api/notifications/answers-owed",
                        "/api/notifications/undelivered/dismiss",
                        "/api/notifications/response/{notification_id}" ):
            assert paths.index( static ) < catchall, (
                f"{static} is declared AFTER the {{user_id}} catch-all and will never "
                f"be reached" )
