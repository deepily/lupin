"""
Unit tests for CJ Flow consumer thread with timed execution support.

Tests the consumer loop's interaction with pop_next_eligible(), dynamic
timeout calculation, and wake-up behavior for scheduled/paused jobs.

Session 381: Initial implementation.
"""

import pytest
import threading
import time
from datetime import datetime, timedelta
from unittest.mock import Mock, MagicMock
from cosa.rest.fifo_queue import FifoQueue
from cosa.rest.queue_consumer import start_todo_producer_run_consumer_thread


class MockSchedulableJob:
    """Mock job with scheduling fields for consumer tests."""

    def __init__( self, id_hash, scheduled_at=None, monopolize=False, paused=False ):
        self.id_hash               = id_hash
        self.push_counter          = 0
        self.user_id               = "test_user"
        self.user_email            = "test@test.com"
        self.session_id            = "test_session"
        self.routing_command       = "test"
        self.run_date              = datetime.now().isoformat()
        self.created_date          = datetime.now().isoformat()
        self.started_at            = None
        self.completed_at          = None
        self.question              = f"Job {id_hash}"
        self.last_question_asked   = f"Job {id_hash}"
        self.answer                = ""
        self.answer_conversational = ""
        self.job_type              = "MockSchedulableJob"
        self.is_cache_hit          = False
        self.status                = "pending"
        self.error                 = None
        self.scheduled_at          = scheduled_at
        self.monopolize            = monopolize
        self.paused                = paused

    def do_all( self ):
        return "done"

    def code_ran_to_completion( self ):
        return True

    def formatter_ran_to_completion( self ):
        return True


class MockTodoQueue( FifoQueue ):
    """TodoFifoQueue-like mock with condition variable for consumer tests."""

    def __init__( self ):
        super().__init__()
        self.condition        = threading.Condition()
        self.consumer_running = True
        self.debug            = False

    def push_with_notify( self, job ):
        """Push a job and notify the consumer (mimics TodoFifoQueue.push)."""
        with self.condition:
            super().push( job )
            self.condition.notify()

    def delete_by_id_hash( self, id_hash ):
        """Override with notify (mimics TodoFifoQueue override)."""
        with self.condition:
            result = super().delete_by_id_hash( id_hash )
            if result:
                self.condition.notify()
            return result

    def shutdown( self ):
        """Signal consumer to stop."""
        with self.condition:
            self.consumer_running = False
            self.condition.notify()


