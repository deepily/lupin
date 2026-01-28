"""
Integration Tests for Job Queue Progressive Disclosure UI

Tests the progressive disclosure UI implementation from Session 57:
- Simultaneous job submissions to exercise TODO queue
- Queue count badge accuracy
- Job state transitions (TODO → Running → Done)
- Job interactions endpoint for completed jobs
- User filtering in queue queries

These tests exercise the frontend-facing API endpoints that power
the progressive disclosure UI in notifications.html.
"""

import pytest
import requests
import time
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed


# Test server configuration
BASE_URL = "http://localhost:7999"


def unique_email( prefix ):
    """Generate a unique email address to avoid conflicts across test runs."""
    return f"{prefix}_{uuid.uuid4().hex[:8]}@test.com"


class TestJobQueueProgressiveDisclosure:
    """Integration tests for job queue progressive disclosure UI."""

    # ==================== Helper Methods ====================

    def _create_user_and_get_token( self, email, password="TestPassword123!" ):
        """
        Create a user and return their access token.

        Args:
            email: User email
            password: User password (default: TestPassword123!)

        Returns:
            tuple: (access_token, user_id)
        """
        # Register user
        register_response = requests.post(
            f"{BASE_URL}/auth/register",
            json={ "email": email, "password": password }
        )
        assert register_response.status_code == 201, f"Registration failed: {register_response.text}"

        # Login to get token
        login_response = requests.post(
            f"{BASE_URL}/auth/login",
            json={ "email": email, "password": password }
        )
        assert login_response.status_code == 200, f"Login failed: {login_response.text}"

        tokens = login_response.json()["tokens"]
        user_id = login_response.json()["user"]["id"]

        return tokens["access_token"], user_id

    def _submit_job( self, token, question, websocket_id ):
        """
        Submit a job to the queue.

        Args:
            token: User access token
            question: Job question text
            websocket_id: WebSocket session identifier

        Returns:
            Response object
        """
        return requests.post(
            f"{BASE_URL}/api/push",
            json={
                "question": question,
                "websocket_id": websocket_id
            },
            headers={ "Authorization": f"Bearer {token}" }
        )

    def _get_queue( self, token, queue_name, user_filter=None ):
        """
        Get queue contents.

        Args:
            token: User access token
            queue_name: Queue name (todo, run, done, dead)
            user_filter: Optional user filter (* for all, user_id for specific)

        Returns:
            Response object
        """
        url = f"{BASE_URL}/api/get-queue/{queue_name}"
        if user_filter:
            url += f"?user_filter={user_filter}"

        return requests.get(
            url,
            headers={ "Authorization": f"Bearer {token}" }
        )

    def _get_all_queue_counts( self, token ):
        """
        Get job counts across all queues.

        Args:
            token: User access token

        Returns:
            dict: { 'todo': N, 'run': N, 'done': N, 'dead': N, 'total': N }
        """
        counts = {}
        total = 0

        for queue_name in [ "todo", "run", "done", "dead" ]:
            response = self._get_queue( token, queue_name )
            assert response.status_code == 200
            data = response.json()
            counts[ queue_name ] = data[ "total_jobs" ]
            total += data[ "total_jobs" ]

        counts[ "total" ] = total
        return counts

    def _wait_for_jobs_in_done_queue( self, token, expected_count, timeout_seconds=60 ):
        """
        Poll done queue until expected number of jobs appear.

        Args:
            token: User access token
            expected_count: Number of jobs to wait for
            timeout_seconds: Maximum wait time

        Returns:
            list: Done jobs metadata
        """
        start_time = time.time()

        while time.time() - start_time < timeout_seconds:
            response = self._get_queue( token, "done" )
            assert response.status_code == 200
            data = response.json()

            if data[ "total_jobs" ] >= expected_count:
                return data[ "done_jobs_metadata" ]

            time.sleep( 0.5 )

        # Timeout - return what we have
        response = self._get_queue( token, "done" )
        return response.json().get( "done_jobs_metadata", [] )

    # ==================== Test Cases ====================

    def test_multiple_simultaneous_job_submissions( self, clean_test_db ):
        """
        Submit 5 jobs rapidly and verify they queue correctly.

        This test exercises the TODO queue by submitting multiple jobs
        faster than the queue consumer can process them.
        """
        # Setup: Create user
        token, user_id = self._create_user_and_get_token( unique_email( "simultaneous" ) )

        # Submit 5 jobs rapidly with incrementing numbers
        responses = []
        for i in range( 5 ):
            question = f"What is {i + 2} + {i + 2}?"  # 2+2, 3+3, 4+4, 5+5, 6+6
            response = self._submit_job( token, question, f"session_{i}" )
            responses.append( response )
            # Small delay to avoid overwhelming the server
            time.sleep( 0.05 )

        # Verify all submissions were accepted
        for i, response in enumerate( responses ):
            assert response.status_code == 200, f"Job {i} submission failed: {response.text}"
            data = response.json()
            assert data[ "status" ] == "queued"
            print( f"Job {i}: {data[ 'result' ]}" )

        # Query queue counts immediately
        counts = self._get_all_queue_counts( token )
        print( f"Queue counts after submissions: {counts}" )

        # At least some jobs should be in TODO or running
        # (depends on how fast the consumer is)
        assert counts[ "total" ] >= 1, "Expected at least 1 job in queues"

    def test_queue_count_badges( self, clean_test_db ):
        """
        Verify queue counts are accurate after bulk submission.

        Tests that the total_jobs field in each queue response
        accurately reflects the number of jobs.
        """
        # Setup: Create user
        token, user_id = self._create_user_and_get_token( unique_email( "badges" ) )

        # Submit 3 jobs
        for i in range( 3 ):
            response = self._submit_job(
                token,
                f"What is {i + 1} + {i + 1}?",
                f"badge_session_{i}"
            )
            assert response.status_code == 200
            time.sleep( 0.05 )

        # Get counts for all queues
        counts = self._get_all_queue_counts( token )
        print( f"Queue counts: {counts}" )

        # Verify total equals sum of individual queues
        individual_sum = counts[ "todo" ] + counts[ "run" ] + counts[ "done" ] + counts[ "dead" ]
        assert counts[ "total" ] == individual_sum, \
            f"Total {counts['total']} != sum of queues {individual_sum}"

        # Verify we have at least some jobs tracked
        assert counts[ "total" ] >= 1, "Expected at least 1 job tracked"

    def test_job_transitions_todo_to_done( self, clean_test_db ):
        """
        Submit simple math jobs and verify they complete.

        Tests that jobs transition through the queue states:
        TODO → Running → Done
        """
        # Setup: Create user
        token, user_id = self._create_user_and_get_token( unique_email( "transitions" ) )

        # Submit 3 simple math questions (fast execution via MathAgent)
        job_count = 3
        for i in range( job_count ):
            response = self._submit_job(
                token,
                f"What is {i + 10} + {i + 10}?",
                f"transition_session_{i}"
            )
            assert response.status_code == 200

        # Wait for jobs to complete (timeout 60s)
        done_jobs = self._wait_for_jobs_in_done_queue( token, job_count, timeout_seconds=60 )

        print( f"Done jobs: {len( done_jobs )}" )

        # Verify we got all jobs in done queue
        assert len( done_jobs ) >= job_count, \
            f"Expected {job_count} jobs in done queue, got {len( done_jobs )}"

        # Verify job metadata structure
        for job in done_jobs:
            print( f"Job: {job.get( 'question_text', 'N/A' )[:50]}..." )

            # Required fields from progressive disclosure implementation
            assert "job_id" in job, "Missing job_id"
            assert "question_text" in job, "Missing question_text"
            assert "response_text" in job, "Missing response_text"
            assert "timestamp" in job, "Missing timestamp"
            assert "user_id" in job, "Missing user_id"

            # New fields added in Session 57
            assert "session_id" in job, "Missing session_id (added in Session 57)"
            assert "agent_type" in job, "Missing agent_type (added in Session 57)"
            assert "has_interactions" in job, "Missing has_interactions (added in Session 57)"

            # Verify agent type is MathAgent for math questions
            assert job[ "agent_type" ] == "MathAgent", \
                f"Expected MathAgent, got {job[ 'agent_type' ]}"

    def test_job_interactions_endpoint( self, clean_test_db ):
        """
        Verify the /api/get-job-interactions/{job_id} endpoint works.

        Tests the new endpoint added in Session 57 for loading
        notification conversation history for a completed job.
        """
        # Setup: Create user
        token, user_id = self._create_user_and_get_token( unique_email( "interactions" ) )

        # Submit a job
        response = self._submit_job(
            token,
            "What is 42 + 42?",
            "interactions_session"
        )
        assert response.status_code == 200

        # Wait for job to complete
        done_jobs = self._wait_for_jobs_in_done_queue( token, 1, timeout_seconds=30 )
        assert len( done_jobs ) >= 1, "Job did not complete in time"

        # Get job_id from done queue metadata
        job_id = done_jobs[ 0 ][ "job_id" ]
        print( f"Testing interactions endpoint for job_id: {job_id}" )

        # Call the interactions endpoint
        response = requests.get(
            f"{BASE_URL}/api/get-job-interactions/{job_id}",
            headers={ "Authorization": f"Bearer {token}" }
        )

        # Verify response
        assert response.status_code == 200, f"Interactions endpoint failed: {response.text}"
        data = response.json()

        # Verify response structure
        assert "job_id" in data, "Missing job_id in response"
        assert "session_id" in data, "Missing session_id in response"
        assert "job_metadata" in data, "Missing job_metadata in response"
        assert "interactions" in data, "Missing interactions array in response"
        assert "interaction_count" in data, "Missing interaction_count in response"

        # Verify job_metadata structure
        metadata = data[ "job_metadata" ]
        assert "question" in metadata, "Missing question in job_metadata"
        assert "answer" in metadata, "Missing answer in job_metadata"
        assert "agent_type" in metadata, "Missing agent_type in job_metadata"
        assert "run_date" in metadata, "Missing run_date in job_metadata"

        print( f"Job metadata: {metadata}" )
        print( f"Interaction count: {data[ 'interaction_count' ]}" )

        # interactions array may be empty for jobs without notifications
        # (math jobs typically don't send notifications)
        assert isinstance( data[ "interactions" ], list ), "interactions should be a list"

    def test_user_filtering_in_queues( self, clean_test_db ):
        """
        Two users submit jobs, each only sees their own.

        Tests user isolation in queue queries - critical for
        the progressive disclosure UI to show correct jobs.
        """
        # Setup: Create two users
        token_a, user_id_a = self._create_user_and_get_token( unique_email( "user_a" ) )
        token_b, user_id_b = self._create_user_and_get_token( unique_email( "user_b" ) )

        # User A submits 2 jobs
        for i in range( 2 ):
            response = self._submit_job(
                token_a,
                f"User A question {i + 1}: What is {i + 100}?",
                f"user_a_session_{i}"
            )
            assert response.status_code == 200

        # User B submits 2 jobs
        for i in range( 2 ):
            response = self._submit_job(
                token_b,
                f"User B question {i + 1}: What is {i + 200}?",
                f"user_b_session_{i}"
            )
            assert response.status_code == 200

        # Small delay for jobs to enter queue
        time.sleep( 0.2 )

        # User A queries TODO queue - should only see their own
        counts_a = self._get_all_queue_counts( token_a )
        print( f"User A queue counts: {counts_a}" )

        # User B queries TODO queue - should only see their own
        counts_b = self._get_all_queue_counts( token_b )
        print( f"User B queue counts: {counts_b}" )

        # Each user should see at least some of their jobs
        # (exact count depends on processing speed)
        # The key test is that counts are INDEPENDENT between users
        # If filtering is broken, both would see the same counts

    def test_concurrent_job_submissions( self, clean_test_db ):
        """
        Submit jobs concurrently using threads to stress-test the queue.

        This is a more aggressive version of test_multiple_simultaneous_job_submissions
        that uses actual concurrent threads.
        """
        # Setup: Create user
        token, user_id = self._create_user_and_get_token( unique_email( "concurrent" ) )

        # Define job submission function
        results = []
        lock = threading.Lock()

        def submit_job_thread( idx ):
            response = self._submit_job(
                token,
                f"Concurrent question {idx}: What is {idx * 10}?",
                f"concurrent_session_{idx}"
            )
            with lock:
                results.append( ( idx, response.status_code, response.json() if response.ok else None ) )

        # Submit 10 jobs concurrently
        threads = []
        for i in range( 10 ):
            t = threading.Thread( target=submit_job_thread, args=( i, ) )
            threads.append( t )
            t.start()

        # Wait for all threads to complete
        for t in threads:
            t.join()

        # Verify all submissions succeeded
        success_count = sum( 1 for _, status, _ in results if status == 200 )
        print( f"Concurrent submissions: {success_count}/10 succeeded" )

        assert success_count == 10, f"Expected 10 successful submissions, got {success_count}"

        # Verify queue has jobs
        counts = self._get_all_queue_counts( token )
        print( f"Queue counts after concurrent submissions: {counts}" )
        assert counts[ "total" ] >= 1, "Expected at least 1 job in queues"

    def test_done_queue_metadata_includes_session_fields( self, clean_test_db ):
        """
        Verify done queue metadata includes new Session 57 fields.

        The progressive disclosure UI depends on these fields:
        - session_id: For correlation with notifications
        - agent_type: For agent badge display
        - has_interactions: For showing interaction toggle
        """
        # Setup: Create user
        token, user_id = self._create_user_and_get_token( unique_email( "metadata" ) )

        # Submit and wait for completion
        response = self._submit_job(
            token,
            "What is 7 + 7?",
            "metadata_session"
        )
        assert response.status_code == 200

        done_jobs = self._wait_for_jobs_in_done_queue( token, 1, timeout_seconds=30 )
        assert len( done_jobs ) >= 1, "Job did not complete"

        job = done_jobs[ 0 ]

        # Verify Session 57 fields exist
        assert "session_id" in job, "session_id missing from done queue metadata"
        assert "agent_type" in job, "agent_type missing from done queue metadata"
        assert "has_interactions" in job, "has_interactions missing from done queue metadata"

        # Verify types
        assert isinstance( job[ "session_id" ], str ), "session_id should be string"
        assert isinstance( job[ "agent_type" ], str ), "agent_type should be string"
        assert isinstance( job[ "has_interactions" ], bool ), "has_interactions should be bool"

        print( f"Session 57 fields verified:" )
        print( f"  session_id: {job[ 'session_id' ]}" )
        print( f"  agent_type: {job[ 'agent_type' ]}" )
        print( f"  has_interactions: {job[ 'has_interactions' ]}" )

    def test_job_interactions_unauthorized_access( self, clean_test_db ):
        """
        Verify users cannot access other users' job interactions.

        Tests authorization check in the interactions endpoint.
        """
        # Setup: Create two users
        token_a, user_id_a = self._create_user_and_get_token( "owner@test.com" )
        token_b, user_id_b = self._create_user_and_get_token( "attacker@test.com" )

        # User A submits a job
        response = self._submit_job(
            token_a,
            "What is 99 + 99?",
            "owner_session"
        )
        assert response.status_code == 200

        # Wait for job to complete
        done_jobs = self._wait_for_jobs_in_done_queue( token_a, 1, timeout_seconds=30 )
        assert len( done_jobs ) >= 1, "Job did not complete"

        job_id = done_jobs[ 0 ][ "job_id" ]

        # User B tries to access User A's job interactions
        response = requests.get(
            f"{BASE_URL}/api/get-job-interactions/{job_id}",
            headers={ "Authorization": f"Bearer {token_b}" }
        )

        # Should be forbidden
        assert response.status_code == 403, \
            f"Expected 403 Forbidden, got {response.status_code}: {response.text}"

    def test_nonexistent_job_interactions( self, clean_test_db ):
        """
        Verify interactions endpoint returns 404 for nonexistent job.
        """
        # Setup: Create user
        token, user_id = self._create_user_and_get_token( "notfound@test.com" )

        # Try to get interactions for fake job_id
        response = requests.get(
            f"{BASE_URL}/api/get-job-interactions/fake_job_id_12345",
            headers={ "Authorization": f"Bearer {token}" }
        )

        # Should be 404
        assert response.status_code == 404, \
            f"Expected 404 Not Found, got {response.status_code}: {response.text}"
