"""
Smoke Tests for Queue Filtering

End-to-end validation of multi-user queue isolation and filtering.
Tests real-world user scenarios with minimal mocking.
"""

import os
import time

import pytest
import requests
from typing import Dict

# Admin credentials come from their OWN env pair, deliberately NOT the shared
# LUPIN_TEST_INTERACTIVE_MOCK_JOBS_* tester. That account holds roles ["user"], and
# promoting it to admin would quietly gut test_regular_user_wildcard_blocked and
# test_regular_user_other_user_blocked, which exist to prove a NON-admin is refused.
ADMIN_EMAIL    = os.environ.get( "LUPIN_TEST_ADMIN_EMAIL" )
ADMIN_PASSWORD = os.environ.get( "LUPIN_TEST_ADMIN_PASSWORD" )

_missing_admin_vars = [
    name for name, value in (
        ( "LUPIN_TEST_ADMIN_EMAIL",    ADMIN_EMAIL    ),
        ( "LUPIN_TEST_ADMIN_PASSWORD", ADMIN_PASSWORD ),
    ) if not value
]

# A missing credential must SKIP LOUDLY, naming the variable. It must never pass:
# a credentials-missing path that yields green is the same defect as a runner that
# writes a stub for a suite it cannot find.
ADMIN_SKIP_REASON = (
    "admin-only test needs real admin credentials; unset: "
    + ", ".join( _missing_admin_vars )
    + " — export both and re-run, or these three admin tests prove nothing"
)

requires_admin = pytest.mark.skipif( bool( _missing_admin_vars ), reason=ADMIN_SKIP_REASON )


