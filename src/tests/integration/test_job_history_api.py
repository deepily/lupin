"""
Integration Tests for Job History API

Tests the /api/job-history endpoints added by CJ Flow Persistence Phases 5-6.
Validates authentication, authorization, pagination, filtering, delete, and retry
against live server.

Phase 6 additions (Session 372): Data-driven tests with seeded job_history rows.
"""

import os

import pytest
import requests
from datetime import datetime, timedelta, timezone

from cosa.rest.job_state import JobState
from tests.integration.conftest import get_auth_header


# Test server configuration
BASE_URL = os.environ.get( "LUPIN_TEST_BASE_URL", "http://localhost:8000" )


class TestJobHistoryApi:
    """Integration tests for GET /api/job-history endpoint."""

    def test_unauthenticated_returns_401( self ):
        """Request without auth token returns 401."""
        response = requests.get( f"{BASE_URL}/api/job-history" )
        assert response.status_code == 401, f"Expected 401, got {response.status_code}"

    def test_returns_paginated_results( self, create_test_user ):
        """Authenticated user gets paginated response structure."""
        headers = get_auth_header( create_test_user[ "access_token" ] )

        response = requests.get( f"{BASE_URL}/api/job-history", headers=headers )

        assert response.status_code == 200
        data = response.json()
        assert "jobs" in data, "Response missing 'jobs' key"
        assert "total" in data, "Response missing 'total' key"
        assert "limit" in data, "Response missing 'limit' key"
        assert "offset" in data, "Response missing 'offset' key"
        assert "filtered_by" in data, "Response missing 'filtered_by' key"
        assert isinstance( data[ "jobs" ], list )
        assert isinstance( data[ "total" ], int )

    def test_filters_by_status( self, create_test_user ):
        """Status filter parameter is accepted and returns valid response."""
        headers = get_auth_header( create_test_user[ "access_token" ] )

        response = requests.get(
            f"{BASE_URL}/api/job-history?status=completed",
            headers=headers
        )

        assert response.status_code == 200
        data = response.json()
        # All returned jobs should have status=completed (if any exist)
        for job in data[ "jobs" ]:
            assert job[ "status" ] == JobState.COMPLETED.value, f"Expected '{JobState.COMPLETED.value}', got '{job[ 'status' ]}'"

    def test_filters_by_job_type( self, create_test_user ):
        """Job type filter parameter is accepted and returns valid response."""
        headers = get_auth_header( create_test_user[ "access_token" ] )

        response = requests.get(
            f"{BASE_URL}/api/job-history?job_type=deep_research",
            headers=headers
        )

        assert response.status_code == 200
        data = response.json()
        for job in data[ "jobs" ]:
            assert job[ "job_type" ] == "deep_research", f"Expected 'deep_research', got '{job[ 'job_type' ]}'"

    def test_respects_limit_and_offset( self, create_test_user ):
        """Pagination parameters limit and offset are respected."""
        headers = get_auth_header( create_test_user[ "access_token" ] )

        response = requests.get(
            f"{BASE_URL}/api/job-history?limit=5&offset=0",
            headers=headers
        )

        assert response.status_code == 200
        data = response.json()
        assert data[ "limit" ] == 5
        assert data[ "offset" ] == 0
        assert len( data[ "jobs" ] ) <= 5

    def test_regular_user_sees_own_only( self, create_test_user ):
        """Regular user's filtered_by matches their own user ID."""
        headers = get_auth_header( create_test_user[ "access_token" ] )

        response = requests.get( f"{BASE_URL}/api/job-history", headers=headers )

        assert response.status_code == 200
        data = response.json()
        # Regular user should see filtered_by set to their uid (not "all")
        assert data[ "filtered_by" ] != "all", "Regular user should not see 'all' filter"

    def test_admin_sees_all( self, create_test_admin ):
        """Admin user sees all jobs (filtered_by='all')."""
        headers = get_auth_header( create_test_admin[ "access_token" ] )

        response = requests.get( f"{BASE_URL}/api/job-history", headers=headers )

        assert response.status_code == 200
        data = response.json()
        assert data[ "filtered_by" ] == "all", f"Admin should see 'all', got '{data[ 'filtered_by' ]}'"


