"""
Unit tests for CJ Flow timed execution, monopolize, and pause features.

Tests pop_next_eligible() and earliest_scheduled_at() methods on FifoQueue,
covering all eligibility combinations: immediate, timed, paused, and mixed.

Session 381: Initial implementation.
"""

import pytest
from datetime import datetime, timedelta
from cosa.rest.fifo_queue import FifoQueue
from cosa.rest.job_state import JobState


class MockSchedulableJob:
    """Mock job implementing QueueableJob protocol with scheduling fields."""

    def __init__( self, id_hash, scheduled_at=None, monopolize=False ):
        # Identity
        self.id_hash               = id_hash
        self.push_counter          = 0
        # Ownership
        self.user_id               = "test_user"
        self.user_email            = "test@test.com"
        self.session_id            = "test_session"
        self.routing_command       = "test"
        # Timestamps
        self.run_date              = "2026-03-27"
        self.created_date          = "2026-03-27"
        self.started_at            = None
        self.completed_at          = None
        # Question/Answer
        self.question              = f"Job {id_hash}"
        self.last_question_asked   = f"Job {id_hash}"
        self.answer                = ""
        self.answer_conversational = ""
        # Type/State
        self.job_type              = "MockSchedulableJob"
        self.is_cache_hit          = False
        self.state                 = JobState.PENDING
        self.error                 = None
        # Scheduling (CJ Flow)
        self.scheduled_at          = scheduled_at
        self.monopolize            = monopolize

    def do_all( self ):
        return "done"

    def code_ran_to_completion( self ):
        return True

    def formatter_ran_to_completion( self ):
        return True


class TestPopNextEligible:
    """Tests for FifoQueue.pop_next_eligible()."""

    def _make_queue( self ):
        return FifoQueue()

    # --- Immediate jobs ---

    def test_pop_immediate_job( self ):
        """scheduled_at=None pops immediately."""
        queue = self._make_queue()
        job = MockSchedulableJob( "job-1" )
        queue.push( job )
        result = queue.pop_next_eligible()
        assert result is job
        assert queue.is_empty()

    def test_pop_eligible_timed_job( self ):
        """Past scheduled_at is eligible."""
        queue = self._make_queue()
        past = ( datetime.now() - timedelta( minutes=5 ) ).isoformat()
        job = MockSchedulableJob( "job-1", scheduled_at=past )
        queue.push( job )
        result = queue.pop_next_eligible()
        assert result is job

    def test_skip_future_timed_job( self ):
        """Future job skipped, returns None."""
        queue = self._make_queue()
        future = ( datetime.now() + timedelta( hours=1 ) ).isoformat()
        job = MockSchedulableJob( "job-1", scheduled_at=future )
        queue.push( job )
        result = queue.pop_next_eligible()
        assert result is None
        assert queue.size() == 1  # Job stays in queue

    def test_mixed_queue_immediate_first( self ):
        """[future, immediate] -> pops immediate, future stays."""
        queue = self._make_queue()
        future = ( datetime.now() + timedelta( hours=1 ) ).isoformat()
        queue.push( MockSchedulableJob( "future-1", scheduled_at=future ) )
        queue.push( MockSchedulableJob( "immediate-1" ) )
        result = queue.pop_next_eligible()
        assert result.id_hash == "immediate-1"
        assert queue.size() == 1

    def test_mixed_queue_eligible_timed( self ):
        """[future, past_timed] -> pops past_timed."""
        queue = self._make_queue()
        future = ( datetime.now() + timedelta( hours=1 ) ).isoformat()
        past = ( datetime.now() - timedelta( minutes=5 ) ).isoformat()
        queue.push( MockSchedulableJob( "future-1", scheduled_at=future ) )
        queue.push( MockSchedulableJob( "past-1", scheduled_at=past ) )
        result = queue.pop_next_eligible()
        assert result.id_hash == "past-1"
        assert queue.size() == 1

    def test_multiple_same_scheduled_time( self ):
        """Two same-time jobs -> first in queue wins."""
        queue = self._make_queue()
        past = ( datetime.now() - timedelta( minutes=5 ) ).isoformat()
        queue.push( MockSchedulableJob( "first", scheduled_at=past ) )
        queue.push( MockSchedulableJob( "second", scheduled_at=past ) )
        result = queue.pop_next_eligible()
        assert result.id_hash == "first"

    def test_all_future_returns_none( self ):
        """All future -> None."""
        queue = self._make_queue()
        future = ( datetime.now() + timedelta( hours=1 ) ).isoformat()
        queue.push( MockSchedulableJob( "f1", scheduled_at=future ) )
        queue.push( MockSchedulableJob( "f2", scheduled_at=future ) )
        assert queue.pop_next_eligible() is None

    # --- Pause ---

    def test_paused_job_skipped( self ):
        """Paused job skipped even if immediate."""
        queue = self._make_queue()
        job   = MockSchedulableJob( "paused-1" )
        job.state = JobState.PAUSED
        queue.push( job )
        assert queue.pop_next_eligible() is None
        assert queue.size() == 1

    def test_paused_timed_job_skipped( self ):
        """Paused + past scheduled_at still skipped."""
        queue = self._make_queue()
        past  = ( datetime.now() - timedelta( minutes=5 ) ).isoformat()
        job   = MockSchedulableJob( "paused-timed", scheduled_at=past )
        job.state = JobState.PAUSED
        queue.push( job )
        assert queue.pop_next_eligible() is None

    def test_resume_makes_eligible( self ):
        """Set state=QUEUED, job becomes eligible."""
        queue = self._make_queue()
        job   = MockSchedulableJob( "paused-1" )
        job.state = JobState.PAUSED
        queue.push( job )
        assert queue.pop_next_eligible() is None
        job.state = JobState.QUEUED
        result = queue.pop_next_eligible()
        assert result is job


