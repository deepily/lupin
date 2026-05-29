"""
Deep Research background job for queue-based execution.

Wraps the existing Deep Research CLI functionality for execution
within the COSA queue system. Enables users to submit research
queries via the API and receive results asynchronously.

Example:
    job = DeepResearchJob(
        query      = "Compare React vs Vue frameworks",
        user_id    = "user123",
        user_email = "user@example.com",
        session_id = "wise-penguin",
        budget     = 2.00,
        debug      = True
    )
    result = job.do_all()  # Runs research and returns conversational answer
"""

import asyncio
import time
from datetime import datetime
from typing import Optional

import cosa.utils.util as cu
from cosa.agents.agentic_job_base import AgenticJobBase
from cosa.agents.deep_research.cost_tracker import SessionSummary
from cosa.rest.job_state import JobState


class DeepResearchJob( AgenticJobBase ):
    """
    Background job for Deep Research execution.

    Runs multi-minute research with web search, synthesis, and report generation.
    Sends progress notifications via cosa-voice and completion notification
    with report link.

    Attributes:
        query: The research query to investigate
        budget: Maximum budget in USD (None = unlimited)
        lead_model: Model for lead agent (None = use default)
        report_path: Path to generated report (set after completion)
        abstract: Report abstract (set after completion)
        cost_summary: Execution cost summary (set after completion)
    """

    JOB_TYPE   = "deep_research"
    JOB_PREFIX = "dr"

    def __init__(
        self,
        query: str,
        user_id: str,
        user_email: str,
        session_id: str,
        budget: Optional[ float ] = None,
        lead_model: Optional[ str ] = None,
        no_confirm: bool = True,  # Default to auto-approve in queue mode
        dry_run: bool = False,
        force_failure_mode: Optional[ str ] = None,
        audience: Optional[ str ] = None,
        audience_context: Optional[ str ] = None,
        debug: bool = False,
        verbose: bool = False
    ) -> None:
        """
        Initialize a Deep Research job.

        Requires:
            - query is a non-empty string
            - user_id is a valid system ID
            - user_email is a valid email address
            - session_id is a WebSocket session ID

        Ensures:
            - Job ID generated with "dr-" prefix
            - All parameters stored for execution

        Args:
            query: The research query to investigate
            user_id: System ID of the job owner
            user_email: Email address for report storage
            session_id: WebSocket session for notifications
            budget: Maximum budget in USD (None = unlimited)
            lead_model: Model for lead agent (None = use default)
            no_confirm: Skip confirmation prompts (default True for queue)
            dry_run: Simulate execution without API calls
            audience: Target audience level (beginner/general/expert/academic)
            audience_context: Custom audience description
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

        # Research parameters
        self.query              = query
        self.budget             = budget
        self.lead_model         = lead_model
        self.no_confirm         = no_confirm
        self.dry_run            = dry_run
        self.force_failure_mode = force_failure_mode
        self.audience           = audience
        self.audience_context   = audience_context

        # Results (populated after execution)
        self.report_path  = None
        self.abstract     = None
        self.cost_summary = None
        self.report       = None

    @property
    def last_question_asked( self ) -> str:
        """
        Display string for queue UI.

        Returns full query with [Deep Research] prefix.
        JS header truncates independently via truncateText().

        Returns:
            str: Human-readable job description
        """
        return f"[Deep Research] {self.query}"

    def do_all( self ) -> str:
        """
        Execute deep research and return conversational answer.

        This is the main entry point called by RunningFifoQueue.
        Bridges to the async _execute() method via asyncio.run().

        Returns:
            str: Conversational answer summarizing research results
        """
        if self.debug:
            print( f"[DeepResearchJob] Starting do_all() for: {self.query[ :50 ]}..." )

        self.state      = JobState.RUNNING
        self.started_at = cu.get_current_datetime_iso()

        try:
            result = asyncio.run( self._execute() )

            # Check if cancellation was requested during execution
            if self._cancel_requested:
                self.state                 = JobState.CANCELLED
                self.completed_at          = cu.get_current_datetime_iso()
                self.error                 = "Cancelled by user request"
                self.answer_conversational = result or "Research was cancelled by the user."
                if self.debug:
                    print( f"[DeepResearchJob] Cancelled by user request" )
                return self.answer_conversational

            self.state        = JobState.COMPLETED
            self.completed_at = cu.get_current_datetime_iso()
            self.result       = result
            self.answer_conversational = result

            if self.debug:
                duration = self.get_execution_duration_seconds()
                print( f"[DeepResearchJob] Completed in {duration:.1f}s" )

            return result

        except Exception as e:
            import traceback
            tb_str = traceback.format_exc()

            self.state        = JobState.FAILED
            self.completed_at = cu.get_current_datetime_iso()
            self.error        = f"{e}\n\n{tb_str}"
            self.answer_conversational = f"Research failed: {str( e )}"

            print( f"[DeepResearchJob] Failed: {e}" )
            print( tb_str )

            # Re-raise so the agentic-pool Future captures the exception
            # (Future.exception() is the canonical signal). Pre-cleanup this
            # method swallowed and returned the error string, forcing the
            # pool callback's defensive FAILED-state branch to catch it.
            # Backlog item 5 (2026-04-29): re-raise is the architectural fix.
            raise

    async def _execute( self ) -> str:
        """
        Internal async research execution.

        Uses the existing Deep Research CLI functions to run research.
        Handles configuration, execution, abstract generation, and report saving.
        When dry_run=True, sends breadcrumb notifications and returns mock results.

        Returns:
            str: Conversational summary of research results
        """
        from cosa.agents.deep_research import voice_io, cosa_interface

        # Re-establish core voice_io binding (import-order race: last configure() wins)
        voice_io.reconfigure()

        # Handle dry-run mode with breadcrumb notifications
        if self.dry_run:
            return await self._execute_dry_run( voice_io, cosa_interface )

        # Import research components
        from cosa.agents.deep_research.config import ResearchConfig
        from cosa.agents.deep_research.cost_tracker import CostTracker, BudgetExceededError
        from cosa.agents.deep_research.cli import (
            run_research,
            generate_abstract_for_cli,
            save_report_with_frontmatter,
        )
        from cosa.config.configuration_manager import ConfigurationManager
        from cosa.memory.gister import Gister

        # Initialize configuration
        config_mgr = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )

        # Get storage configuration
        storage_backend = config_mgr.get( "deep research storage backend", default="local" )
        gcs_bucket      = config_mgr.get( "deep research gcs bucket", default=None )
        output_dir      = config_mgr.get( "deep research output directory", default="/io/deep-research" )

        # Build full output path
        import cosa.utils.util as cu
        if not output_dir.startswith( "/" ):
            output_dir = cu.get_project_root() + "/" + output_dir
        elif not output_dir.startswith( cu.get_project_root() ):
            output_dir = cu.get_project_root() + output_dir

        # Generate session_name from query using Gister
        gister = Gister( debug=self.debug )
        session_name = gister.get_gist( self.query, prompt_key="prompt template for deep research session name" )
        session_name = session_name.lower().strip()
        if not session_name:
            session_name = "general research query"

        # Derive semantic_topic from session_name
        semantic_topic = session_name.replace( " ", "-" )

        # Set sender_id, target_user, and session_name for notifications.
        # Module globals are mutated for backward compatibility (CLI path reads
        # them); ContextVars are set for per-task isolation in the agentic pool
        # so concurrent DR jobs don't leak each other's sender_id.
        # See: src/cosa/agents/utils/agent_notification_dispatcher.py contextvars
        per_job_sender_id    = cosa_interface._get_sender_id( suffix=self.base_id )
        cosa_interface.SENDER_ID    = per_job_sender_id
        cosa_interface.TARGET_USER  = self.user_email
        cosa_interface.SESSION_NAME = session_name
        cosa_interface.set_dispatch_context(
            sender_id    = per_job_sender_id,
            target_user  = self.user_email,
            session_name = session_name,
        )

        # Set job_id for auto-injection into all downstream notify() calls
        voice_io.set_job_id( self.id_hash )

        if self.debug:
            print( f"[DeepResearchJob] Session name: {session_name}" )
            print( f"[DeepResearchJob] Semantic topic: {semantic_topic}" )
            print( f"[DeepResearchJob] Storage backend: {storage_backend}" )

        try:
            # Notify start (with job_id and queue_name for job card routing)
            await voice_io.notify(
                f"Starting deep research on: {self.query[ :80 ]}",
                priority="medium",
                job_id=self.id_hash,
                queue_name="run"
            )

            # Create research configuration from INI
            config = ResearchConfig.from_config( config_mgr, debug=self.debug )

            # Job args override INI values
            if self.lead_model:
                config.lead_model = self.lead_model
            if self.audience:
                config.audience = self.audience
            if self.audience_context:
                config.audience_context = self.audience_context

            # Create cost tracker
            cost_tracker = CostTracker(
                session_id       = f"research-{self.user_id}-{int( time.time() )}",
                budget_limit_usd = self.budget,
                debug            = self.debug,
            )

            # Run the research (with cancellation callback)
            cancel_check = lambda: self._cancel_requested
            report = await run_research(
                query        = self.query,
                config       = config,
                cost_tracker = cost_tracker,
                no_confirm   = self.no_confirm,
                cancel_check = cancel_check,
                debug        = self.debug,
                verbose      = self.verbose
            )

            if report is None:
                await voice_io.notify( "Research was cancelled.", priority="medium", job_id=self.id_hash, queue_name="run" )
                return "Research was cancelled by the user."

            self.report = report

            # Generate abstract
            self.abstract = await generate_abstract_for_cli(
                report       = report,
                config       = config,
                cost_tracker = cost_tracker,
                debug        = self.debug
            )

            # Save report with frontmatter
            self.report_path = save_report_with_frontmatter(
                report          = report,
                query           = self.query,
                abstract        = self.abstract,
                semantic_topic  = semantic_topic,
                session_id      = self.id_hash,
                cost_tracker    = cost_tracker,
                config          = config,
                output_dir      = output_dir,
                user_email      = self.user_email,
                storage_backend = storage_backend,
                gcs_bucket      = gcs_bucket,
                debug           = self.debug
            )

            # Store artifacts
            self.artifacts[ "report_path" ] = self.report_path
            self.artifacts[ "abstract" ]    = self.abstract

            # Get cost summary and store in artifacts for persistence
            self.cost_summary = cost_tracker.get_summary()
            from dataclasses import asdict
            self.artifacts[ "cost_summary" ] = asdict( self.cost_summary )

            # Format completion message (SessionSummary is a dataclass)
            duration = self.cost_summary.duration_seconds
            cost     = self.cost_summary.total_cost_usd
            tokens   = self.cost_summary.total_input_tokens + self.cost_summary.total_output_tokens

            completion_abstract = f"""**Research Complete!**