class TestJobHistoryDetailApi:
    """Integration tests for GET /api/job-history/{job_id} endpoint."""

    def test_detail_not_found_returns_404( self, create_test_user ):
        """Nonexistent job ID returns 404."""
        headers = get_auth_header( create_test_user[ "access_token" ] )

        response = requests.get(
            f"{BASE_URL}/api/job-history/nonexistent-job-id",
            headers=headers
        )

        assert response.status_code == 404

    def test_detail_unauthenticated_returns_401( self ):
        """Detail endpoint without auth token returns 401."""
        response = requests.get( f"{BASE_URL}/api/job-history/some-job-id" )
        assert response.status_code == 401


class TestJobHistoryDeleteApi:
    """Integration tests for DELETE /api/job-history/{job_id} endpoint (Phase 6)."""

    def test_delete_unauthenticated_returns_401( self ):
        """DELETE without auth token returns 401."""
        response = requests.delete( f"{BASE_URL}/api/job-history/some-job-id" )
        assert response.status_code == 401

    def test_delete_nonexistent_returns_404( self, create_test_user ):
        """DELETE with nonexistent job ID returns 404."""
        headers = get_auth_header( create_test_user[ "access_token" ] )

        response = requests.delete(
            f"{BASE_URL}/api/job-history/nonexistent-job-id-xyz",
            headers=headers
        )

        assert response.status_code == 404


class TestJobHistoryRetryApi:
    """POST /api/job-history/{job_id}/retry is a TOMBSTONE — 410 Gone, to everybody.

    Retired 2026-08-21 (bd842858) under Rick's one-entry-point ruling. It was a queue
    door wearing a job-history URL: the server read `question_text` off the stored row
    and called push_job with it. The client holds that text already, so the client
    re-asks at /api/v2/ask and this route answers 410 naming that door.

    THE CONTRACT CHANGED SHAPE, NOT JUST STATUS. The refusal takes no auth dependency
    and reads no row, so the four answers this class used to distinguish — 401 for no
    token, 404 for an unknown id, 403 for someone else's job, 400 for a job in the
    wrong status — are all 410 now. That is deliberate: a stale client must learn the
    same thing whether or not it holds a token, and a 401 teaches nobody anything.
    Each case is kept as its own test rather than collapsed into one, so a stub that
    quietly regains an auth or ownership check fails HERE, by name.
    """

    def _assert_tombstone( self, response ):
        """Every refusal from this door: 410, names /api/v2/ask, carries the date."""
        assert response.status_code == 410, \
            f"Expected 410 Gone, got {response.status_code}: {response.text[ :300 ]}"
        detail = response.json()[ "detail" ]
        assert "/api/v2/ask" in detail, f"Refusal does not name the replacement: {detail}"
        assert "2026-12-31" in detail, f"Refusal does not carry the removal date: {detail}"

    def test_retry_unauthenticated_returns_410( self ):
        """No token is not a credentials problem here — the door is gone for everyone."""
        response = requests.post( f"{BASE_URL}/api/job-history/some-job-id/retry" )
        self._assert_tombstone( response )

    def test_retry_nonexistent_returns_410( self, create_test_user ):
        """The tombstone never reads a row, so an unknown id is 410, not 404."""
        headers = get_auth_header( create_test_user[ "access_token" ] )

        response = requests.post(
            f"{BASE_URL}/api/job-history/nonexistent-job-id-xyz/retry",
            headers=headers,
            json={ "websocket_id": "test-ws-id" }
        )

        self._assert_tombstone( response )


