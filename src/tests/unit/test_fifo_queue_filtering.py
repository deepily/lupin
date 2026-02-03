"""
Unit Tests for FifoQueue User Filtering

Tests the get_jobs_for_user() and get_all_jobs() methods from FifoQueue.
Validates user-specific job retrieval and filtering logic.
"""

import pytest
from cosa.rest.fifo_queue import FifoQueue


class MockJob:
    """
    Mock job object for testing FifoQueue filtering.

    Implements the full QueueableJob protocol required by FifoQueue.push().
    """

    def __init__( self, id_hash: str, content: str, user_id: str = "test_user" ):
        # Core identifiers
        self.id_hash               = id_hash
        self.content               = content
        self.push_counter          = 0

        # User/session info
        self.user_id               = user_id
        self.user_email            = f"{user_id}@test.com"
        self.session_id            = "test_session"

        # Job metadata
        self.routing_command       = "test"
        self.run_date              = "2026-02-02"
        self.created_date          = "2026-02-02"
        self.started_at            = None
        self.completed_at          = None

        # Question/answer data
        self.question              = content
        self.last_question_asked   = content
        self.answer                = f"Answer to {content}"
        self.answer_conversational = f"Here's the answer to {content}"

        # Status tracking
        self.job_type              = "MockJob"
        self.is_cache_hit          = False
        self.status                = "pending"
        self.error                 = None

    def do_all( self ):
        """Execute the job (mock implementation)."""
        return "done"

    def code_ran_to_completion( self ):
        """Check if code execution completed."""
        return True

    def formatter_ran_to_completion( self ):
        """Check if formatting completed."""
        return True


