"""
SWE Team background job for queue-based execution.

Wraps the SWE Team orchestrator for execution within the COSA queue
system. Enables users to submit engineering tasks via the API and
receive results asynchronously.

Example:
    job = SweTeamJob(
        task       = "Add health check endpoint",
        user_id    = "user123",
        user_email = "user@example.com",
        session_id = "wise-penguin",
        dry_run    = True,
        debug      = True
    )
    result = job.do_all()  # Runs SWE Team and returns conversational answer
"""

import asyncio
import uuid
from datetime import datetime
from typing import Optional

import cosa.utils.util as cu

from cosa.agents.agentic_job_base import AgenticJobBase
from cosa.rest.job_state import JobState


class SweTeamJob( AgenticJobBase ):
    """
    Background job for SWE Team multi-agent execution.

    Runs multi-minute engineering tasks with task decomposition,
    coder delegation, and test verification. Sends progress
    notifications via cosa-voice.

    Attributes:
        task: The engineering task to accomplish
        dry_run: Simulate execution without API calls
        lead_model: Model for lead agent (None = use default)
        worker_model: Model for worker agents (None = use default)
        budget: Maximum budget in USD (None = use default)
        timeout: Wall-clock timeout in seconds (None = use default)
        cost_summary: Execution cost summary (set after completion)
    """

    JOB_TYPE   = "swe_team"
    JOB_PREFIX = "swe"

    # Phase labels for dry-run simulation loop
    DRY_RUN_PHASE_LABELS = [
        "Starting SWE Team simulation",
        "Analyzing task requirements",
        "Decomposing task into subtasks",
        "Planning implementation strategy",
        "Delegating subtask 1 to coder agent",
        "Verifying coder output with tester agent",
        "Delegating subtask 2 to coder agent",
        "Running integration tests",
        "Reviewing implementation quality",
        "Generating final summary",
    ]

    # Questions per phase for realistic proxy decision generation
    # Each maps to a phase index; questions exercise the classifier pipeline
    DRY_RUN_PHASE_QUESTIONS = [
        None,  # Phase 0: no decision needed at start
        None,  # Phase 1: analysis has no proxy question
        {
            "question"  : "Should I create a new API endpoint for this subtask?",
            "sender_id" : "swe.lead@lupin.deepily.ai",
        },
        {
            "question"  : "Should I refactor the existing module to accommodate the new design?",
            "sender_id" : "swe.lead@lupin.deepily.ai",
        },
        {
            "question"  : "Can I install the pydantic-settings package as a new dependency?",
            "sender_id" : "swe.coder@lupin.deepily.ai",
        },
        {
            "question"  : "Run the unit test suite to verify the implementation?",
            "sender_id" : "swe.tester@lupin.deepily.ai",
        },
        {
            "question"  : "Should I delete the old temporary build artifacts from the output directory?",
            "sender_id" : "swe.coder@lupin.deepily.ai",
        },
        {
            "question"  : "Run integration tests before merging the changes?",
            "sender_id" : "swe.tester@lupin.deepily.ai",
        },
        None,  # Phase 8: review has no proxy question
        {
            "question"  : "Deploy the completed changes to the staging environment?",
            "sender_id" : "swe.lead@lupin.deepily.ai",
        },
    ]

    def __init__(
        self,
        task,
        user_id,
        user_email,
        session_id,
        dry_run=False,
        dry_run_phases=10,
        dry_run_delay=1.5,
        lead_model=None,
        worker_model=None,
        budget=None,
        timeout=None,
        trust_mode=None,
        debug=False,
        verbose=False
    ):
        """
        Initialize a SWE Team job.

        Requires:
            - task is a non-empty string
            - user_id is a valid system ID
            - user_email is a valid email address
            - session_id is a WebSocket session ID

        Ensures:
            - Job ID generated with "swe-" prefix
            - All parameters stored for execution

        Args:
            task: The engineering task description
            user_id: System ID of the job owner
            user_email: Email address for notifications
            session_id: WebSocket session for notifications
            dry_run: Simulate execution without API calls
            dry_run_phases: Number of simulation phases (default 10)
            dry_run_delay: Seconds to sleep per phase (default 1.5)
            lead_model: Model for lead agent (None = use default)
            worker_model: Model for worker agents (None = use default)
            budget: Maximum budget in USD (None = use default)
            timeout: Wall-clock timeout in seconds (None = use default)
            trust_mode: Override trust mode (None = use server default from INI)
            debug: Enable debug output
            verbose: Enable verbose output
        """
        super().__init__(
            user_id    = user_id,
            user_email = user_email,
            session_id = session_id,
            debug      = debug,
            verbose    = verbose
        )

        # Task parameters
        self.task           = task
        self.dry_run        = dry_run
        self.dry_run_phases = dry_run_phases
        self.dry_run_delay  = dry_run_delay
        self.lead_model     = lead_model
        self.worker_model   = worker_model
        self.budget         = budget
        self.timeout        = timeout

        # Per-job trust mode override (None = use server default from INI)
        self._trust_mode_override = trust_mode

        # Live orchestrator reference (set during _execute, cleared after)
        # Enables hot-reload of trust mode via REST endpoint
        self._orchestrator = None

        # Results (populated after execution)
        self.cost_summary = None

    @property
    def last_question_asked( self ):
        """
        Display string for queue UI.

        Returns truncated task with [SWE Team] prefix.

        Returns:
            str: Human-readable job description
        """
        truncated = self.task[ :50 ] + "..." if len( self.task ) > 50 else self.task
        return f"[SWE Team] {truncated}"

    def do_all( self ):
        """
        Execute SWE Team task and return conversational answer.

        This is the main entry point called by RunningFifoQueue.
        Bridges to the async _execute() method via asyncio.run().

        Returns:
            str: Conversational answer summarizing results
        """
        if self.debug:
            print( f"[SweTeamJob] Starting do_all() for: {self.task[ :50 ]}..." )

        self.state      = JobState.RUNNING
        self.started_at = cu.get_current_datetime_iso()

        try:
            result = asyncio.run( self._execute() )

            self.state        = JobState.COMPLETED
            self.completed_at = cu.get_current_datetime_iso()
            self.result       = result
            self.answer_conversational = result

            if self.debug:
                duration = self.get_execution_duration_seconds()
                print( f"[SweTeamJob] Completed in {duration:.1f}s" )

            return result

        except Exception as e:
            self.state        = JobState.FAILED
            self.completed_at = cu.get_current_datetime_iso()
            self.error        = str( e )
            self.answer_conversational = f"SWE Team task failed: {str( e )}"

            if self.debug:
                print( f"[SweTeamJob] Failed: {e}" )
                import traceback
                traceback.print_exc()

            # Re-raise so the agentic-pool Future captures the exception.
            # Backlog item 5 (2026-04-29): canonical Future contract.
            raise

    async def _execute( self ):
        """
        Internal async SWE Team execution.

        When dry_run=True, sends breadcrumb notifications and returns mock results.
        When live, delegates to SweTeamOrchestrator.

        Returns:
            str: Conversational summary of results
        """
        from cosa.agents.swe_team import voice_io

        # Re-establish core voice_io binding (import-order race: last configure() wins)
        voice_io.reconfigure()

        # Handle dry-run mode with breadcrumb notifications
        if self.dry_run:
            return await self._execute_dry_run( voice_io )

        # Set SESSION_ID so sender_id includes job hash suffix for routing
        from cosa.agents.swe_team import cosa_interface
        cosa_interface.SESSION_ID   = self.id_hash
        cosa_interface.TARGET_USER  = self.user_email

        # Set job_id for auto-injection into all notify() calls
        voice_io.set_job_id( self.id_hash )

        # Live execution: build config from INI and delegate to orchestrator
        from cosa.agents.swe_team.config import SweTeamConfig
        from cosa.agents.swe_team.orchestrator import SweTeamOrchestrator
        from cosa.config.configuration_manager import ConfigurationManager

        config_mgr = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )
        config = SweTeamConfig.from_config( config_mgr, debug=self.debug )
        config.dry_run = False

        # Per-job overrides take priority over INI values
        if self._trust_mode_override:
            config.trust_mode = self._trust_mode_override
        if self.lead_model:
            config.lead_model = self.lead_model
        if self.worker_model:
            config.worker_model = self.worker_model
        if self.budget is not None:
            config.budget_usd = self.budget
        if self.timeout is not None:
            config.wall_clock_timeout_secs = self.timeout

        orchestrator = SweTeamOrchestrator(
            task_description = self.task,
            config           = config,
            session_id       = self.id_hash,
            job_id           = self.id_hash,
            debug            = self.debug,
            verbose          = self.verbose
        )

        # Expose for hot-reload via run queue (Phase 8)
        self._orchestrator = orchestrator

        # Start notification client for user-initiated messages (Approach D)
        notification_client = None
        if config.enable_user_messages:
            notification_client = self._start_notification_client( orchestrator )

        try:
            result = await orchestrator.run()

            if result is None:
                return "SWE Team task failed or was cancelled."

            return result

        finally:
            # Clear job_id to prevent leaking to subsequent jobs
            voice_io.clear_job_id()

            # Clear orchestrator reference after execution
            self._orchestrator = None

            # Always clean up notification client
            if notification_client:
                notification_client.stop_sync()
                if self.debug:
                    print( f"[SweTeamJob] Notification client stopped for {self.id_hash}" )

    def _start_notification_client( self, orchestrator ):
        """
        Create and start an OrchestratorNotificationClient.

        Shares the orchestrator's _user_messages queue and _urgent_interrupt
        event so user messages flow from WebSocket → queue → orchestrator.

        Requires:
            - orchestrator has _user_messages and _urgent_interrupt attributes
            - self.user_email is set

        Ensures:
            - Returns started client, or None on failure
            - Client runs in a daemon thread
            - Never raises (logs warning on failure)

        Args:
            orchestrator: SweTeamOrchestrator instance

        Returns:
            OrchestratorNotificationClient or None
        """
        try:
            from cosa.agents.swe_team.notification_client import OrchestratorNotificationClient

            client = OrchestratorNotificationClient(
                user_email    = self.user_email,
                job_id        = self.id_hash,
                message_queue = orchestrator._user_messages,
                urgent_event  = orchestrator._urgent_interrupt,
                debug         = self.debug,
                verbose       = self.verbose,
            )
            client.start()

            if self.debug:
                print( f"[SweTeamJob] Notification client started for {self.id_hash}" )

            return client

        except Exception as e:
            print( f"[SweTeamJob] Warning: Failed to start notification client: {e}" )
            return None

    async def _execute_dry_run( self, voice_io ):
        """
        Execute dry-run mode with breadcrumb notifications.

        Simulates the SWE Team workflow without making API calls.
        Loops through DRY_RUN_PHASE_LABELS with configurable phase count
        and delay, sending low-priority notifications at each phase.

        Requires:
            - voice_io is the voice I/O module
            - self.dry_run_phases > 0
            - self.dry_run_delay >= 0

        Ensures:
            - Runs min( dry_run_phases, len( DRY_RUN_PHASE_LABELS ) ) phases
            - Each phase sleeps for dry_run_delay seconds
            - Sets self.cost_summary with simulated metrics

        Args:
            voice_io: Voice I/O module for notifications

        Returns:
            str: Mock conversational summary
        """
        if self.debug:
            print( f"[SweTeamJob] DRY RUN MODE for: {self.task[ :50 ]}..." )
            print( f"[SweTeamJob] Phases: {self.dry_run_phases}, delay: {self.dry_run_delay}s" )

        # Set SESSION_ID so sender_id includes job hash suffix for routing
        from cosa.agents.swe_team import cosa_interface
        cosa_interface.SESSION_ID   = self.id_hash
        cosa_interface.TARGET_USER  = self.user_email

        # Loop through simulation phases
        num_phases = min( self.dry_run_phases, len( self.DRY_RUN_PHASE_LABELS ) )
        for i in range( num_phases ):
            label = self.DRY_RUN_PHASE_LABELS[ i ]
            await voice_io.notify(
                f"Dry run: {label}",
                priority="low",
                job_id=self.id_hash,
                queue_name="run"
            )
            await asyncio.sleep( self.dry_run_delay )

        # Mock cost summary with actual simulated duration
        total_duration = num_phases * self.dry_run_delay
        self.cost_summary = {
            "duration_seconds"    : total_duration,
            "total_cost_usd"      : 0.0,
            "total_input_tokens"  : 0,
            "total_output_tokens" : 0,
        }

        completion_abstract = f"""**Dry Run Complete!**

**Task**: {self.task[ :80 ]}

**Subtasks**: 1 simulated (0 real API calls)

**Stats**: $0.00 | 0 tokens | {total_duration:.1f}s (simulated)"""

        # Store artifacts so the queue picks them up at completion
        self.artifacts[ "abstract" ]     = completion_abstract
        self.artifacts[ "cost_summary" ] = self.cost_summary

        # Notify completion
        await voice_io.notify(
            "Dry run complete! No cost incurred.",
            priority="medium",
            abstract=completion_abstract,
            job_id=self.id_hash,
            queue_name="run"
        )

        # Generate proxy decisions via real classifier pipeline (no LLM cost)
        try:
            from cosa.rest.db.database import get_db
            from cosa.rest.db.repositories.proxy_decision_repository import ProxyDecisionRepository
            from cosa.agents.swe_team.proxy.engineering_classifier import EngineeringClassifier

            classifier      = EngineeringClassifier( debug=self.debug )
            decisions_count = 0

            with get_db() as db_session:
                repo = ProxyDecisionRepository( db_session )

                for i in range( num_phases ):
                    if i >= len( self.DRY_RUN_PHASE_QUESTIONS ):  # pragma: no cover - defensive list-drift guard, dead as written: num_phases is capped at len(DRY_RUN_PHASE_LABELS) and both phase lists are length 10, so i never reaches len(DRY_RUN_PHASE_QUESTIONS)
                        continue
                    phase_q = self.DRY_RUN_PHASE_QUESTIONS[ i ]
                    if phase_q is None:
                        continue

                    question  = phase_q[ "question" ]
                    sender_id = phase_q[ "sender_id" ]

                    # Run through real keyword classifier (zero LLM cost)
                    category, confidence = classifier.classify( question, sender_id=sender_id )

                    # Derive decision value from confidence
                    decision_value = "approved" if confidence >= 0.7 else "requires_review"

                    repo.log_decision(
                        notification_id       = str( uuid.uuid4() ),
                        domain                = "swe",
                        category              = category,
                        question              = question,
                        action                = "suggest",
                        decision_value        = decision_value,
                        sender_id             = f"{sender_id}#{self.id_hash}",
                        confidence            = confidence,
                        trust_level           = 1,
                        reason                = f"Dry-run classifier: {category} ({confidence:.2f})",
                        requires_ratification = True,
                        metadata_json         = {
                            "dry_run"    : True,
                            "job_id"     : self.id_hash,
                            "phase"      : i,
                            "classified" : True,
                        },
                        data_origin           = "synthetic_generated",
                    )
                    decisions_count += 1

                db_session.commit()

            if self.debug: print( f"[SweTeamJob] Inserted {decisions_count} classified proxy decisions for dry-run" )

        except Exception as e:
            if self.debug: print( f"[SweTeamJob] Warning: Proxy decision generation failed: {e}" )

        return "Dry run complete. SWE Team simulation finished."