class TestJobHistoryFiltersApi:
    """Integration tests for new days and exclude_ids filters (Phase 6)."""

    def test_days_filter_accepted( self, create_test_user ):
        """days=7 parameter is accepted and returns valid response."""
        headers = get_auth_header( create_test_user[ "access_token" ] )

        response = requests.get(
            f"{BASE_URL}/api/job-history?days=7",
            headers=headers
        )

        assert response.status_code == 200
        data = response.json()
        assert "jobs" in data
        assert "total" in data

    def test_exclude_ids_filter_accepted( self, create_test_user ):
        """exclude_ids parameter is accepted and returns valid response."""
        headers = get_auth_header( create_test_user[ "access_token" ] )

        response = requests.get(
            f"{BASE_URL}/api/job-history?exclude_ids=fake-id-1,fake-id-2",
            headers=headers
        )

        assert response.status_code == 200
        data = response.json()
        assert "jobs" in data
        assert "total" in data

    def test_combined_filters( self, create_test_user ):
        """Multiple filters (days + status + exclude_ids) work together."""
        headers = get_auth_header( create_test_user[ "access_token" ] )

        response = requests.get(
            f"{BASE_URL}/api/job-history?days=30&status=completed&exclude_ids=id-a,id-b&limit=10",
            headers=headers
        )

        assert response.status_code == 200
        data = response.json()
        assert data[ "limit" ] == 10
        for job in data[ "jobs" ]:
            assert job[ "status" ] == JobState.COMPLETED.value


# ===========================================================================
# Data-Driven Tests (Session 372) — require seeded job_history rows
# ===========================================================================

