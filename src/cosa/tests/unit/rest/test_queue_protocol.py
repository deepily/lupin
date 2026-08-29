"""
Unit tests for the QueueableJob protocol (cosa.rest.queue_protocol).

Covers is_queueable_job() against a fully-conforming job, a job missing a
required method, and a plain object — to genuine 100% line + branch + function.

Zero external dependencies — the protocol is a structural (runtime_checkable)
interface; tests only construct in-memory stand-ins.
"""

import unittest

from cosa.rest.queue_protocol import QueueableJob, is_queueable_job
from cosa.rest.job_state import JobState


class _ConformingJob:
    """A minimal object exposing every QueueableJob member (data + methods)."""
    id_hash               = "job-1"
    push_counter          = 0
    user_id               = "u1"
    session_id            = "s1"
    routing_command       = "test"
    user_email            = "u1@example.com"
    run_date              = "2026-01-01"
    created_date          = "2026-01-01"
    started_at            = None
    completed_at          = None
    question              = "q"
    last_question_asked   = "q"
    answer                = "a"
    answer_conversational = "a"
    job_type              = "TestJob"
    is_cache_hit          = False
    state                 = JobState.PENDING
    error                 = None
    scheduled_at          = None
    monopolize            = False
    brake_terminal_claimed = False

    def do_all( self ): return "done"
    def code_ran_to_completion( self ): return True
    def formatter_ran_to_completion( self ): return True


class _MissingMethodJob:
    """Conforming data members but missing the required methods."""
    id_hash = "job-2"


class TestIsQueueableJob( unittest.TestCase ):
    """
    Validate the runtime_checkable protocol membership test.

    Ensures:
        - A fully-conforming object passes is_queueable_job
        - An object missing required methods fails
        - A plain object fails
    """

    def test_conforming_job_is_queueable( self ):
        self.assertTrue( is_queueable_job( _ConformingJob() ) )

    def test_missing_method_job_is_not_queueable( self ):
        self.assertFalse( is_queueable_job( _MissingMethodJob() ) )

    def test_plain_object_is_not_queueable( self ):
        self.assertFalse( is_queueable_job( object() ) )

    def test_protocol_is_runtime_checkable( self ):
        # runtime_checkable protocols carry the _is_runtime_protocol marker.
        self.assertTrue( getattr( QueueableJob, "_is_runtime_protocol", False ) )


def isolated_unit_test():
    """
    Run the queue_protocol unit tests in isolation.

    Ensures:
        - Returns (success, duration, message) for the smoke-runner harness
    """
    import time
    start_time = time.time()
    suite = unittest.TestLoader().loadTestsFromModule( __import__( __name__ ) )
    result = unittest.TextTestRunner( verbosity=2 ).run( suite )
    duration = time.time() - start_time
    success = result.wasSuccessful()
    message = f"{result.testsRun} run, {len( result.failures )} failed, {len( result.errors )} errors"
    return success, duration, message


if __name__ == "__main__":
    ok, secs, msg = isolated_unit_test()
    print( f"\n{'✅ PASS' if ok else '❌ FAIL'} queue_protocol tests in {secs:.3f}s — {msg}" )