def quick_smoke_test():
    """
    Quick smoke test for SweTeamJob.
    """
    import cosa.utils.util as cu

    cu.print_banner( "SweTeamJob Smoke Test", prepend_nl=True )

    try:
        # Test 1: Import
        print( "Testing module import..." )
        from cosa.agents.swe_team.job import SweTeamJob
        print( "✓ Module imported successfully" )

        # Test 2: Instantiation
        print( "Testing job instantiation..." )
        job = SweTeamJob(
            task       = "test task for smoke test",
            user_id    = "user123",
            user_email = "test@test.com",
            session_id = "session456",
            dry_run    = True,
            debug      = True
        )
        print( f"✓ Job created with id: {job.id_hash}" )

        # Test 3: ID format
        print( "Testing ID format..." )
        assert job.id_hash.startswith( "swe-" ), "ID should start with swe-"
        print( f"✓ ID format correct: {job.id_hash}" )

        # Test 4: last_question_asked
        print( "Testing last_question_asked..." )
        lqa = job.last_question_asked
        assert "[SWE Team]" in lqa
        print( f"✓ last_question_asked: {lqa}" )

        # Test 5: is_cacheable
        print( "Testing is_cacheable property..." )
        assert job.is_cacheable == False
        print( "✓ is_cacheable correctly returns False" )

        # Test 6: Check attributes
        print( "Testing job attributes..." )
        assert job.task == "test task for smoke test"
        assert job.dry_run == True
        assert job.user_email == "test@test.com"
        assert job.state == JobState.PENDING
        print( "✓ All attributes set correctly" )

        # Test 7: Check JOB_TYPE and JOB_PREFIX
        print( "Testing class constants..." )
        assert SweTeamJob.JOB_TYPE == "swe_team"
        assert SweTeamJob.JOB_PREFIX == "swe"
        print( "✓ Class constants correct" )

        # Note: We don't test do_all() here as it requires orchestrator setup
        print( "\n⚠ Note: do_all() not tested (requires orchestrator)" )

        print( "\n✓ Smoke test completed successfully" )

    except Exception as e:
        print( f"\n✗ Smoke test failed: {e}" )
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    quick_smoke_test()