class TestJobHistoryWithData:
    """Integration tests for GET /api/job-history with seeded data."""

    def test_returns_seeded_jobs( self, seeded_job_history ):
        """Seeded job_history rows are returned by the API."""
        user    = seeded_job_history[ "user" ]
        headers = get_auth_header( user[ "access_token" ] )

        response = requests.get( f"{BASE_URL}/api/job-history", headers=headers )

        assert response.status_code == 200
        data = response.json()
        assert data[ "total" ] == 5, f"Expected 5 seeded jobs, got {data[ 'total' ]}"
        assert len( data[ "jobs" ] ) == 5

        # Verify fields are populated (not just structural keys)
        job = data[ "jobs" ][ 0 ]
        assert job[ "id_hash" ] is not None
        assert job[ "job_type" ] is not None
        assert job[ "status" ] is not None
        assert job[ "question_text" ] is not None

    def test_filters_by_status_with_data( self, seeded_job_history ):
        """Status filter returns only matching jobs from seeded data."""
        user    = seeded_job_history[ "user" ]
        headers = get_auth_header( user[ "access_token" ] )

        response = requests.get(
            f"{BASE_URL}/api/job-history?status=completed",
            headers=headers
        )

        assert response.status_code == 200
        data = response.json()
        # Standard set has 2 completed jobs
        assert data[ "total" ] == 2, f"Expected 2 completed, got {data[ 'total' ]}"
        for job in data[ "jobs" ]:
            assert job[ "status" ] == JobState.COMPLETED.value

    def test_filters_by_job_type_with_data( self, seeded_job_history ):
        """Job type filter returns only matching jobs from seeded data."""
        user    = seeded_job_history[ "user" ]
        headers = get_auth_header( user[ "access_token" ] )

        response = requests.get(
            f"{BASE_URL}/api/job-history?job_type=podcast",
            headers=headers
        )

        assert response.status_code == 200
        data = response.json()
        # Standard set has 1 podcast job
        assert data[ "total" ] == 1, f"Expected 1 podcast, got {data[ 'total' ]}"
        assert data[ "jobs" ][ 0 ][ "job_type" ] == "podcast"

    def test_days_filter_excludes_old_jobs( self, create_test_user ):
        """days=7 filter excludes jobs older than 7 days."""
        from tests.helpers.job_history_seed import seed_time_window_jobs

        user    = create_test_user
        records = seed_time_window_jobs( user[ "user_id" ], user[ "email" ] )
        headers = get_auth_header( user[ "access_token" ] )

        response = requests.get(
            f"{BASE_URL}/api/job-history?days=7",
            headers=headers
        )

        assert response.status_code == 200
        data = response.json()
        # Only the 3-day-old job should pass the 7-day window
        assert data[ "total" ] == 1, f"Expected 1 job within 7 days, got {data[ 'total' ]}"

    def test_exclude_ids_removes_specified( self, seeded_job_history ):
        """exclude_ids parameter removes specified jobs from results."""
        user    = seeded_job_history[ "user" ]
        records = seeded_job_history[ "records" ]
        headers = get_auth_header( user[ "access_token" ] )

        # Exclude first 3 jobs
        exclude = ",".join( [ r[ "id_hash" ] for r in records[ :3 ] ] )

        response = requests.get(
            f"{BASE_URL}/api/job-history?exclude_ids={exclude}",
            headers=headers
        )

        assert response.status_code == 200
        data = response.json()
        assert data[ "total" ] == 2, f"Expected 2 after excluding 3, got {data[ 'total' ]}"
        returned_ids = { j[ "id_hash" ] for j in data[ "jobs" ] }
        for excluded_rec in records[ :3 ]:
            assert excluded_rec[ "id_hash" ] not in returned_ids

    def test_pagination_limit_offset( self, seeded_job_history ):
        """Pagination limit and offset return correct slices."""
        user    = seeded_job_history[ "user" ]
        headers = get_auth_header( user[ "access_token" ] )

        # Page 1
        r1 = requests.get(
            f"{BASE_URL}/api/job-history?limit=2&offset=0",
            headers=headers
        )
        d1 = r1.json()
        assert len( d1[ "jobs" ] ) == 2
        assert d1[ "total" ] == 5

        # Page 2
        r2 = requests.get(
            f"{BASE_URL}/api/job-history?limit=2&offset=2",
            headers=headers
        )
        d2 = r2.json()
        assert len( d2[ "jobs" ] ) == 2
        assert d2[ "total" ] == 5

        # Pages should have different jobs
        ids_p1 = { j[ "id_hash" ] for j in d1[ "jobs" ] }
        ids_p2 = { j[ "id_hash" ] for j in d2[ "jobs" ] }
        assert ids_p1.isdisjoint( ids_p2 ), "Page 1 and Page 2 should have different jobs"

    def test_ordered_by_created_at_desc( self, seeded_job_history ):
        """Results are ordered by created_at descending (newest first)."""
        user    = seeded_job_history[ "user" ]
        headers = get_auth_header( user[ "access_token" ] )

        response = requests.get( f"{BASE_URL}/api/job-history", headers=headers )

        data = response.json()
        jobs = data[ "jobs" ]
        assert len( jobs ) >= 2, "Need at least 2 jobs to verify ordering"

        # Verify descending order
        for i in range( len( jobs ) - 1 ):
            ts_current = jobs[ i ][ "created_at" ]
            ts_next    = jobs[ i + 1 ][ "created_at" ]
            assert ts_current >= ts_next, f"Job {i} ({ts_current}) should be >= Job {i+1} ({ts_next})"


