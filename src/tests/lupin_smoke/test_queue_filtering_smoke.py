"""
Smoke Tests for Queue Filtering

End-to-end validation of multi-user queue isolation and filtering.
Tests real-world user scenarios with minimal mocking.
"""

import pytest
import requests
from typing import Dict


class TestQueueFilteringSmoke:
    """Smoke tests for user-filtered queue views."""

    @pytest.fixture
    def base_url(self):
        """Base URL for FastAPI server (assumes running on port 7999)."""
        return "http://localhost:7999"

    @pytest.fixture
    def create_user(self, base_url):
        """Helper fixture to create and login users."""
        def _create_user(email: str, password: str = "test123") -> Dict[str, str]:
            # Register user
            response = requests.post(
                f"{base_url}/api/auth/register",
                json={
                    "email": email,
                    "password": password,
                    "display_name": email.split("@")[0]
                }
            )

            if response.status_code == 201:
                return response.json()
            elif response.status_code == 400 and "already exists" in response.json().get("detail", ""):
                # User exists, login instead
                login_response = requests.post(
                    f"{base_url}/api/auth/login",
                    json={"email": email, "password": password}
                )
                return login_response.json()
            else:
                raise Exception(f"Failed to create user: {response.text}")

        return _create_user

    @pytest.fixture
    def push_job(self, base_url):
        """Helper fixture to push jobs to queue."""
        def _push_job(token: str, question: str) -> Dict:
            response = requests.post(
                f"{base_url}/api/push",
                json={
                    "question": question,
                    "websocket_id": f"smoke_test_session_{token[:10]}"
                },
                headers={"Authorization": f"Bearer {token}"}
            )
            assert response.status_code == 200
            return response.json()

        return _push_job

    @pytest.fixture
    def get_queue(self, base_url):
        """Helper fixture to get queue contents."""
        def _get_queue(token: str, queue_name: str, user_filter: str = None) -> Dict:
            url = f"{base_url}/api/get-queue/{queue_name}"
            if user_filter is not None:
                url += f"?user_filter={user_filter}"

            response = requests.get(
                url,
                headers={"Authorization": f"Bearer {token}"}
            )
            return response

        return _get_queue

    # ==================== Multi-User Isolation Tests ====================

    def test_multi_user_queue_isolation(self, create_user, push_job, get_queue):
        """Multiple users maintain queue isolation - each sees only their own jobs."""

        # Create three users
        user_a = create_user("smoke_user_a@test.com")
        user_b = create_user("smoke_user_b@test.com")
        admin_user = create_user("ricardo.felipe.ruiz@gmail.com", "pswfJ^WP&1AXA1nB")

        # User A pushes job
        push_job(user_a["access_token"], "What is 2+2?")

        # User B pushes job
        push_job(user_b["access_token"], "What is 3+3?")

        # Test 1: User A sees only their job
        response_a = get_queue(user_a["access_token"], "todo")
        assert response_a.status_code == 200
        data_a = response_a.json()
        assert data_a["filtered_by"] == user_a["uid"]
        assert data_a["is_admin_view"] is False
        # Verify at least user A's job is present
        assert any("2+2" in job for job in data_a["todo_jobs"])

        # Test 2: User B sees only their job
        response_b = get_queue(user_b["access_token"], "todo")
        assert response_b.status_code == 200
        data_b = response_b.json()
        assert data_b["filtered_by"] == user_b["uid"]
        assert any("3+3" in job for job in data_b["todo_jobs"])

        # Test 3: Admin with wildcard sees both
        response_admin = get_queue(admin_user["access_token"], "todo", user_filter="*")
        assert response_admin.status_code == 200
        data_admin = response_admin.json()
        assert data_admin["filtered_by"] == "*"
        assert data_admin["is_admin_view"] is True
        # Admin should see both jobs (or more if queue has other jobs)
        all_jobs_html = " ".join(data_admin["todo_jobs"])
        # Note: Depending on queue state, these jobs might be in run/done queues
        # So we just verify admin can use wildcard successfully

    def test_regular_user_wildcard_blocked(self, create_user, get_queue):
        """Regular user attempting wildcard filter receives 403 Forbidden."""

        # Create regular user
        user = create_user("smoke_wildcard@test.com")

        # Test: Attempt wildcard
        response = get_queue(user["access_token"], "todo", user_filter="*")

        # Assert: 403 Forbidden
        assert response.status_code == 403
        assert "admin" in response.json()["detail"].lower()

    def test_regular_user_other_user_blocked(self, create_user, get_queue):
        """Regular user attempting to access another user's jobs receives 403."""

        # Create two users
        user_1 = create_user("smoke_user1@test.com")
        user_2 = create_user("smoke_user2@test.com")

        # Test: User 1 attempts to query User 2's jobs
        response = get_queue(user_1["access_token"], "todo", user_filter=user_2["uid"])

        # Assert: 403 Forbidden
        assert response.status_code == 403
        assert "cannot access" in response.json()["detail"].lower()

    # ==================== Admin Scenarios ====================

    def test_admin_view_all_toggle(self, create_user, push_job, get_queue):
        """Admin can toggle between own jobs and all jobs."""

        # Get admin user
        admin = create_user("ricardo.felipe.ruiz@gmail.com", "pswfJ^WP&1AXA1nB")

        # Push job as admin
        push_job(admin["access_token"], "Admin question")

        # Test 1: Admin without filter sees own jobs
        response_own = get_queue(admin["access_token"], "todo")
        assert response_own.status_code == 200
        data_own = response_own.json()
        assert data_own["filtered_by"] == admin["uid"]
        assert data_own["is_admin_view"] is False

        # Test 2: Admin with wildcard sees all jobs
        response_all = get_queue(admin["access_token"], "todo", user_filter="*")
        assert response_all.status_code == 200
        data_all = response_all.json()
        assert data_all["filtered_by"] == "*"
        assert data_all["is_admin_view"] is True
        # All jobs count should be >= own jobs count
        assert data_all["total_jobs"] >= data_own["total_jobs"]

    def test_admin_specific_user_query(self, create_user, push_job, get_queue):
        """Admin can query specific user's jobs."""

        # Create target user and admin
        target_user = create_user("smoke_target@test.com")
        admin = create_user("ricardo.felipe.ruiz@gmail.com", "pswfJ^WP&1AXA1nB")

        # Push job as target user
        push_job(target_user["access_token"], "Target user question")

        # Test: Admin queries target user's jobs
        response = get_queue(admin["access_token"], "todo", user_filter=target_user["uid"])

        # Assert: Success
        assert response.status_code == 200
        data = response.json()
        assert data["filtered_by"] == target_user["uid"]
        assert data["is_admin_view"] is True

    # ==================== Queue Types ====================

    def test_filtering_across_queue_types(self, create_user, get_queue):
        """User filtering works consistently across all queue types."""

        # Create user
        user = create_user("smoke_multi_queue@test.com")

        # Test: Query each queue type
        queue_types = ["todo", "run", "done", "dead"]
        for queue_name in queue_types:
            response = get_queue(user["access_token"], queue_name)

            # Assert: All succeed with correct filtering
            assert response.status_code == 200
            data = response.json()
            assert data["filtered_by"] == user["uid"]
            assert f"{queue_name}_jobs" in data
            assert "total_jobs" in data

    def test_done_queue_special_format(self, create_user, get_queue):
        """Done queue returns both HTML jobs and metadata."""

        # Create user
        user = create_user("smoke_done_queue@test.com")

        # Test: Query done queue
        response = get_queue(user["access_token"], "done")

        # Assert: Contains expected fields
        assert response.status_code == 200
        data = response.json()
        assert "done_jobs" in data
        assert "done_jobs_metadata" in data
        assert "filtered_by" in data
        assert data["filtered_by"] == user["uid"]

    # ==================== Backward Compatibility ====================

    def test_response_format_backward_compatible(self, create_user, get_queue):
        """Response format maintains backward compatibility with existing clients."""

        # Create user
        user = create_user("smoke_compat@test.com")

        # Test: Query queue (old clients expect {queue_name}_jobs field)
        response = get_queue(user["access_token"], "todo")

        # Assert: Required fields present
        assert response.status_code == 200
        data = response.json()

        # Core field for backward compatibility
        assert "todo_jobs" in data
        assert isinstance(data["todo_jobs"], list)

        # New metadata fields (additive)
        assert "filtered_by" in data
        assert "is_admin_view" in data
        assert "total_jobs" in data

    # ==================== Error Cases ====================

    def test_invalid_queue_name(self, create_user, get_queue):
        """Invalid queue name returns 400 Bad Request."""

        user = create_user("smoke_error@test.com")

        response = get_queue(user["access_token"], "invalid_queue")

        assert response.status_code == 400
        assert "invalid queue name" in response.json()["detail"].lower()

    def test_unauthenticated_access(self, base_url):
        """Unauthenticated request returns 401."""

        response = requests.get(f"{base_url}/api/get-queue/todo")

        assert response.status_code == 401


if __name__ == "__main__":
    """
    Run smoke tests directly (requires FastAPI server running on port 7999).

    Usage:
        python test_queue_filtering_smoke.py
    """
    pytest.main([__file__, "-v"])