**Abstract**: {self.abstract}

**Report**: {self.report_path}

**Stats**: ${cost:.4f} | {tokens:,} tokens | {duration:.1f}s"""

            # Notify completion (with job_id and queue_name for job card routing)
            await voice_io.notify(
                f"Research complete! Cost: ${cost:.4f}",
                priority="medium",
                abstract=completion_abstract,
                job_id=self.id_hash,
                queue_name="run"
            )

            # Return conversational answer
            return f"Research complete. {self.abstract} The full report is available at: {self.report_path}"

        except BudgetExceededError as e:
            await voice_io.notify(
                f"Research stopped: Budget exceeded. ${e.current_cost:.2f} spent of ${e.budget_limit:.2f} limit.",
                priority="high",
                job_id=self.id_hash,
                queue_name="run"
            )
            raise

        except Exception as e:
            await voice_io.notify(
                f"Research error: {str( e )[ :100 ]}",
                priority="urgent",
                job_id=self.id_hash,
                queue_name="run"
            )
            raise

        finally:
            voice_io.clear_job_id()

    async def _execute_dry_run( self, voice_io, cosa_interface ) -> str:
        """
        Execute dry-run mode with breadcrumb notifications.

        Simulates the research workflow without making API calls.
        Sends low-priority notifications at each phase and returns mock results.

        Args:
            voice_io: Voice I/O module for notifications
            cosa_interface: COSA interface module for sender ID

        Returns:
            str: Mock conversational summary
        """
        import asyncio

        # Set sender_id and target_user for notifications. Module globals
        # mutated for CLI back-compat; ContextVars set for per-task isolation
        # in the agentic pool (concurrent DR jobs no longer share sender_id).
        per_job_sender_id           = cosa_interface._get_sender_id( suffix=self.base_id )
        cosa_interface.SENDER_ID    = per_job_sender_id
        cosa_interface.TARGET_USER  = self.user_email
        cosa_interface.set_dispatch_context(
            sender_id    = per_job_sender_id,
            target_user  = self.user_email,
        )

        if self.debug:
            print( f"[DeepResearchJob] DRY RUN MODE for: {self.query[ :50 ]}..." )

        # Breadcrumb: Starting (with job_id and queue_name for job card routing)
        await voice_io.notify( f"🧪 Dry run: Starting research simulation", priority="low", job_id=self.id_hash, queue_name="run" )
        await asyncio.sleep( 1.0 )

        # Breadcrumb: Query clarification
        await voice_io.notify( "🧪 Dry run: skipping query clarification", priority="low", job_id=self.id_hash, queue_name="run" )
        await asyncio.sleep( 1.0 )

        # Breadcrumb: Research planning
        await voice_io.notify( "🧪 Dry run: skipping research planning", priority="low", job_id=self.id_hash, queue_name="run" )
        await asyncio.sleep( 1.0 )

        # Breadcrumb: Subquery research
        await voice_io.notify( "🧪 Dry run: skipping subquery research (5 queries)", priority="low", job_id=self.id_hash, queue_name="run" )
        await asyncio.sleep( 1.0 )

        # Breadcrumb: Report synthesis
        await voice_io.notify( "🧪 Dry run: skipping report synthesis", priority="low", job_id=self.id_hash, queue_name="run" )
        await asyncio.sleep( 1.0 )

        # Breadcrumb: Report write
        await voice_io.notify( "🧪 Dry run: skipping report write to disk", priority="low", job_id=self.id_hash, queue_name="run" )
        await asyncio.sleep( 1.0 )

        # Set mock results
        self.report_path  = f"/io/deep-research/{self.user_email}/dry-run-{self.id_hash}/report.md"
        self.abstract     = "This is a mock abstract generated during dry-run mode. No actual research was performed."
        self.report       = "# Mock Research Report\n\nThis report was generated in dry-run mode."

        # Store mock artifacts
        self.artifacts[ "report_path" ] = self.report_path
        self.artifacts[ "abstract" ]    = self.abstract

        # Mock cost summary - uses SessionSummary dataclass for proper JSON serialization
        self.cost_summary = SessionSummary(
            duration_seconds    = 6.0,
            total_cost_usd      = 0.0,
            total_input_tokens  = 0,
            total_output_tokens = 0,
        )
        from dataclasses import asdict
        self.artifacts[ "cost_summary" ] = asdict( self.cost_summary )

        # Phase 6 repair loop hook: deliberately fail the dry-run to exercise
        # the dead-queue watchdog + BFE auto-fix pipeline.
        if self.force_failure_mode:
            await self._raise_forced_failure( voice_io )

        completion_abstract = f"""**🧪 Dry Run Complete!**