class TestJobHistoryDeleteWithData:
    """Integration tests for DELETE /api/job-history/{job_id} with seeded data."""

    def test_delete_existing_job( self, seeded_job_history ):
        """DELETE removes a seeded job and subsequent GET confirms removal."""
        user    = seeded_job_history[ "user" ]
        records = seeded_job_history[ "records" ]
        headers = get_auth_header( user[ "access_token" ] )
        target  = records[ 0 ][ "id_hash" ]

        # Delete
        del_resp = requests.delete(
            f"{BASE_URL}/api/job-history/{target}",
            headers=headers
        )
        assert del_resp.status_code == 200
        assert del_resp.json()[ "status" ] == "deleted"

        # Confirm gone
        get_resp = requests.get( f"{BASE_URL}/api/job-history", headers=headers )
        data = get_resp.json()
        assert data[ "total" ] == 4, f"Expected 4 after delete, got {data[ 'total' ]}"
        returned_ids = { j[ "id_hash" ] for j in data[ "jobs" ] }
        assert target not in returned_ids

    def test_delete_other_users_job_403( self, create_test_user, create_test_admin ):
        """Regular user cannot delete another user's job (403)."""
        from tests.helpers.job_history_seed import seed_job_history_records

        # Seed a job owned by admin
        admin_user_id = create_test_admin[ "user_id" ]
        records = seed_job_history_records(
            user_id    = admin_user_id,
            user_email = create_test_admin[ "email" ],
            records    = [ { "id_suffix": "other-001", "status": JobState.COMPLETED.value } ]
        )

        # Regular user tries to delete it
        headers = get_auth_header( create_test_user[ "access_token" ] )
        response = requests.delete(
            f"{BASE_URL}/api/job-history/{records[ 0 ][ 'id_hash' ]}",
            headers=headers
        )
        assert response.status_code == 403

    def test_admin_can_delete_any_job( self, create_test_user, create_test_admin ):
        """Admin can delete any user's job."""
        from tests.helpers.job_history_seed import seed_job_history_records

        # Seed a job owned by regular user
        records = seed_job_history_records(
            user_id    = create_test_user[ "user_id" ],
            user_email = create_test_user[ "email" ],
            records    = [ { "id_suffix": "admin-del-001", "status": JobState.COMPLETED.value } ]
        )

        # Admin deletes it
        headers = get_auth_header( create_test_admin[ "access_token" ] )
        response = requests.delete(
            f"{BASE_URL}/api/job-history/{records[ 0 ][ 'id_hash' ]}",
            headers=headers
        )
        assert response.status_code == 200
        assert response.json()[ "status" ] == "deleted"


class TestJobHistoryRetryWithData:
    """The tombstone answers 410 for a REAL row too, whatever its status or owner.

    The class above proves the door refuses when there is nothing to find. This one
    proves it refuses when there IS — a failed row the caller owns, an interrupted
    one, a completed one, and one belonging to somebody else. All four used to give
    four different answers; a row-reading handler restored behind this route would
    show up here as one of those answers coming back.

    What was lost rather than moved, said plainly so nobody hunts for it: the
    wrong-status 400 check (nothing performs it now — the client re-asks whatever it
    wants) and the other-user 403, which dissolves rather than moves. You ask as
    yourself at /api/v2/ask, so there is no other-user retry left to authorize.
    """

    def _assert_tombstone( self, response ):
        """Every refusal from this door: 410, names /api/v2/ask, carries the date."""
        assert response.status_code == 410, \
            f"Expected 410 Gone, got {response.status_code}: {response.text[ :300 ]}"
        detail = response.json()[ "detail" ]
        assert "/api/v2/ask" in detail, f"Refusal does not name the replacement: {detail}"
        assert "2026-12-31" in detail, f"Refusal does not carry the removal date: {detail}"

    def test_retry_failed_job_returns_410( self, seeded_job_history ):
        """A failed row the caller owns — the case retry existed for — is 410."""
        user    = seeded_job_history[ "user" ]
        records = seeded_job_history[ "records" ]
        headers = get_auth_header( user[ "access_token" ] )

        # Find the failed job (std-003)
        failed = next( r for r in records if r[ "status" ] == JobState.FAILED.value )

        response = requests.post(
            f"{BASE_URL}/api/job-history/{failed[ 'id_hash' ]}/retry",
            headers=headers,
            json={ "websocket_id": "test-ws-retry-001" }
        )
        self._assert_tombstone( response )

    def test_retry_interrupted_job_returns_410( self, seeded_job_history ):
        """The other status the retry button used to appear for is 410 as well."""
        user    = seeded_job_history[ "user" ]
        records = seeded_job_history[ "records" ]
        headers = get_auth_header( user[ "access_token" ] )

        interrupted = next( r for r in records if r[ "status" ] == JobState.INTERRUPTED.value )

        response = requests.post(
            f"{BASE_URL}/api/job-history/{interrupted[ 'id_hash' ]}/retry",
            headers=headers,
            json={ "websocket_id": "test-ws-retry-002" }
        )
        self._assert_tombstone( response )

    def test_retry_completed_job_returns_410_not_400( self, seeded_job_history ):
        """The wrong-status 400 is GONE — no handler reads the row to object."""
        user    = seeded_job_history[ "user" ]
        records = seeded_job_history[ "records" ]
        headers = get_auth_header( user[ "access_token" ] )

        completed = next( r for r in records if r[ "status" ] == JobState.COMPLETED.value )

        response = requests.post(
            f"{BASE_URL}/api/job-history/{completed[ 'id_hash' ]}/retry",
            headers=headers,
            json={ "websocket_id": "test-ws-retry-003" }
        )
        self._assert_tombstone( response )

    def test_retry_other_users_job_returns_410_not_403( self, create_test_user, create_test_admin ):
        """The ownership 403 dissolved with the feature — you ask as yourself now."""
        from tests.helpers.job_history_seed import seed_job_history_records

        # Seed a failed job owned by admin
        records = seed_job_history_records(
            user_id    = create_test_admin[ "user_id" ],
            user_email = create_test_admin[ "email" ],
            records    = [ { "id_suffix": "retry-other-001", "status": JobState.FAILED.value, "error": "test error" } ]
        )

        # Regular user tries to retry
        headers = get_auth_header( create_test_user[ "access_token" ] )
        response = requests.post(
            f"{BASE_URL}/api/job-history/{records[ 0 ][ 'id_hash' ]}/retry",
            headers=headers,
            json={ "websocket_id": "test-ws-retry-004" }
        )
        self._assert_tombstone( response )