class TestEarliestScheduledAt:
    """Tests for FifoQueue.earliest_scheduled_at()."""

    def _make_queue( self ):
        return FifoQueue()

    def test_empty_queue( self ):
        """Empty queue -> None."""
        queue = self._make_queue()
        assert queue.earliest_scheduled_at() is None

    def test_all_immediate( self ):
        """All immediate -> None."""
        queue = self._make_queue()
        queue.push( MockSchedulableJob( "j1" ) )
        queue.push( MockSchedulableJob( "j2" ) )
        assert queue.earliest_scheduled_at() is None

    def test_mixed_returns_minimum( self ):
        """Returns minimum datetime among timed jobs."""
        queue = self._make_queue()
        early = ( datetime.now() + timedelta( hours=1 ) ).isoformat()
        late = ( datetime.now() + timedelta( hours=3 ) ).isoformat()
        queue.push( MockSchedulableJob( "late", scheduled_at=late ) )
        queue.push( MockSchedulableJob( "early", scheduled_at=early ) )
        queue.push( MockSchedulableJob( "immediate" ) )
        result = queue.earliest_scheduled_at()
        assert result is not None
        assert abs( ( result - datetime.fromisoformat( early ) ).total_seconds() ) < 1

    def test_single_timed( self ):
        """Single timed job -> that datetime."""
        queue = self._make_queue()
        scheduled = ( datetime.now() + timedelta( hours=2 ) ).isoformat()
        queue.push( MockSchedulableJob( "timed", scheduled_at=scheduled ) )
        result = queue.earliest_scheduled_at()
        assert result is not None

    def test_ignores_paused( self ):
        """Paused timed job excluded from earliest calc."""
        queue = self._make_queue()
        early = ( datetime.now() + timedelta( hours=1 ) ).isoformat()
        late = ( datetime.now() + timedelta( hours=3 ) ).isoformat()
        paused_job       = MockSchedulableJob( "paused-early", scheduled_at=early )
        paused_job.state = JobState.PAUSED
        queue.push( paused_job )
        queue.push( MockSchedulableJob( "active-late", scheduled_at=late ) )
        result = queue.earliest_scheduled_at()
        # Should return the late time, not the paused early one
        assert abs( ( result - datetime.fromisoformat( late ) ).total_seconds() ) < 1
