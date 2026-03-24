"""
Integration Tests for Job History API

Tests the /api/job-history endpoints added by CJ Flow Persistence Phase 5.
Validates authentication, authorization, pagination, and filtering against live server.
"""

import pytest
import requests

from tests.integration.conftest import get_auth_header


# Test server configuration
BASE_URL = "http://localhost:7999"


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
            assert job[ "status" ] == "completed", f"Expected 'completed', got '{job[ 'status' ]}'"

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
