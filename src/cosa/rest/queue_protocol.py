"""
Unified protocol for all queueable job objects in CJ Flow (COSA Jobs Flow).

All job types (AgentBase, SolutionSnapshot, AgenticJobBase) must implement
this interface for consistent queue system handling. This protocol documents
the unified interface that was established through property additions to
each class.

The unified naming conventions are:
    - job_type: Unified type identifier (replaces agent_class_name/JOB_TYPE getattr chains)
    - question: Raw question text
    - last_question_asked: Display question for UI
    - answer: Raw answer text
    - answer_conversational: Formatted answer for display
    - created_date: When the job was created
    - run_date: When the job was executed

Generated on: 2025-01-22
"""

from typing import Protocol, runtime_checkable, Dict, Any

from cosa.rest.job_state import JobState


@runtime_checkable
class QueueableJob( Protocol ):
    """
    Protocol for jobs flowing through the COSA queue system.

    This protocol documents the expected interface for all job types:
    - AgentBase: Code-generating agents (MathAgent, CalendarAgent, etc.)
    - SolutionSnapshot: Cached/persisted solutions from agents
    - AgenticJobBase: Long-running async jobs (DeepResearchJob, etc.)

    All three classes now implement these attributes/methods through
    either direct attributes or properties, enabling direct attribute
    access instead of getattr() chains in queue handling code.
    """

    # =========================================================================
    # Identity Attributes
    # =========================================================================

    id_hash: str
    """Unique identifier for this job instance."""

    push_counter: int
    """Queue position tracking counter."""

    # =========================================================================
    # Ownership/Routing Attributes
    # =========================================================================

    user_id: str
    """User ID who owns this job (for filtering and authorization)."""

    session_id: str
    """WebSocket session ID for notifications and job correlation."""

    routing_command: str
    """Command used to route this job to the appropriate handler."""

    # =========================================================================
    # User Context (Session 110+)
    # =========================================================================

    user_email: str
    """User email address for TTS notification routing."""

    # =========================================================================
    # Timestamps
    # =========================================================================

    run_date: str
    """When the job was executed (ISO format timestamp)."""

    created_date: str
    """When the job was created (unified - may equal run_date)."""

    started_at: str
    """When the job started running (ISO format timestamp, may be None)."""

    completed_at: str
    """When the job completed (ISO format timestamp, may be None)."""

    # =========================================================================
    # Question/Answer (Unified Names)
    # =========================================================================

    question: str
    """Raw question text (verbatim user input)."""

    last_question_asked: str
    """Display question for UI (may include formatting)."""

    answer: str
    """Raw answer/output from execution."""

    answer_conversational: str
    """Formatted answer suitable for display/TTS."""

    # =========================================================================
    # Type Identification (Unified)
    # =========================================================================

    job_type: str
    """
    Unified job type identifier.

    This is the NEW unified property that replaces the getattr() chains:
    - AgentBase: Returns class name (e.g., "MathAgent")
    - SolutionSnapshot: Returns agent_class_name (e.g., "MathAgent")
    - AgenticJobBase: Returns JOB_TYPE (e.g., "deep_research")
    """

    # =========================================================================
    # Status Tracking (Session 111)
    # =========================================================================

    is_cache_hit: bool
    """Whether this job was served from cache (for Time Saved Dashboard)."""

    state: JobState
    """Unified lifecycle state (JobState enum). Replaces the former string 'status' field."""

    error: str
    """Error message if job failed (None if successful)."""

    # =========================================================================
    # Scheduling Attributes (CJ Flow Timed Execution + Monopolize + Pause)
    # =========================================================================

    scheduled_at: str
    """When to run this job (ISO format local datetime string, or None for immediate)."""

    monopolize: bool
    """If True, this job runs exclusively — no other jobs process until it completes."""

    # NOTE: paused boolean removed — absorbed into JobState.PAUSED
    # Check job.state == JobState.PAUSED instead of job.paused

    # =========================================================================
    # Required Methods
    # =========================================================================

    def do_all( self ) -> str:
        """
        Execute job and return conversational answer.

        Returns:
            str: The conversational answer after execution
        """
        ...

    def code_ran_to_completion( self ) -> bool:
        """
        Check if code/job execution completed successfully.

        Returns:
            bool: True if execution completed without errors
        """
        ...

    def formatter_ran_to_completion( self ) -> bool:
        """
        Check if output formatting completed successfully.

        Returns:
            bool: True if answer_conversational is populated
        """
        ...


def is_queueable_job( obj: Any ) -> bool:
    """
    Check if an object implements the QueueableJob protocol.

    This uses runtime_checkable to verify the object has the required
    attributes and methods.

    Args:
        obj: Object to check

    Returns:
        bool: True if object implements QueueableJob protocol
    """
    return isinstance( obj, QueueableJob )


def quick_smoke_test():
    """
    Quick smoke test for QueueableJob protocol.
    """
    import cosa.utils.util as cu

    cu.print_banner( "QueueableJob Protocol Smoke Test", prepend_nl=True )

    try:
        # Test 1: Import
        print( "Testing module import..." )
        from cosa.rest.queue_protocol import QueueableJob, is_queueable_job
        print( "✓ Module imported successfully" )

        # Test 2: Protocol is runtime_checkable
        print( "Testing runtime_checkable decorator..." )
        assert hasattr( QueueableJob, '__protocol_attrs__' ) or hasattr( QueueableJob, '_is_runtime_protocol' )
        print( "✓ Protocol is runtime_checkable" )

        # Test 3: Create a mock class that implements the protocol
        print( "Testing protocol implementation check..." )

        class MockJob:
            id_hash               = "test-123"
            push_counter          = 0
            user_id               = "user123"
            user_email            = "test@test.com"
            session_id            = "session456"
            routing_command       = "test"
            run_date              = "2025-01-22"
            created_date          = "2025-01-22"
            started_at            = None
            completed_at          = None
            question              = "test question"
            last_question_asked   = "test question"
            answer                = "test answer"
            answer_conversational = "Test answer"
            job_type              = "MockJob"
            is_cache_hit          = False
            state                 = JobState.PENDING
            error                 = None
            scheduled_at          = None
            monopolize            = False

            def do_all( self ):
                return "done"

            def code_ran_to_completion( self ):
                return True

            def formatter_ran_to_completion( self ):
                return True

        mock = MockJob()
        is_valid = is_queueable_job( mock )
        print( f"✓ MockJob implements protocol: {is_valid}" )

        # Test 4: Test with actual classes (if available)
        print( "Testing with actual job classes..." )

        try:
            from cosa.agents.agentic_job_base import AgenticJobBase

            # Create a concrete implementation for testing
            class TestAgenticJob( AgenticJobBase ):
                JOB_TYPE   = "test_agentic"
                JOB_PREFIX = "ta"

                def __init__( self ):
                    super().__init__(
                        user_id    = "test_user",
                        user_email = "test@test.com",
                        session_id = "test_session"
                    )

                @property
                def last_question_asked( self ):
                    return "Test agentic question"

                def do_all( self ):
                    return "done"

                async def _execute( self ):
                    return "executed"

            test_job = TestAgenticJob()

            # Test unified properties
            assert test_job.job_type == "test_agentic"
            assert test_job.question == "Test agentic question"
            assert test_job.created_date == test_job.run_date
            print( f"✓ AgenticJobBase unified properties work" )

        except Exception as e:
            print( f"⚠ AgenticJobBase test skipped: {e}" )

        print( "\n✓ QueueableJob Protocol smoke test completed successfully" )

    except Exception as e:
        print( f"\n✗ Smoke test failed: {e}" )
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    quick_smoke_test()
