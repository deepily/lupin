"""
Mock agentic job for testing queue UI without inference costs.

Simulates a long-running job with configurable:
- Number of iterations (sleep/wake cycles)
- Duration between iterations
- Failure probability

All parameters can be randomized within configurable ranges.

Example:
    job = MockAgenticJob(
        user_id    = "user123",
        user_email = "test@example.com",
        session_id = "wise-penguin",
        fixed_iterations = 3,
        fixed_sleep      = 1.0,
        debug            = True
    )
    result = job.do_all()  # Runs mock phases, emits notifications
"""

import asyncio
import random
import time
from datetime import datetime
from typing import Optional, Tuple

from cosa.agents.agentic_job_base import AgenticJobBase
from cosa.rest.job_state import JobState


class MockAgenticJob( AgenticJobBase ):
    """
    Mock agentic job for testing queue UI without inference costs.

    Simulates a long-running job by sleeping between iterations and
    emitting progress notifications. Useful for:
    - Testing queue visualization without waiting for real jobs
    - Testing failure paths (dead queue)
    - Testing notification routing to job cards
    - Stress testing queue system with multiple concurrent jobs

    Attributes:
        iterations: Number of sleep/wake cycles
        sleep_seconds: Duration between iterations
        will_fail: Whether job will fail during execution
        fail_at_iteration: Which iteration to fail at (if will_fail)
    """

    JOB_TYPE   = "mock"
    JOB_PREFIX = "mock"

    # Simulated phase messages (mimics real job patterns)
    PHASE_MESSAGES = [
        "Initializing research context...",
        "Analyzing query parameters...",
        "Searching knowledge sources...",
        "Processing intermediate results...",
        "Synthesizing findings...",
        "Generating summary...",
        "Finalizing report...",
        "Performing quality checks...",
    ]

    def __init__(
        self,
        user_id: str,
        user_email: str,
        session_id: str,
        # Randomization ranges (min, max)
        iterations_range: Tuple[ int, int ] = ( 3, 8 ),
        sleep_range: Tuple[ float, float ] = ( 1.0, 5.0 ),
        failure_probability: float = 0.0,
        # Override with fixed values (None = use random)
        fixed_iterations: Optional[ int ] = None,
        fixed_sleep: Optional[ float ] = None,
        # Optional description for queue display
        description: Optional[ str ] = None,
        # Scheduling attributes (CJ Flow timed execution + monopolize)
        scheduled_at: str = None,
        monopolize: bool = False,
        debug: bool = False,
        verbose: bool = False
    ) -> None:
        """
        Initialize a mock agentic job.

        Requires:
            - user_id is a valid system ID
            - user_email is a valid email address
            - session_id is a WebSocket session ID
            - iterations_range[0] <= iterations_range[1]
            - sleep_range[0] <= sleep_range[1]
            - 0.0 <= failure_probability <= 1.0

        Ensures:
            - Job ID generated with "mock-" prefix
            - Parameters randomized within ranges (unless fixed)
            - Failure decision made at init time

        Args:
            user_id: System ID of the job owner
            user_email: Email address of the user
            session_id: WebSocket session ID for notifications
            iterations_range: (min, max) for random iteration count
            sleep_range: (min, max) seconds for random sleep duration
            failure_probability: 0.0 = never fail, 1.0 = always fail
            fixed_iterations: Override random iterations with fixed value
            fixed_sleep: Override random sleep with fixed value
            description: Custom description for queue display
            debug: Enable debug output
            verbose: Enable verbose output
        """
        super().__init__(
            user_id      = user_id,
            user_email   = user_email,
            session_id   = session_id,
            scheduled_at = scheduled_at,
            monopolize   = monopolize,
            debug        = debug,
            verbose      = verbose
        )

        # Store configuration for API response
        self.iterations_range     = iterations_range
        self.sleep_range          = sleep_range
        self.failure_probability  = failure_probability
        self.fixed_iterations     = fixed_iterations
        self.fixed_sleep          = fixed_sleep
        self.description          = description

        # Randomize parameters
        self._randomize_parameters()

        # Results (populated after execution)
        self.report_path  = None
        self.abstract     = None
        self.cost_summary = None

    def _randomize_parameters( self ) -> None:
        """
        Set random values within configured ranges.

        Called during __init__ to determine actual iteration count,
        sleep duration, and failure behavior.
        """
        # Iterations: random int in range or fixed
        if self.fixed_iterations is not None:
            self.iterations = self.fixed_iterations
        else:
            self.iterations = random.randint( *self.iterations_range )

        # Sleep duration: random float in range or fixed
        if self.fixed_sleep is not None:
            self.sleep_seconds = self.fixed_sleep
        else:
            self.sleep_seconds = random.uniform( *self.sleep_range )

        # Failure: roll dice once at init
        self.will_fail = random.random() < self.failure_probability

        # If failing, pick random iteration to fail at (not always at end)
        if self.will_fail:
            self.fail_at_iteration = random.randint( 1, self.iterations )
        else:
            self.fail_at_iteration = -1

    def _get_phase_message( self, iteration: int ) -> str:
        """
        Get phase message for given iteration, cycling through available messages.

        Args:
            iteration: Zero-based iteration index

        Returns:
            str: Phase message for this iteration
        """
        return self.PHASE_MESSAGES[ iteration % len( self.PHASE_MESSAGES ) ]

    def _create_mock_artifacts( self ) -> None:
        """
        Create fake artifacts that mimic DeepResearchJob output.

        Populates self.artifacts, self.abstract, self.report_path,
        and self.cost_summary with mock data for UI testing.
        """
        # Calculate actual duration
        if self.started_at and self.completed_at:
            start = datetime.fromisoformat( self.started_at )
            end   = datetime.fromisoformat( self.completed_at )
            duration = ( end - start ).total_seconds()
        else:
            duration = self.iterations * self.sleep_seconds

        # Mock report path
        self.report_path = f"/io/mock-reports/{self.id_hash}/report.md"

        # Mock abstract
        self.abstract = (
            f"Mock research completed successfully. "
            f"Simulated {self.iterations} phases over {duration:.1f} seconds. "
            f"This is a test job for UI development."
        )

        # Store in artifacts dict
        self.artifacts[ "report_path" ] = self.report_path
        self.artifacts[ "abstract" ]    = self.abstract

        # Mock cost summary (zero cost, but realistic structure)
        self.cost_summary = {
            "total_cost_usd"     : 0.0,
            "total_input_tokens" : random.randint( 1000, 5000 ),
            "total_output_tokens": random.randint( 500, 2000 ),
            "duration_seconds"   : duration
        }

    @property
    def last_question_asked( self ) -> str:
        """
        Display string for queue UI.

        Returns:
            str: Human-readable job description
        """
        if self.description:
            return f"[Mock] {self.description}"
        return f"[Mock] Test job with {self.iterations} phases"

    def do_all( self ) -> str:
        """
        Execute mock job and return conversational answer.

        This is the main entry point called by RunningFifoQueue.
        Bridges to the async _execute() method via asyncio.run().

        Returns:
            str: Conversational answer summarizing mock results
        """
        if self.debug:
            print( f"[MockAgenticJob] Starting do_all() - {self.iterations} iterations, {self.sleep_seconds:.1f}s each" )

        self.state      = JobState.RUNNING
        self.started_at = datetime.now().isoformat()

        try:
            result = asyncio.run( self._execute() )

            self.state        = JobState.COMPLETED
            self.completed_at = datetime.now().isoformat()
            self.result       = result
            self.answer_conversational = result

            # Create mock artifacts for done queue display
            self._create_mock_artifacts()

            if self.debug:
                duration = self.get_execution_duration_seconds()
                print( f"[MockAgenticJob] Completed in {duration:.1f}s" )

            return result

        except Exception as e:
            self.state        = JobState.FAILED
            self.completed_at = datetime.now().isoformat()
            self.error        = str( e )

            if self.debug:
                print( f"[MockAgenticJob] Failed: {e}" )

            # Return error message as conversational answer
            self.answer_conversational = f"Mock job failed: {str( e )}"
            return self.answer_conversational

    async def _execute( self ) -> str:
        """
        Internal async execution - sleep and emit notifications.

        Loops through iterations, sleeping and emitting progress notifications.
        Checks for failure condition at each iteration.

        Returns:
            str: Completion message

        Raises:
            RuntimeError: If failure triggered at configured iteration
        """
        estimated_duration = self.iterations * self.sleep_seconds

        # Notify start
        await self._send_notification(
            f"Starting mock job: {self.iterations} phases, ~{estimated_duration:.0f}s",
            priority="medium"
        )

        # Execute iterations
        for i in range( self.iterations ):
            # Check for failure
            if self.will_fail and ( i + 1 ) == self.fail_at_iteration:
                await self._send_notification(
                    f"Mock job failed at phase {i + 1}!",
                    priority="urgent"
                )
                raise RuntimeError( f"Simulated failure at iteration {i + 1} of {self.iterations}" )

            # Sleep
            await asyncio.sleep( self.sleep_seconds )

            # Get phase message
            phase_msg = self._get_phase_message( i )
            progress_pct = int( ( ( i + 1 ) / self.iterations ) * 100 )

            # Notify progress
            await self._send_notification(
                f"Phase {i + 1}/{self.iterations} ({progress_pct}%): {phase_msg}",
                priority="low"
            )

        # Notify completion
        await self._send_notification(
            f"Mock job complete! All {self.iterations} phases finished.",
            priority="medium"
        )

        return f"Mock job completed successfully. Processed {self.iterations} phases."

    async def _send_notification( self, message: str, priority: str = "low" ) -> None:
        """
        Send progress notification via cosa-voice.

        Includes job_id in notification for routing to job card activity log.

        Args:
            message: Notification message
            priority: Notification priority (low, medium, high, urgent)
        """
        try:
            from cosa.agents.deep_research import voice_io

            # Set job_id for notification routing
            await voice_io.notify(
                message,
                priority=priority,
                job_id=self.id_hash
            )

        except ImportError as e:
            if self.debug:
                print( f"[MockAgenticJob] Could not import voice_io: {e}" )
        except Exception as e:
            if self.debug:
                print( f"[MockAgenticJob] Notification error: {e}" )


