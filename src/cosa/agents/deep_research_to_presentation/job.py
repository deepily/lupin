"""
Deep Research to Presentation background job for queue-based execution.

Wraps the existing DeepResearchToPresentationAgent functionality for execution
within the COSA queue system. Enables users to submit chained research→presentation
workflows via the API and receive results asynchronously.

Example:
    job = DeepResearchToPresentationJob(
        query          = "State of AI safety in 2026",
        user_id        = "user123",
        user_email     = "user@example.com",
        session_id     = "wise-penguin",
        budget         = 3.00,
        debug          = True
    )
    result = job.do_all()  # Runs full pipeline and returns conversational answer
"""

import asyncio
from datetime import datetime
from typing import Optional

import cosa.utils.util as cu
from cosa.agents.agentic_job_base import AgenticJobBase
from cosa.rest.job_state import JobState


class DeepResearchToPresentationJob( AgenticJobBase ):
    """
    Background job for Deep Research → Presentation pipeline execution.

    Runs a chained workflow:
    1. Deep Research: Web search, synthesis, report generation
    2. Presentation Generation: Narrative analysis, slide outline, Marp rendering

    Sends progress notifications via cosa-voice and completion notification
    with links to all generated artifacts.

    Attributes:
        query: The research topic/question to investigate
        budget: Maximum budget in USD for Deep Research (None = unlimited)
        target_duration_minutes: Override presentation duration (None = use default)
        theme: Override presentation theme (None = use default)
        research_path: Path to generated research report (set after completion)
        yaml_path: Path to generated YAML intermediate (set after completion)
        marp_path: Path to generated Marp presentation (set after completion)
        cost_summary: Combined execution cost summary (set after completion)
    """

    JOB_TYPE   = "research_to_presentation"
    JOB_PREFIX = "rx"

    def __init__(
        self,
        query: str,
        user_id: str,
        user_email: str,
        session_id: str,
        budget: Optional[ float ] = None,
        target_duration_minutes: Optional[ int ] = None,
        theme: Optional[ str ] = None,
        lead_model: Optional[ str ] = None,
        dry_run: bool = False,
        audience: Optional[ str ] = None,
        audience_context: Optional[ str ] = None,
        debug: bool = False,
        verbose: bool = False
    ) -> None:
        """
        Initialize a Deep Research to Presentation job.

        Requires:
            - query is a non-empty string
            - user_id is a valid system ID
            - user_email is a valid email address
            - session_id is a WebSocket session ID

        Ensures:
            - Job ID generated with "rx-" prefix
            - All parameters stored for execution

        Args:
            query: The research topic/question to investigate
            user_id: System ID of the job owner
            user_email: Email address for output storage
            session_id: WebSocket session for notifications
            budget: Maximum budget in USD for Deep Research (None = unlimited)
            target_duration_minutes: Override presentation duration (None = use default)
            theme: Override presentation theme (None = use default)
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

        # Pipeline parameters
        self.query                   = query
        self.budget                  = budget
        self.target_duration_minutes = target_duration_minutes
        self.theme                   = theme
        self.lead_model              = lead_model
        self.dry_run                 = dry_run
        self.audience                = audience
        self.audience_context        = audience_context

        # Results (populated after execution)
        self.research_path = None
        self.yaml_path     = None
        self.marp_path     = None
        self.cost_summary  = None

    @property
    def last_question_asked( self ) -> str:
        """
        Display string for queue UI.

        Returns truncated query with [Research→Presentation] prefix.

        Returns:
            str: Human-readable job description
        """
        return f"[Research→Presentation] {self.query}"

    def do_all( self ) -> str:
        """
        Execute research→presentation pipeline and return conversational answer.

        This is the main entry point called by RunningFifoQueue.
        Bridges to the async _execute() method via asyncio.run().

        Returns:
            str: Conversational answer summarizing pipeline results
        """
        if self.debug:
            print( f"[DeepResearchToPresentationJob] Starting do_all() for: {self.query[ :50 ]}..." )

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
                print( f"[DeepResearchToPresentationJob] Completed in {duration:.1f}s" )

            return result

        except Exception as e:
            self.state        = JobState.FAILED
            self.completed_at = cu.get_current_datetime_iso()
            self.error        = str( e )
            self.answer_conversational = f"Research→Presentation pipeline failed: {str( e )}"

            if self.debug:
                print( f"[DeepResearchToPresentationJob] Failed: {e}" )
                import traceback
                traceback.print_exc()

            # Re-raise so the agentic-pool Future captures the exception.
            # Backlog item 5 (2026-04-29): canonical Future contract.
            raise

    async def _execute( self ) -> str:
        """
        Internal async pipeline execution.

        Uses the DeepResearchToPresentationAgent to run the full workflow.
        When dry_run=True, sends breadcrumb notifications and returns mock results.

        Returns:
            str: Conversational summary of pipeline results
        """
        from cosa.agents.deep_research import voice_io, cosa_interface

        # Handle dry-run mode with breadcrumb notifications
        if self.dry_run:
            return await self._execute_dry_run( voice_io, cosa_interface )

        # Import pipeline components
        from cosa.agents.deep_research_to_presentation.agent import DeepResearchToPresentationAgent
        from cosa.agents.deep_research_to_presentation.state import PipelineState

        # Set sender_id and target_user for notifications (use base_id to strip ::user_id scope suffix)
        cosa_interface.SENDER_ID   = cosa_interface._get_sender_id( suffix=self.base_id )
        cosa_interface.TARGET_USER = self.user_email

        # Set job_id for auto-injection into all downstream notify() calls
        voice_io.set_job_id( self.id_hash )

        if self.debug:
            print( f"[DeepResearchToPresentationJob] Query: {self.query[ :80 ]}..." )
            print( f"[DeepResearchToPresentationJob] Budget: ${self.budget}" if self.budget else "[DeepResearchToPresentationJob] Budget: unlimited" )

        try:
            # Notify start
            await voice_io.notify(
                f"Starting research→presentation pipeline: {self.query[ :60 ]}...",
                priority="medium",
                job_id=self.id_hash,
                queue_name="run"
            )

            # Create the chained agent
            agent = DeepResearchToPresentationAgent(
                query                   = self.query,
                user_email              = self.user_email,
                budget                  = self.budget,
                lead_model              = self.lead_model,
                audience                = self.audience,
                audience_context        = self.audience_context,
                target_duration_minutes = self.target_duration_minutes,
                theme                   = self.theme,
                cli_mode                = False,  # Voice-driven mode for queue
                debug                   = self.debug,
                verbose                 = self.verbose,
            )

            # Run the full pipeline
            result = await agent.run_async()

            # Check result state
            if result.state == PipelineState.CANCELLED:
                await voice_io.notify( "Pipeline was cancelled.", priority="medium", job_id=self.id_hash, queue_name="run" )
                return "Research→Presentation pipeline was cancelled by the user."

            if result.state == PipelineState.FAILED:
                error_msg = result.error or "Unknown error"
                await voice_io.notify( f"Pipeline failed: {error_msg[ :80 ]}", priority="urgent", job_id=self.id_hash, queue_name="run" )
                raise Exception( error_msg )

            # Store results
            self.research_path = result.research_path
            self.yaml_path     = result.yaml_path
            self.marp_path     = result.marp_path

            # Store artifacts
            self.artifacts[ "research_path" ]     = result.research_path
            self.artifacts[ "research_abstract" ] = result.research_abstract
            self.artifacts[ "yaml_path" ]         = result.yaml_path
            self.artifacts[ "marp_path" ]         = result.marp_path
            self.artifacts[ "slide_count" ]       = result.slide_count

            # Build cost summary
            self.cost_summary = {
                "dr_cost_usd"    : result.dr_cost,
                "pg_cost_usd"    : result.pg_cost,
                "total_cost_usd" : result.total_cost,
            }
            self.artifacts[ "cost_summary" ] = self.cost_summary

            # Return conversational answer
            return f"Pipeline complete! Research report and presentation generated. Total cost: ${result.total_cost:.4f}. Presentation: {self.marp_path}"

        finally:
            voice_io.clear_job_id()

    async def _execute_dry_run( self, voice_io, cosa_interface ) -> str:
        """
        Execute dry-run mode with breadcrumb notifications.

        Simulates the full research→presentation pipeline without making API calls.
        Sends low-priority notifications at each phase and returns mock results.

        Args:
            voice_io: Voice I/O module for notifications
            cosa_interface: COSA interface module for sender ID

        Returns:
            str: Mock conversational summary
        """
        import asyncio

        # Set sender_id and target_user for notifications (use base_id to strip ::user_id scope suffix)
        cosa_interface.SENDER_ID   = cosa_interface._get_sender_id( suffix=self.base_id )
        cosa_interface.TARGET_USER = self.user_email

        # Set job_id for auto-injection into all downstream notify() calls
        voice_io.set_job_id( self.id_hash )

        if self.debug:
            print( f"[DeepResearchToPresentationJob] DRY RUN MODE for: {self.query[ :50 ]}..." )

        # === Deep Research Phase Breadcrumbs ===
        await voice_io.notify( f"Dry run: Starting research→presentation simulation", priority="low", job_id=self.id_hash, queue_name="run" )
        await asyncio.sleep( 1.0 )

        await voice_io.notify( "Dry run: [RESEARCH] skipping query clarification", priority="low", job_id=self.id_hash, queue_name="run" )
        await asyncio.sleep( 1.0 )

        await voice_io.notify( "Dry run: [RESEARCH] skipping research planning", priority="low", job_id=self.id_hash, queue_name="run" )
        await asyncio.sleep( 1.0 )

        await voice_io.notify( "Dry run: [RESEARCH] skipping subquery research (5 queries)", priority="low", job_id=self.id_hash, queue_name="run" )
        await asyncio.sleep( 1.0 )

        await voice_io.notify( "Dry run: [RESEARCH] skipping report synthesis", priority="low", job_id=self.id_hash, queue_name="run" )
        await asyncio.sleep( 1.0 )

        await voice_io.notify( "Dry run: [RESEARCH] skipping report write to disk", priority="low", job_id=self.id_hash, queue_name="run" )
        await asyncio.sleep( 1.0 )

        # === Presentation Generation Phase Breadcrumbs ===
        await voice_io.notify( "Dry run: [PRESENTATION] skipping document ingestion", priority="low", job_id=self.id_hash, queue_name="run" )
        await asyncio.sleep( 1.0 )

        await voice_io.notify( "Dry run: [PRESENTATION] skipping narrative analysis", priority="low", job_id=self.id_hash, queue_name="run" )
        await asyncio.sleep( 1.0 )

        await voice_io.notify( "Dry run: [PRESENTATION] skipping slide outline generation", priority="low", job_id=self.id_hash, queue_name="run" )
        await asyncio.sleep( 1.0 )

        await voice_io.notify( "Dry run: [PRESENTATION] skipping slide elaboration", priority="low", job_id=self.id_hash, queue_name="run" )
        await asyncio.sleep( 1.0 )

        await voice_io.notify( "Dry run: [PRESENTATION] skipping YAML serialization", priority="low", job_id=self.id_hash, queue_name="run" )
        await asyncio.sleep( 1.0 )

        await voice_io.notify( "Dry run: [PRESENTATION] skipping Marp rendering", priority="low", job_id=self.id_hash, queue_name="run" )
        await asyncio.sleep( 1.0 )

        # Set mock results
        self.research_path = f"/io/deep-research/{self.user_email}/dry-run-{self.id_hash}/report.md"
        self.yaml_path     = f"/io/presentations/{self.user_email}/dry-run-{self.id_hash}/presentation.yaml"
        self.marp_path     = f"/io/presentations/{self.user_email}/dry-run-{self.id_hash}/presentation.md"

        # Store mock artifacts
        self.artifacts[ "research_path" ]     = self.research_path
        self.artifacts[ "research_abstract" ] = "Mock abstract from dry-run mode."
        self.artifacts[ "yaml_path" ]         = self.yaml_path
        self.artifacts[ "marp_path" ]         = self.marp_path
        self.artifacts[ "slide_count" ]       = 0   # dry-run: no real presentation built

        # Mock cost summary
        self.cost_summary = {
            "dr_cost_usd"    : 0.0,
            "pg_cost_usd"    : 0.0,
            "total_cost_usd" : 0.0,
        }
        self.artifacts[ "cost_summary" ] = self.cost_summary

        completion_abstract = f"""**Dry Run Complete!**

