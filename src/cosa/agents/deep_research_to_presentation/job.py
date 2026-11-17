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

from cosa.agents.agentic_job_base import AgenticJobBase
from cosa.agents.deep_research.seed_context import normalize_source_document
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

    CHAIN_TITLE          = "Research→Presentation"
    CHAIN_NOUN           = "presentation"
    DRY_RUN_ICON         = ""
    DRY_RUN_SECOND_STAGE = (
        "[PRESENTATION] skipping document ingestion",
        "[PRESENTATION] skipping narrative analysis",
        "[PRESENTATION] skipping slide outline generation",
        "[PRESENTATION] skipping slide elaboration",
        "[PRESENTATION] skipping YAML serialization",
        "[PRESENTATION] skipping Marp rendering",
    )

    def __init__(
        self,
        query: str,
        user_id: str,
        user_email: str,
        session_id: str,
        budget: Optional[ float ] = None,
        target_duration_minutes: Optional[ int ] = None,
        target_slide_count: Optional[ int ] = None,
        theme: Optional[ str ] = None,
        lead_model: Optional[ str ] = None,
        dry_run: bool = False,
        audience: Optional[ str ] = None,
        audience_context: Optional[ str ] = None,
        source_document: Optional[ list ] = None,
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
            target_slide_count: Explicit slide count overriding the duration formula (None = use default)
            theme: Override presentation theme (None = use default)
            dry_run: Simulate execution without API calls
            audience: Target audience level (beginner/general/expert/academic)
            audience_context: Custom audience description
            source_document: Absolute paths to local documents the research leg reads
                first, as seed context. Already scope-validated and resolved by the v2
                door ( cosa/rest/v2/source_document.py ). This constructor receives real
                paths and does not re-decide whether they may be read. None or [] means
                the run behaves as it did without this argument.
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
        self.target_slide_count      = target_slide_count
        self.theme                   = theme
        self.lead_model              = lead_model
        self.dry_run                 = dry_run
        self.audience                = audience
        self.audience_context        = audience_context
        self.source_document         = normalize_source_document( source_document )

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
        return self._run_execute( "DeepResearchToPresentationJob", self.query[ :50 ], "Research→Presentation pipeline failed" )

    def _make_agent( self ):
        """
        Build the chained agent this job runs, so the job-to-agent hand-off can be tested.

        A method, not an expression inside `_execute`, because `_execute` runs the whole pipeline: notifications, research, slides and storage.
        That needs real services, so a test could only prove its own copy of the arguments.
        The `test_source_document_reaches_the_model_*` tests drive it on a job the real factory built.

        Ensures:
            - returns a fully-configured agent carrying this job's own arguments
        """
        from cosa.agents.deep_research_to_presentation.agent import DeepResearchToPresentationAgent

        return DeepResearchToPresentationAgent(
            query                   = self.query,
            user_email              = self.user_email,
            budget                  = self.budget,
            lead_model              = self.lead_model,
            audience                = self.audience,
            audience_context        = self.audience_context,
            source_document         = self.source_document,
            target_duration_minutes = self.target_duration_minutes,
            target_slide_count      = self.target_slide_count,
            theme                   = self.theme,
            cli_mode                = False,  # Voice-driven mode for queue
            debug                   = self.debug,
            verbose                 = self.verbose,
        )

    async def _execute( self ) -> str:
        """
        Run the research→presentation pipeline, or its dry-run simulation when dry_run is set.

        Returns:
            str: Conversational summary of pipeline results
        """
        return await self._run_chained_pipeline()

    def _chain_pipeline_state( self ):
        """
        Return this pipeline's state enum, imported late so a test can fake the module graph.

        Ensures:
            - returns the PipelineState enum of deep_research_to_presentation.state
        """
        from cosa.agents.deep_research_to_presentation.state import PipelineState

        return PipelineState

    def _chain_debug_lines( self ) -> list:
        """
        Return the job-specific debug lines printed after the shared query and budget lines.

        Ensures:
            - returns an empty list
        """
        return [ ]

    def _store_chain_artifacts( self, result ) -> None:
        """
        Keep the presentation paths from a finished run on the job and in its artifacts.

        Requires:
            - result carries research_path, yaml_path, marp_path and slide_count

        Ensures:
            - the three paths are job attributes and artifacts entries
            - the slide count is an artifacts entry
        """
        self.research_path = result.research_path
        self.yaml_path     = result.yaml_path
        self.marp_path     = result.marp_path

        self.artifacts[ "yaml_path" ]   = result.yaml_path
        self.artifacts[ "marp_path" ]   = result.marp_path
        self.artifacts[ "slide_count" ] = result.slide_count

    def _chain_return_tail( self ) -> str:
        """
        Return the last sentence of the conversational answer.

        Ensures:
            - returns the presentation path sentence
        """
        return f"Presentation: {self.marp_path}"

    async def _chain_completion( self, result ) -> tuple:
        """
        Build the completion card for a finished run, with clickable links.

        Requires:
            - result is a completed ChainedResult

        Ensures:
            - returns ( abstract, spoken_suffix ) with an empty suffix
        """
        research_link = self._io_view_link( result.research_path, "📄 View" )
        yaml_link     = self._io_view_link( result.yaml_path,     "View YAML" )
        marp_link     = self._io_view_link( result.marp_path,     "View Presentation" )

        completion_abstract = f"""**Research → Presentation Complete!**

**Research Report**: {research_link}

**Slides**: {result.slide_count} slides

**YAML**: {yaml_link}

**Presentation**: {marp_link}

**Cost**: ${result.total_cost:.4f}"""

        skipped_names = self._skipped_topic_names( result )
        if skipped_names:
            completion_abstract += "\n\n" + self._skipped_topics_line( skipped_names )

        return completion_abstract, ""

    def _store_dry_run_results( self ) -> str:
        """
        Store the mock presentation results of a dry run.

        Ensures:
            - mock paths are job attributes and artifacts entries
            - the slide count artifact is 0, because no presentation is built
            - returns the dry-run completion abstract
        """
        self._store_dry_run_research()
        self.yaml_path     = self._dry_run_io_path( "presentations", "presentation.yaml" )
        self.marp_path     = self._dry_run_io_path( "presentations", "presentation.md" )

        self.artifacts[ "yaml_path" ]         = self.yaml_path
        self.artifacts[ "marp_path" ]         = self.marp_path
        self.artifacts[ "slide_count" ]       = 0

        return f"""**Dry Run Complete!**

**Research Report**: {self.research_path} (mock - not actually created)

**YAML**: {self.yaml_path} (mock - not actually created)

**Presentation**: {self.marp_path} (mock - not actually created)

**Stats**: $0.00 total | 0 tokens | 12.0s (simulated)"""


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
            target_slide_count      = 12,
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
        assert job.target_slide_count == 12
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