class TestQueueFilteringSmoke:
    """Smoke tests for user-filtered queue views."""

    @pytest.fixture
    def smoke_base_url(self):
        """Base URL for FastAPI server (defaults to the dev server on port 7999)."""
        return os.environ.get( "LUPIN_TEST_BASE_URL", "http://localhost:7999" )

    @pytest.fixture
    def create_user(self, smoke_base_url):
        """Helper fixture to create and login users."""
        def _create_user(email: str, password: str = "SmokeTest123!") -> Dict[str, str]:
            # Register user
            response = requests.post(
                f"{smoke_base_url}/auth/register",
                json={
                    "email": email,
                    "password": password,
                    "display_name": email.split("@")[0]
                }
            )

            # The server answers a duplicate registration with 400 "Email already
            # registered" — match on the wording the server actually sends, not on a
            # paraphrase of it, or a re-run of this file raises instead of logging in.
            if response.status_code == 400 and "already registered" in response.json().get( "detail", "" ):
                response = requests.post(
                    f"{smoke_base_url}/auth/login",
                    json={ "email": email, "password": password }
                )
                if response.status_code != 200:
                    raise Exception( f"Failed to log in existing user {email}: {response.text}" )
            elif response.status_code != 201:
                raise Exception( f"Failed to create user {email}: {response.text}" )

            # Both /auth/register and /auth/login answer {message, user, tokens}.
            # Flatten to the shape the tests index: access_token + uid.
            payload = response.json()
            return {
                "access_token" : payload["tokens"]["access_token"],
                "uid"          : payload["user"]["id"],
                "email"        : payload["user"]["email"],
            }

        return _create_user

    @pytest.fixture
    def push_job(self, smoke_base_url):
        """Helper fixture to push jobs to queue."""
        def _push_job(token: str, question: str) -> Dict:
            response = requests.post(
                f"{smoke_base_url}/api/v2/ask",
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
    def get_queue(self, smoke_base_url):
        """Helper fixture to get queue contents."""
        def _get_queue(token: str, queue_name: str, user_filter: str = None) -> Dict:
            url = f"{smoke_base_url}/api/get-queue/{queue_name}"
            if user_filter is not None:
                url += f"?user_filter={user_filter}"

            response = requests.get(
                url,
                headers={"Authorization": f"Bearer {token}"}
            )
            return response

        return _get_queue

    @pytest.fixture
    def find_job( self, get_queue ):
        """Locate a job by id across every queue a user can see.

        A fast agent (the calculator answers "What is 2+2?" in well under a second)
        has usually left `todo` before the assertion runs, so pinning the job to one
        queue makes the test a coin flip. This follows it instead, and reports the
        queues it searched when it comes up empty.
        """
        def _find_job( token: str, job_id: str, timeout_s: float = 20.0 ) -> dict:
            queue_names = [ "todo", "run", "done" ]
            deadline    = time.time() + timeout_s
            while True:
                for queue_name in queue_names:
                    response = get_queue( token, queue_name )
                    assert response.status_code == 200, f"{queue_name} query failed: {response.text}"
                    for job in response.json()[ f"{queue_name}_jobs_metadata" ]:
                        if job[ "job_id" ] == job_id: return job
                if time.time() >= deadline: return None
                time.sleep( 0.5 )

        return _find_job

    # ==================== Multi-User Isolation Tests ====================

    def test_multi_user_queue_isolation(self, create_user, push_job, get_queue, find_job):
        """Multiple users maintain queue isolation - each sees only their own jobs."""

        # Create two users. The admin half of this scenario lives in
        # test_admin_wildcard_sees_all so that isolation coverage keeps running
        # even when admin credentials are absent.
        user_a = create_user("smoke_user_a@test.com")
        user_b = create_user("smoke_user_b@test.com")

        # Each user pushes one job and we keep its id — the queue a job sits in is
        # a moving target, its id is not.
        job_a = push_job(user_a["access_token"], "What is 2+2?")["job_id"]
        job_b = push_job(user_b["access_token"], "What is 3+3?")["job_id"]
        assert job_a != job_b

        # Test 1: the todo view is filtered to the requesting user and says so
        response_a = get_queue(user_a["access_token"], "todo")
        assert response_a.status_code == 200
        data_a = response_a.json()
        assert data_a["filtered_by"] == user_a["uid"]
        assert data_a["is_admin_view"] is False

        # Test 2: each user can find their OWN job somewhere in their own view
        # The stored question_text is not always the string that was sent: "What is
        # 2+2?" comes back verbatim while "What is 3+3?" comes back as "What is 3 + 3?".
        # Compare with spaces removed so the content claim holds either way.
        def squashed( job ): return ( job["question_text"] or "" ).replace( " ", "" )

        found_a = find_job(user_a["access_token"], job_a)
        assert found_a is not None, f"user A cannot see their own job {job_a} in any queue"
        assert "2+2" in squashed( found_a ), f"job {job_a} carries {found_a['question_text']!r}"

        found_b = find_job(user_b["access_token"], job_b)
        assert found_b is not None, f"user B cannot see their own job {job_b} in any queue"
        assert "3+3" in squashed( found_b ), f"job {job_b} carries {found_b['question_text']!r}"

        # Test 3: and neither can see the OTHER user's job — the isolation this
        # test is named for, which the previous version never actually checked.
        assert find_job(user_a["access_token"], job_b, timeout_s=0) is None, \
            f"user A can see user B's job {job_b}"
        assert find_job(user_b["access_token"], job_a, timeout_s=0) is None, \
            f"user B can see user A's job {job_a}"

    @requires_admin
    def test_admin_wildcard_sees_all(self, create_user, push_job, get_queue):
        """Admin with the wildcard filter sees the whole queue, not just their own."""

        user_a     = create_user("smoke_user_a@test.com")
        admin_user = create_user( ADMIN_EMAIL, ADMIN_PASSWORD )

        push_job(user_a["access_token"], "What is 2+2?")

        response_admin = get_queue(admin_user["access_token"], "todo", user_filter="*")
        assert response_admin.status_code == 200
        data_admin = response_admin.json()
        assert data_admin["filtered_by"] == "*"
        assert data_admin["is_admin_view"] is True
        # Depending on queue state these jobs may already have moved to run/done,
        # so this only pins that the wildcard is honoured and the list is structured.
        assert isinstance(data_admin["todo_jobs_metadata"], list)

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

    @requires_admin
    def test_admin_view_all_toggle(self, create_user, push_job, get_queue):
        """Admin can toggle between own jobs and all jobs."""

        # Get admin user
        admin = create_user( ADMIN_EMAIL, ADMIN_PASSWORD )

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

    @requires_admin
    def test_admin_specific_user_query(self, create_user, push_job, get_queue):
        """Admin can query specific user's jobs."""

        # Create target user and admin
        target_user = create_user("smoke_target@test.com")
        admin = create_user( ADMIN_EMAIL, ADMIN_PASSWORD )

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
            assert f"{queue_name}_jobs_metadata" in data
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
        assert "done_jobs_metadata" in data
        assert "filtered_by" in data
        assert data["filtered_by"] == user["uid"]

    # ==================== Backward Compatibility ====================

    def test_response_format_backward_compatible(self, create_user, get_queue):
        """Response format maintains backward compatibility with existing clients."""

        # Create user
        user = create_user("smoke_compat@test.com")

        # Test: Query queue (clients read the {queue_name}_jobs_metadata field)
        response = get_queue(user["access_token"], "todo")

        # Assert: Required fields present
        assert response.status_code == 200
        data = response.json()

        # Core field of the current contract
        assert "todo_jobs_metadata" in data
        assert isinstance(data["todo_jobs_metadata"], list)

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

    def test_unauthenticated_access(self, smoke_base_url):
        """Unauthenticated request returns 401."""

        response = requests.get(f"{smoke_base_url}/api/get-queue/todo")

        assert response.status_code == 401


if __name__ == "__main__":
    """
    Run smoke tests directly (requires FastAPI server running on port 7999).

    Usage:
        python test_queue_filtering_smoke.py
    """
    pytest.main([__file__, "-v"])