**Abstract**: {self.abstract}

**Report**: {self.report_path} (mock - not actually created)

**Stats**: $0.00 | 0 tokens | 6.0s (simulated)"""

        # Notify completion (with job_id and queue_name for job card routing)
        await voice_io.notify(
            "🧪 Dry run complete! No cost incurred.",
            priority="medium",
            abstract=completion_abstract,
            job_id=self.id_hash,
            queue_name="run"
        )

        return "Dry run complete. Research simulation finished."


def quick_smoke_test():
    """
    Quick smoke test for DeepResearchJob.
    """
    import cosa.utils.util as cu

    cu.print_banner( "DeepResearchJob Smoke Test", prepend_nl=True )

    try:
        # Test 1: Import
        print( "Testing module import..." )
        from cosa.agents.deep_research.job import DeepResearchJob
        print( "✓ Module imported successfully" )

        # Test 2: Instantiation
        print( "Testing job instantiation..." )
        job = DeepResearchJob(
            query      = "test query for smoke test",
            user_id    = "user123",
            user_email = "test@test.com",
            session_id = "session456",
            budget     = 1.00,
            debug      = True
        )
        print( f"✓ Job created with id: {job.id_hash}" )

        # Test 3: ID format
        print( "Testing ID format..." )
        assert job.id_hash.startswith( "dr-" ), "ID should start with dr-"
        print( f"✓ ID format correct: {job.id_hash}" )

        # Test 4: last_question_asked
        print( "Testing last_question_asked..." )
        lqa = job.last_question_asked
        assert "[Deep Research]" in lqa
        print( f"✓ last_question_asked: {lqa}" )

        # Test 5: is_cacheable
        print( "Testing is_cacheable property..." )
        assert job.is_cacheable == False
        print( "✓ is_cacheable correctly returns False" )

        # Test 6: Check attributes
        print( "Testing job attributes..." )
        assert job.query == "test query for smoke test"
        assert job.budget == 1.00
        assert job.user_email == "test@test.com"
        assert job.state == JobState.PENDING
        print( "✓ All attributes set correctly" )

        # Test 7: Check JOB_TYPE and JOB_PREFIX
        print( "Testing class constants..." )
        assert DeepResearchJob.JOB_TYPE == "deep_research"
        assert DeepResearchJob.JOB_PREFIX == "dr"
        print( "✓ Class constants correct" )

        # Note: We don't test do_all() here as it requires API keys and network
        print( "\n⚠ Note: do_all() not tested (requires API keys)" )

        print( "\n✓ Smoke test completed successfully" )

    except Exception as e:
        print( f"\n✗ Smoke test failed: {e}" )
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    quick_smoke_test()