class TestFifoQueueFiltering:
    """Unit tests for FifoQueue user filtering methods."""

    # ==================== get_jobs_for_user() Tests ====================

    def test_get_jobs_for_user_returns_correct_jobs(self):
        """get_jobs_for_user() returns only jobs belonging to specified user."""
        queue = FifoQueue()

        # Setup: Create jobs and associate with users
        job1 = MockJob("job_1", "User A Job 1")
        job2 = MockJob("job_2", "User B Job")
        job3 = MockJob("job_3", "User A Job 2")

        queue.user_job_tracker.associate_job_with_user("job_1", "user_a")
        queue.user_job_tracker.associate_job_with_user("job_2", "user_b")
        queue.user_job_tracker.associate_job_with_user("job_3", "user_a")

        queue.push(job1)
        queue.push(job2)
        queue.push(job3)

        # Test: Filter for user_a
        user_a_jobs = queue.get_jobs_for_user("user_a")

        # Assert: Only user_a's jobs returned
        assert len(user_a_jobs) == 2
        assert user_a_jobs[0].id_hash == "job_1"
        assert user_a_jobs[1].id_hash == "job_3"

    def test_get_jobs_for_user_preserves_order(self):
        """get_jobs_for_user() preserves insertion order of filtered jobs."""
        queue = FifoQueue()

        # Setup: Multiple jobs for same user
        jobs = [
            MockJob("job_1", "First"),
            MockJob("job_2", "Second"),
            MockJob("job_3", "Third")
        ]

        for job in jobs:
            queue.user_job_tracker.associate_job_with_user(job.id_hash, "user_x")
            queue.push(job)

        # Test: Get user's jobs
        user_jobs = queue.get_jobs_for_user("user_x")

        # Assert: Order preserved
        assert [j.id_hash for j in user_jobs] == ["job_1", "job_2", "job_3"]

    def test_get_jobs_for_nonexistent_user_returns_empty(self):
        """get_jobs_for_user() returns empty list for user with no jobs."""
        queue = FifoQueue()

        # Setup: Add jobs for different user
        job = MockJob("job_1", "Content")
        queue.user_job_tracker.associate_job_with_user("job_1", "user_a")
        queue.push(job)

        # Test: Query for different user
        result = queue.get_jobs_for_user("user_b")

        # Assert: Empty list returned
        assert result == []

    def test_get_jobs_for_user_empty_queue_returns_empty(self):
        """get_jobs_for_user() returns empty list for empty queue."""
        queue = FifoQueue()

        result = queue.get_jobs_for_user("any_user")

        assert result == []

    def test_get_jobs_for_user_filters_mixed_jobs(self):
        """get_jobs_for_user() correctly filters interleaved jobs from multiple users."""
        queue = FifoQueue()

        # Setup: Interleave jobs from different users
        jobs_data = [
            ("job_1", "user_a", "A1"),
            ("job_2", "user_b", "B1"),
            ("job_3", "user_a", "A2"),
            ("job_4", "user_c", "C1"),
            ("job_5", "user_a", "A3"),
            ("job_6", "user_b", "B2")
        ]

        for id_hash, user_id, content in jobs_data:
            job = MockJob(id_hash, content)
            queue.user_job_tracker.associate_job_with_user(id_hash, user_id)
            queue.push(job)

        # Test: Filter for user_a
        user_a_jobs = queue.get_jobs_for_user("user_a")

        # Assert: Only user_a's jobs, in order
        assert len(user_a_jobs) == 3
        assert [j.content for j in user_a_jobs] == ["A1", "A2", "A3"]

    def test_get_jobs_for_user_excludes_jobs_without_id_hash(self):
        """get_jobs_for_user() excludes jobs without id_hash attribute."""
        queue = FifoQueue()

        # Setup: Mix of valid and invalid jobs
        job1 = MockJob("job_1", "Valid")
        job2 = type('InvalidJob', (), {'content': 'No id_hash'})()  # Missing id_hash

        queue.user_job_tracker.associate_job_with_user("job_1", "user_a")
        queue.queue_list.append(job1)
        queue.queue_list.append(job2)

        # Test: Get user's jobs
        user_jobs = queue.get_jobs_for_user("user_a")

        # Assert: Only valid job returned
        assert len(user_jobs) == 1
        assert user_jobs[0].id_hash == "job_1"

    # ==================== get_all_jobs() Tests ====================

    def test_get_all_jobs_returns_all(self):
        """get_all_jobs() returns all jobs regardless of user."""
        queue = FifoQueue()

        # Setup: Jobs from different users
        job1 = MockJob("job_1", "User A")
        job2 = MockJob("job_2", "User B")
        job3 = MockJob("job_3", "User C")

        queue.user_job_tracker.associate_job_with_user("job_1", "user_a")
        queue.user_job_tracker.associate_job_with_user("job_2", "user_b")
        queue.user_job_tracker.associate_job_with_user("job_3", "user_c")

        queue.push(job1)
        queue.push(job2)
        queue.push(job3)

        # Test: Get all jobs
        all_jobs = queue.get_all_jobs()

        # Assert: All jobs returned
        assert len(all_jobs) == 3
        assert all_jobs[0].id_hash == "job_1"
        assert all_jobs[1].id_hash == "job_2"
        assert all_jobs[2].id_hash == "job_3"

    def test_get_all_jobs_returns_copy(self):
        """get_all_jobs() returns a copy, not reference to internal list."""
        queue = FifoQueue()

        job = MockJob("job_1", "Content")
        queue.push(job)

        # Test: Get all jobs and modify
        all_jobs = queue.get_all_jobs()
        all_jobs.append(MockJob("job_2", "New"))

        # Assert: Original queue unchanged
        assert queue.size() == 1
        assert len(queue.queue_list) == 1

    def test_get_all_jobs_empty_queue_returns_empty(self):
        """get_all_jobs() returns empty list for empty queue."""
        queue = FifoQueue()

        result = queue.get_all_jobs()

        assert result == []

    def test_get_all_jobs_preserves_order(self):
        """get_all_jobs() preserves insertion order."""
        queue = FifoQueue()

        jobs = [
            MockJob("job_1", "First"),
            MockJob("job_2", "Second"),
            MockJob("job_3", "Third")
        ]

        for job in jobs:
            queue.push(job)

        all_jobs = queue.get_all_jobs()

        assert [j.id_hash for j in all_jobs] == ["job_1", "job_2", "job_3"]

    # ==================== UserJobTracker Integration Tests ====================

    def test_user_job_tracker_singleton_integration(self):
        """Multiple queues share same UserJobTracker singleton."""
        queue1 = FifoQueue()
        queue2 = FifoQueue()

        # Setup: Associate job in queue1
        job = MockJob("shared_job", "Content")
        queue1.user_job_tracker.associate_job_with_user("shared_job", "user_a")
        queue1.push(job)

        # Also push to queue2
        queue2.push(job)

        # Test: Both queues can filter by same association
        queue1_jobs = queue1.get_jobs_for_user("user_a")
        queue2_jobs = queue2.get_jobs_for_user("user_a")

        # Assert: Both find the job (singleton tracker works)
        assert len(queue1_jobs) == 1
        assert len(queue2_jobs) == 1

    def test_user_job_tracker_multiple_users(self):
        """UserJobTracker correctly handles multiple users."""
        queue = FifoQueue()

        # Setup: Jobs for multiple users
        for i in range(1, 4):
            for user in ["alice", "bob", "charlie"]:
                job = MockJob(f"{user}_job_{i}", f"{user} Job {i}")
                queue.user_job_tracker.associate_job_with_user(f"{user}_job_{i}", user)
                queue.push(job)

        # Test: Each user gets their own jobs
        alice_jobs = queue.get_jobs_for_user("alice")
        bob_jobs = queue.get_jobs_for_user("bob")
        charlie_jobs = queue.get_jobs_for_user("charlie")

        # Assert: Correct job counts
        assert len(alice_jobs) == 3
        assert len(bob_jobs) == 3
        assert len(charlie_jobs) == 3

        # Assert: Correct job contents
        assert all("alice" in j.id_hash for j in alice_jobs)
        assert all("bob" in j.id_hash for j in bob_jobs)
        assert all("charlie" in j.id_hash for j in charlie_jobs)

    # ==================== Edge Cases ====================

    def test_job_with_id_hash_but_no_user_association(self):
        """Job with id_hash but no user association is not returned."""
        queue = FifoQueue()

        # Setup: Job without user association
        job = MockJob("orphan_job", "No association")
        queue.push(job)
        # Note: NOT calling user_job_tracker.associate_job_with_user()

        # Test: Try to get jobs for any user
        result = queue.get_jobs_for_user("any_user")

        # Assert: Orphan job not returned
        assert result == []

    def test_filtering_after_queue_pop(self):
        """Filtering works correctly after jobs are popped from queue."""
        queue = FifoQueue()

        # Setup: Add 3 jobs for user_a
        for i in range(1, 4):
            job = MockJob(f"job_{i}", f"Job {i}")
            queue.user_job_tracker.associate_job_with_user(f"job_{i}", "user_a")
            queue.push(job)

        # Test: Pop one job, then filter
        queue.pop()
        user_jobs = queue.get_jobs_for_user("user_a")

        # Assert: Only remaining jobs returned
        assert len(user_jobs) == 2
        assert user_jobs[0].id_hash == "job_2"
        assert user_jobs[1].id_hash == "job_3"

    def test_performance_with_many_jobs(self):
        """Filtering performance acceptable with larger job counts."""
        queue = FifoQueue()

        # Setup: 100 jobs across 10 users
        for i in range(100):
            user_id = f"user_{i % 10}"
            job = MockJob(f"job_{i}", f"Content {i}")
            queue.user_job_tracker.associate_job_with_user(f"job_{i}", user_id)
            queue.push(job)

        # Test: Filter for specific user
        user_0_jobs = queue.get_jobs_for_user("user_0")

        # Assert: Correct jobs returned (every 10th job)
        assert len(user_0_jobs) == 10
        assert all(int(j.id_hash.split("_")[1]) % 10 == 0 for j in user_0_jobs)