class TestJobHistoryUserIsolation:
    """Integration tests for user-level data isolation in job history."""

    def test_regular_user_cannot_see_others( self, create_test_user, create_test_admin ):
        """Regular user sees only their own jobs, not other users' jobs."""
        from tests.helpers.job_history_seed import seed_job_history_records

        # Seed jobs for admin user
        seed_job_history_records(
            user_id    = create_test_admin[ "user_id" ],
            user_email = create_test_admin[ "email" ],
            records    = [
                { "id_suffix": "iso-admin-001", "status": JobState.COMPLETED.value },
                { "id_suffix": "iso-admin-002", "status": JobState.COMPLETED.value },
            ]
        )

        # Regular user queries — should see 0 jobs
        headers = get_auth_header( create_test_user[ "access_token" ] )
        response = requests.get( f"{BASE_URL}/api/job-history", headers=headers )

        data = response.json()
        assert data[ "total" ] == 0, f"Regular user should see 0 jobs, got {data[ 'total' ]}"
        assert data[ "filtered_by" ] != "all"

    def test_admin_sees_all_users_jobs( self, create_test_user, create_test_admin ):
        """Admin user sees all jobs regardless of ownership."""
        from tests.helpers.job_history_seed import seed_job_history_records

        # Seed jobs for regular user
        seed_job_history_records(
            user_id    = create_test_user[ "user_id" ],
            user_email = create_test_user[ "email" ],
            records    = [
                { "id_suffix": "iso-user-001", "status": JobState.COMPLETED.value },
                { "id_suffix": "iso-user-002", "status": JobState.COMPLETED.value },
            ]
        )

        # Admin queries — should see all
        headers = get_auth_header( create_test_admin[ "access_token" ] )
        response = requests.get( f"{BASE_URL}/api/job-history", headers=headers )

        data = response.json()
        assert data[ "total" ] >= 2, f"Admin should see at least 2 jobs, got {data[ 'total' ]}"
        assert data[ "filtered_by" ] == "all"