def quick_smoke_test():
    """
    Quick smoke test for MockAgenticJob - validates basic functionality.
    """
    import cosa.utils.util as cu

    cu.print_banner( "MockAgenticJob Smoke Test", prepend_nl=True )

    try:
        # Test 1: Import
        print( "Testing module import..." )
        from cosa.agents.test_harness.mock_job import MockAgenticJob
        print( "✓ Module imported successfully" )

        # Test 2: Instantiation with defaults
        print( "Testing job instantiation with defaults..." )
        job = MockAgenticJob(
            user_id    = "user123",
            user_email = "test@example.com",
            session_id = "wise-penguin",
            debug      = True
        )
        print( f"✓ Job created with id: {job.id_hash}" )
        print( f"  - iterations: {job.iterations}" )
        print( f"  - sleep_seconds: {job.sleep_seconds:.2f}" )
        print( f"  - will_fail: {job.will_fail}" )

        # Test 3: ID format
        print( "Testing ID format..." )
        assert job.id_hash.startswith( "mock-" ), f"ID should start with mock-, got: {job.id_hash}"
        print( f"✓ ID format correct: {job.id_hash}" )

        # Test 4: Fixed parameters
        print( "Testing fixed parameters..." )
        fixed_job = MockAgenticJob(
            user_id          = "user456",
            user_email       = "test2@example.com",
            session_id       = "clever-dolphin",
            fixed_iterations = 5,
            fixed_sleep      = 0.1,
            debug            = True
        )
        assert fixed_job.iterations == 5, f"Expected 5 iterations, got {fixed_job.iterations}"
        assert fixed_job.sleep_seconds == 0.1, f"Expected 0.1s sleep, got {fixed_job.sleep_seconds}"
        print( f"✓ Fixed parameters work: {fixed_job.iterations} iterations, {fixed_job.sleep_seconds}s sleep" )

        # Test 5: last_question_asked
        print( "Testing last_question_asked..." )
        lqa = fixed_job.last_question_asked
        assert "[Mock]" in lqa
        print( f"✓ last_question_asked: {lqa}" )

        # Test 6: is_cacheable
        print( "Testing is_cacheable property..." )
        assert job.is_cacheable == False
        print( "✓ is_cacheable correctly returns False" )

        # Test 7: JOB_TYPE and JOB_PREFIX
        print( "Testing class constants..." )
        assert MockAgenticJob.JOB_TYPE == "mock"
        assert MockAgenticJob.JOB_PREFIX == "mock"
        print( "✓ Class constants correct" )

        # Test 8: Failure probability
        print( "Testing failure probability..." )
        failing_job = MockAgenticJob(
            user_id             = "user789",
            user_email          = "test3@example.com",
            session_id          = "wise-owl",
            failure_probability = 1.0,  # Always fail
            fixed_iterations    = 3,
            debug               = True
        )
        assert failing_job.will_fail == True
        assert 1 <= failing_job.fail_at_iteration <= 3
        print( f"✓ Failure configured: will fail at iteration {failing_job.fail_at_iteration}" )

        # Test 9: Quick execution (dry run without notifications)
        print( "Testing quick execution (2 iterations, 0.1s)..." )
        quick_job = MockAgenticJob(
            user_id          = "user-exec",
            user_email       = "exec@example.com",
            session_id       = "test-session",
            fixed_iterations = 2,
            fixed_sleep      = 0.1,
            debug            = True
        )

        # Execute without network (notifications will fail silently)
        start_time = time.time()
        result = quick_job.do_all()
        elapsed = time.time() - start_time

        assert quick_job.status == "completed", f"Expected completed, got {quick_job.status}"
        assert quick_job.artifacts.get( "report_path" ) is not None
        assert quick_job.abstract is not None
        assert elapsed >= 0.2, f"Expected >= 0.2s, got {elapsed:.2f}s"
        print( f"✓ Execution completed in {elapsed:.2f}s" )
        print( f"  - status: {quick_job.status}" )
        print( f"  - abstract: {quick_job.abstract[ :60 ]}..." )

        print( "\n✓ Smoke test completed successfully" )

    except Exception as e:
        print( f"\n✗ Smoke test failed: {e}" )
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    quick_smoke_test()
