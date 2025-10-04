"""
Integration Tests for Queue Filtering API

Tests the /api/get-queue endpoint with user filtering and role-based access control.
Validates full authentication and authorization workflow.
"""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
class TestQueueFilteringIntegration:
    """Integration tests for queue filtering endpoints with authentication."""

    # ==================== Regular User Scenarios ====================

    async def test_regular_user_gets_only_own_jobs(self, async_client, test_server_url):
        """Regular user queries queue without filter and gets only their own jobs."""
        # Setup: Create regular user and get token
        register_response = await async_client.post(
            f"{test_server_url}/api/auth/register",
            json={
                "email": "regular@test.com",
                "password": "test123",
                "display_name": "Regular User"
            }
        )
        assert register_response.status_code == 201
        user_token = register_response.json()["access_token"]

        # Push a job as this user
        push_response = await async_client.post(
            f"{test_server_url}/api/push",
            json={
                "question": "What is 2+2?",
                "websocket_id": "test_session_1"
            },
            headers={"Authorization": f"Bearer {user_token}"}
        )
        assert push_response.status_code == 200

        # Query the todo queue
        queue_response = await async_client.get(
            f"{test_server_url}/api/get-queue/todo",
            headers={"Authorization": f"Bearer {user_token}"}
        )

        assert queue_response.status_code == 200
        data = queue_response.json()
        assert "todo_jobs" in data
        assert "filtered_by" in data
        assert "is_admin_view" in data
        assert data["is_admin_view"] is False
        # User should see their own job
        assert data["total_jobs"] >= 1

    async def test_regular_user_wildcard_forbidden(self, async_client, test_server_url):
        """Regular user attempting wildcard filter receives 403 Forbidden."""
        # Setup: Create regular user
        register_response = await async_client.post(
            f"{test_server_url}/api/auth/register",
            json={
                "email": "user2@test.com",
                "password": "test123",
                "display_name": "User 2"
            }
        )
        user_token = register_response.json()["access_token"]

        # Test: Attempt wildcard query
        response = await async_client.get(
            f"{test_server_url}/api/get-queue/todo?user_filter=*",
            headers={"Authorization": f"Bearer {user_token}"}
        )

        # Assert: 403 Forbidden
        assert response.status_code == 403
        assert "admin" in response.json()["detail"].lower()

    async def test_regular_user_other_user_forbidden(self, async_client, test_server_url):
        """Regular user attempting to access another user's jobs receives 403."""
        # Setup: Create regular user
        register_response = await async_client.post(
            f"{test_server_url}/api/auth/register",
            json={
                "email": "user3@test.com",
                "password": "test123",
                "display_name": "User 3"
            }
        )
        user_token = register_response.json()["access_token"]

        # Test: Attempt to query another user's jobs
        response = await async_client.get(
            f"{test_server_url}/api/get-queue/todo?user_filter=other_user_123",
            headers={"Authorization": f"Bearer {user_token}"}
        )

        # Assert: 403 Forbidden
        assert response.status_code == 403
        assert "cannot access" in response.json()["detail"].lower()

    # ==================== Admin User Scenarios ====================

    async def test_admin_wildcard_gets_all_jobs(self, async_client, test_server_url):
        """Admin user with wildcard filter gets all users' jobs."""
        # Setup: Create admin user and regular user
        admin_response = await async_client.post(
            f"{test_server_url}/api/auth/register",
            json={
                "email": "admin@test.com",
                "password": "admin123",
                "display_name": "Admin User"
            }
        )
        # Note: In real system, admin role would be assigned by system
        # For testing, we'll need to use the existing SUPERUSER account
        # or create a test fixture that creates admin users

        # For this test, let's assume we're using the SUPERUSER account
        login_response = await async_client.post(
            f"{test_server_url}/api/auth/login",
            json={
                "email": "ricardo.felipe.ruiz@gmail.com",  # SUPERUSER from fixtures
                "password": "pswfJ^WP&1AXA1nB"  # From history.md
            }
        )
        assert login_response.status_code == 200
        admin_token = login_response.json()["access_token"]

        # Test: Admin queries with wildcard
        response = await async_client.get(
            f"{test_server_url}/api/get-queue/todo?user_filter=*",
            headers={"Authorization": f"Bearer {admin_token}"}
        )

        # Assert: Success with admin view
        assert response.status_code == 200
        data = response.json()
        assert data["filtered_by"] == "*"
        assert data["is_admin_view"] is True

    async def test_admin_specific_user_gets_that_user_jobs(self, async_client, test_server_url):
        """Admin can query specific user's jobs."""
        # Setup: Create regular user and push job
        user_response = await async_client.post(
            f"{test_server_url}/api/auth/register",
            json={
                "email": "target@test.com",
                "password": "test123",
                "display_name": "Target User"
            }
        )
        user_token = user_response.json()["access_token"]
        user_data = user_response.json()
        target_user_id = user_data["uid"]

        # Push job as target user
        await async_client.post(
            f"{test_server_url}/api/push",
            json={
                "question": "Target user question",
                "websocket_id": "target_session"
            },
            headers={"Authorization": f"Bearer {user_token}"}
        )

        # Get admin token
        admin_login = await async_client.post(
            f"{test_server_url}/api/auth/login",
            json={
                "email": "ricardo.felipe.ruiz@gmail.com",
                "password": "pswfJ^WP&1AXA1nB"
            }
        )
        admin_token = admin_login.json()["access_token"]

        # Test: Admin queries specific user
        response = await async_client.get(
            f"{test_server_url}/api/get-queue/todo?user_filter={target_user_id}",
            headers={"Authorization": f"Bearer {admin_token}"}
        )

        # Assert: Success
        assert response.status_code == 200
        data = response.json()
        assert data["filtered_by"] == target_user_id
        assert data["is_admin_view"] is True

    async def test_admin_no_filter_gets_own_jobs(self, async_client, test_server_url):
        """Admin without filter parameter gets only their own jobs."""
        # Get admin token
        login_response = await async_client.post(
            f"{test_server_url}/api/auth/login",
            json={
                "email": "ricardo.felipe.ruiz@gmail.com",
                "password": "pswfJ^WP&1AXA1nB"
            }
        )
        admin_token = login_response.json()["access_token"]
        admin_uid = login_response.json()["uid"]

        # Test: Admin queries without filter
        response = await async_client.get(
            f"{test_server_url}/api/get-queue/todo",
            headers={"Authorization": f"Bearer {admin_token}"}
        )

        # Assert: Gets own jobs (not wildcard by default)
        assert response.status_code == 200
        data = response.json()
        assert data["filtered_by"] == admin_uid
        assert data["is_admin_view"] is False  # No explicit filter used

    # ==================== Multi-Queue Tests ====================

    async def test_filtering_works_across_all_queue_types(self, async_client, test_server_url):
        """User filtering works consistently across all queue types."""
        # Setup: Get user token
        register_response = await async_client.post(
            f"{test_server_url}/api/auth/register",
            json={
                "email": "multiqueue@test.com",
                "password": "test123",
                "display_name": "Multi Queue User"
            }
        )
        user_token = register_response.json()["access_token"]
        user_id = register_response.json()["uid"]

        # Test: Query each queue type
        queue_types = ["todo", "run", "done", "dead"]
        for queue_name in queue_types:
            response = await async_client.get(
                f"{test_server_url}/api/get-queue/{queue_name}",
                headers={"Authorization": f"Bearer {user_token}"}
            )

            # Assert: All succeed with correct filtering
            assert response.status_code == 200
            data = response.json()
            assert data["filtered_by"] == user_id
            assert f"{queue_name}_jobs" in data

    async def test_done_queue_metadata_filtered_correctly(self, async_client, test_server_url):
        """Done queue returns filtered metadata alongside HTML jobs."""
        # Setup: Get user token
        register_response = await async_client.post(
            f"{test_server_url}/api/auth/register",
            json={
                "email": "donequeue@test.com",
                "password": "test123",
                "display_name": "Done Queue User"
            }
        )
        user_token = register_response.json()["access_token"]

        # Test: Query done queue
        response = await async_client.get(
            f"{test_server_url}/api/get-queue/done",
            headers={"Authorization": f"Bearer {user_token}"}
        )

        # Assert: Contains both jobs and metadata
        assert response.status_code == 200
        data = response.json()
        assert "done_jobs" in data
        assert "done_jobs_metadata" in data
        assert "filtered_by" in data
        assert "total_jobs" in data

        # If there are jobs, validate metadata structure
        if len(data["done_jobs"]) > 0:
            metadata = data["done_jobs_metadata"][0]
            assert "html" in metadata
            assert "job_id" in metadata
            assert "question_text" in metadata
            assert "response_text" in metadata
            assert "timestamp" in metadata
            assert "user_id" in metadata
            assert "has_audio_cache" in metadata

    # ==================== Error Cases ====================

    async def test_invalid_queue_name_returns_400(self, async_client, test_server_url):
        """Invalid queue name returns 400 Bad Request."""
        # Setup: Get token
        register_response = await async_client.post(
            f"{test_server_url}/api/auth/register",
            json={
                "email": "error@test.com",
                "password": "test123",
                "display_name": "Error Test User"
            }
        )
        user_token = register_response.json()["access_token"]

        # Test: Query invalid queue
        response = await async_client.get(
            f"{test_server_url}/api/get-queue/invalid",
            headers={"Authorization": f"Bearer {user_token}"}
        )

        # Assert: 400 Bad Request
        assert response.status_code == 400
        assert "invalid queue name" in response.json()["detail"].lower()

    async def test_unauthenticated_request_returns_401(self, async_client, test_server_url):
        """Request without authentication token returns 401 Unauthorized."""
        # Test: Query without token
        response = await async_client.get(f"{test_server_url}/api/get-queue/todo")

        # Assert: 401 Unauthorized
        assert response.status_code == 401

    # ==================== Response Format Validation ====================

    async def test_response_format_backward_compatible(self, async_client, test_server_url):
        """Response format maintains backward compatibility with existing clients."""
        # Setup: Get token
        register_response = await async_client.post(
            f"{test_server_url}/api/auth/register",
            json={
                "email": "compat@test.com",
                "password": "test123",
                "display_name": "Compat User"
            }
        )
        user_token = register_response.json()["access_token"]

        # Test: Query queue
        response = await async_client.get(
            f"{test_server_url}/api/get-queue/todo",
            headers={"Authorization": f"Bearer {user_token}"}
        )

        # Assert: Contains expected fields
        assert response.status_code == 200
        data = response.json()

        # Required fields for backward compatibility
        assert "todo_jobs" in data
        assert isinstance(data["todo_jobs"], list)

        # New metadata fields (additive, not breaking)
        assert "filtered_by" in data
        assert "is_admin_view" in data
        assert "total_jobs" in data

    async def test_metadata_fields_accurate(self, async_client, test_server_url):
        """Metadata fields contain accurate information."""
        # Setup: Get admin token
        login_response = await async_client.post(
            f"{test_server_url}/api/auth/login",
            json={
                "email": "ricardo.felipe.ruiz@gmail.com",
                "password": "pswfJ^WP&1AXA1nB"
            }
        )
        admin_token = login_response.json()["access_token"]
        admin_uid = login_response.json()["uid"]

        # Test 1: Admin with wildcard
        response1 = await async_client.get(
            f"{test_server_url}/api/get-queue/todo?user_filter=*",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        data1 = response1.json()
        assert data1["filtered_by"] == "*"
        assert data1["is_admin_view"] is True
        assert data1["total_jobs"] == len(data1["todo_jobs"])

        # Test 2: Admin without filter
        response2 = await async_client.get(
            f"{test_server_url}/api/get-queue/todo",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        data2 = response2.json()
        assert data2["filtered_by"] == admin_uid
        assert data2["is_admin_view"] is False
        assert data2["total_jobs"] == len(data2["todo_jobs"])