**Research Report**: {self.research_path} (mock - not actually created)

**YAML**: {self.yaml_path} (mock - not actually created)

**Presentation**: {self.marp_path} (mock - not actually created)

**Stats**: $0.00 total | 0 tokens | 12.0s (simulated)"""

        # Notify completion
        await voice_io.notify(
            "Dry run complete! Pipeline simulation finished.",
            priority="medium",
            abstract=completion_abstract,
            job_id=self.id_hash,
            queue_name="run"
        )

        voice_io.clear_job_id()
        return "Dry run complete. Research and presentation simulation finished."


def quick_smoke_test():
    """
    Quick smoke test for DeepResearchToPresentationJob.
    """
    import cosa.utils.util as cu

    cu.print_banner( "DeepResearchToPresentationJob Smoke Test", prepend_nl=True )

    try:
        # Test 1: Import
        print( "Testing module import..." )
        from cosa.agents.deep_research_to_presentation.job import DeepResearchToPresentationJob
        print( "✓ Module imported successfully" )

        # Test 2: Instantiation
        print( "Testing job instantiation..." )
        job = DeepResearchToPresentationJob(
            query                   = "test query for smoke test",
            user_id                 = "user123",
            user_email              = "test@test.com",
            session_id              = "session456",
            budget                  = 2.00,
            target_duration_minutes = 15,
            theme                   = "default",
            debug                   = True
        )
        print( f"✓ Job created with id: {job.id_hash}" )

        # Test 3: ID format
        print( "Testing ID format..." )
        assert job.id_hash.startswith( "rx-" ), "ID should start with rx-"
        print( f"✓ ID format correct: {job.id_hash}" )

        # Test 4: last_question_asked
        print( "Testing last_question_asked..." )
        lqa = job.last_question_asked
        assert "[Research→Presentation]" in lqa
        print( f"✓ last_question_asked: {lqa}" )

        # Test 5: is_cacheable
        print( "Testing is_cacheable property..." )
        assert job.is_cacheable == False
        print( "✓ is_cacheable correctly returns False" )

        # Test 6: Check attributes
        print( "Testing job attributes..." )
        assert job.query == "test query for smoke test"
        assert job.budget == 2.00
        assert job.target_duration_minutes == 15
        assert job.theme == "default"
        assert job.user_email == "test@test.com"
        assert job.state == JobState.PENDING
        print( "✓ All attributes set correctly" )

        # Test 7: Check JOB_TYPE and JOB_PREFIX
        print( "Testing class constants..." )
        assert DeepResearchToPresentationJob.JOB_TYPE == "research_to_presentation"
        assert DeepResearchToPresentationJob.JOB_PREFIX == "rx"
        print( "✓ Class constants correct" )

        # Note: We don't test do_all() here as it requires API keys and network
        print( "\n⚠ Note: do_all() not tested (requires API keys and services)" )

        print( "\n✓ Smoke test completed successfully" )

    except Exception as e:
        print( f"\n✗ Smoke test failed: {e}" )
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    quick_smoke_test()