class TestConsumerTimed:
    """Tests for consumer thread with timed execution."""

    def _start_consumer( self, todo_queue, processed_jobs ):
        """Start consumer with a mock running queue that tracks processed jobs."""
        running_queue = Mock()
        running_queue.websocket_mgr = None

        def mock_process( job ):
            processed_jobs.append( job.id_hash )

        running_queue._process_job = mock_process

        thread = start_todo_producer_run_consumer_thread( todo_queue, running_queue )
        time.sleep( 0.05 )  # Let consumer thread start
        return thread

    def test_consumer_processes_immediate_job( self ):
        """Basic: push immediate job, consumer processes it."""
        todo_queue = MockTodoQueue()
        processed = []
        thread = self._start_consumer( todo_queue, processed )

        job = MockSchedulableJob( "imm-1" )
        todo_queue.push_with_notify( job )
        time.sleep( 0.2 )

        assert "imm-1" in processed
        todo_queue.shutdown()
        thread.join( timeout=1.0 )

    def test_consumer_sleeps_until_scheduled( self ):
        """Push job at now+0.3s, verify ~0.3s delay."""
        todo_queue = MockTodoQueue()
        processed = []
        thread = self._start_consumer( todo_queue, processed )

        scheduled = ( datetime.now() + timedelta( seconds=0.3 ) ).isoformat()
        job = MockSchedulableJob( "timed-1", scheduled_at=scheduled )
        todo_queue.push_with_notify( job )

        # Should NOT be processed immediately
        time.sleep( 0.1 )
        assert "timed-1" not in processed

        # Should be processed after ~0.3s
        time.sleep( 0.4 )
        assert "timed-1" in processed

        todo_queue.shutdown()
        thread.join( timeout=1.0 )

    def test_earlier_job_wakes_consumer( self ):
        """Sleeping for T+5s, push immediate job, wakes and processes immediately."""
        todo_queue = MockTodoQueue()
        processed = []
        thread = self._start_consumer( todo_queue, processed )

        # Push far-future job — consumer sleeps for ~5s
        future = ( datetime.now() + timedelta( seconds=5 ) ).isoformat()
        todo_queue.push_with_notify( MockSchedulableJob( "future-1", scheduled_at=future ) )
        time.sleep( 0.1 )

        # Push immediate job — should wake consumer
        todo_queue.push_with_notify( MockSchedulableJob( "immediate-1" ) )
        time.sleep( 0.2 )

        assert "immediate-1" in processed
        assert "future-1" not in processed  # Still waiting

        todo_queue.shutdown()
        thread.join( timeout=1.0 )

    def test_timed_job_deleted_while_waiting( self ):
        """Delete the job consumer is sleeping for — consumer recalculates."""
        todo_queue = MockTodoQueue()
        processed = []
        thread = self._start_consumer( todo_queue, processed )

        future = ( datetime.now() + timedelta( seconds=5 ) ).isoformat()
        todo_queue.push_with_notify( MockSchedulableJob( "future-del", scheduled_at=future ) )
        time.sleep( 0.1 )

        # Delete the job — delete_by_id_hash calls condition.notify()
        todo_queue.delete_by_id_hash( "future-del" )
        time.sleep( 0.2 )

        # Queue is now empty, consumer should be waiting (not stuck)
        assert todo_queue.is_empty()
        assert "future-del" not in processed

        todo_queue.shutdown()
        thread.join( timeout=1.0 )

    def test_empty_then_timed_push( self ):
        """Empty queue -> push timed job -> consumer sleeps until scheduled."""
        todo_queue = MockTodoQueue()
        processed = []
        thread = self._start_consumer( todo_queue, processed )
        time.sleep( 0.1 )  # Consumer is waiting on empty queue

        scheduled = ( datetime.now() + timedelta( seconds=0.3 ) ).isoformat()
        todo_queue.push_with_notify( MockSchedulableJob( "timed-2", scheduled_at=scheduled ) )

        time.sleep( 0.1 )
        assert "timed-2" not in processed  # Not yet

        time.sleep( 0.4 )
        assert "timed-2" in processed  # Now eligible

        todo_queue.shutdown()
        thread.join( timeout=1.0 )

    def test_immediate_bypasses_future( self ):
        """[future, immediate] -> immediate processed first."""
        todo_queue = MockTodoQueue()
        processed = []
        thread = self._start_consumer( todo_queue, processed )

        future = ( datetime.now() + timedelta( seconds=5 ) ).isoformat()
        todo_queue.push_with_notify( MockSchedulableJob( "future-2", scheduled_at=future ) )
        todo_queue.push_with_notify( MockSchedulableJob( "immediate-2" ) )
        time.sleep( 0.3 )

        assert processed[ 0 ] == "immediate-2"

        todo_queue.shutdown()
        thread.join( timeout=1.0 )

    def test_monopolize_flag_preserved( self ):
        """Job with monopolize=True processes normally in serial mode."""
        todo_queue = MockTodoQueue()
        processed = []
        thread = self._start_consumer( todo_queue, processed )

        job = MockSchedulableJob( "mono-1", monopolize=True )
        todo_queue.push_with_notify( job )
        time.sleep( 0.2 )

        assert "mono-1" in processed

        todo_queue.shutdown()
        thread.join( timeout=1.0 )

    def test_monopolize_plus_timed( self ):
        """Timed + monopolize job respects both: waits then processes."""
        todo_queue = MockTodoQueue()
        processed = []
        thread = self._start_consumer( todo_queue, processed )

        scheduled = ( datetime.now() + timedelta( seconds=0.3 ) ).isoformat()
        job = MockSchedulableJob( "mono-timed", scheduled_at=scheduled, monopolize=True )
        todo_queue.push_with_notify( job )

        time.sleep( 0.1 )
        assert "mono-timed" not in processed

        time.sleep( 0.4 )
        assert "mono-timed" in processed

        todo_queue.shutdown()
        thread.join( timeout=1.0 )

    def test_pause_while_consumer_sleeping( self ):
        """Pause a timed job that consumer is sleeping for — recalculates."""
        todo_queue = MockTodoQueue()
        processed = []
        thread = self._start_consumer( todo_queue, processed )

        scheduled = ( datetime.now() + timedelta( seconds=0.5 ) ).isoformat()
        job = MockSchedulableJob( "pause-sleep", scheduled_at=scheduled )
        todo_queue.push_with_notify( job )
        time.sleep( 0.1 )

        # Pause the job — consumer should NOT process it even after scheduled time
        job.paused = True
        with todo_queue.condition:
            todo_queue.condition.notify()  # Wake consumer to see paused state
        time.sleep( 0.8 )  # Well past scheduled time

        assert "pause-sleep" not in processed

        todo_queue.shutdown()
        thread.join( timeout=1.0 )

    def test_resume_wakes_consumer( self ):
        """Resume a paused job — consumer wakes and processes it."""
        todo_queue = MockTodoQueue()
        processed = []
        thread = self._start_consumer( todo_queue, processed )

        job = MockSchedulableJob( "resume-1", paused=True )
        todo_queue.push_with_notify( job )
        time.sleep( 0.2 )
        assert "resume-1" not in processed  # Paused

        # Resume
        job.paused = False
        with todo_queue.condition:
            todo_queue.condition.notify()
        time.sleep( 0.3 )

        assert "resume-1" in processed

        todo_queue.shutdown()
        thread.join( timeout=1.0 )
