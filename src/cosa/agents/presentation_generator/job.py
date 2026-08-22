"""
Presentation Generator background job for queue-based execution.

Wraps the presentation generation pipeline for execution within the
COSA queue system. Enables users to submit presentation generation
requests via the API and receive results asynchronously.

Example:
    job = PresentationGeneratorJob(
        source_path  = "/io/deep-research/user@email/2026.01.26-topic.md",
        user_id      = "user123",
        user_email   = "user@example.com",
        session_id   = "wise-penguin",
        debug        = True
    )
    result = job.do_all()  # Runs presentation generation and returns conversational answer
"""

import asyncio
import os
from datetime import datetime
from typing import Optional

import cosa.utils.util as cu
from cosa.agents.agentic_job_base import AgenticJobBase
from cosa.rest.job_state import JobState


def resolve_source_path( path: str ) -> str:
    """
    Turn whatever a caller wrote into the one absolute path this job will open.

    WHY THIS EXISTS AT ALL. The retiring door did this and the job did it again, by two
    DIFFERENT rules: the door treated a leading slash as PROJECT-relative and built the
    absolute path itself, while the job's own existence check treated a leading slash as
    FILESYSTEM-absolute and used it verbatim. Nothing noticed, because the door always
    handed the job a path that was already absolute, so the job's rule never ran on a
    project-relative path. Retire the door without settling this and the browser — which
    sends `/io/deck.md` and cannot know the project root — would start failing with
    "Source document not found" for a file that is there.

    One rule now, and both the guard and the existence check read it:

        - a path already at or under the project root is returned unchanged
        - anything else is project-relative, leading slash or not

    So `/io/deck.md`, `io/deck.md` and `<root>/io/deck.md` all name the same file, which
    is what every caller already believed.

    ⚠️ THE CONSEQUENCE, STATED RATHER THAN BURIED. A caller who genuinely means the
    filesystem-absolute `/etc/passwd` gets `<root>/etc/passwd` instead — silently
    reinterpreted, not refused. That is the retiring door's contract kept verbatim
    (Pocholo, 2026-08-21), and it is why the guard below can be honest about `/etc/passwd`
    coming back True: the path it checked is not the path that name suggests.

    Requires:
        - path is a string

    Ensures:
        - returns an absolute path string
        - is idempotent: resolve( resolve( p ) ) == resolve( p )
    """
    project_root = cu.get_project_root()
    if path == project_root or path.startswith( project_root + "/" ):
        return path
    if path.startswith( "/" ):
        return project_root + path
    return project_root + "/" + path


def source_path_is_inside_the_project( path: str ) -> bool:
    """
    Whether a source path resolves to somewhere inside the project root.

    WHY THIS LIVES ON THE JOB AND NOT ON A ROUTE. It used to be
    `routers/presentation_generator.py::validate_source_path`, checked by the one door
    that built this job. That door is retired: presentation work now enters through
    `/api/v2/submit`, which takes a command and an args dict and — correctly — knows
    nothing about which of an agent's arguments happen to be file paths. A guard that
    lives on ONE entry point protects that entry point; a guard that lives on the thing
    which opens the file protects every caller, including the voice path and any door
    added later.

    Requires:
        - path is a non-empty string, absolute or project-relative

    ⚠️ A LEADING SLASH MEANS PROJECT-RELATIVE HERE, NOT FILESYSTEM-ABSOLUTE — see
    `resolve_source_path`, which both this guard and the job's existence check now read.
    `/etc/passwd` resolves to `<project>/etc/passwd` and comes back True, which looks
    alarming and is not a hole: that file does not exist, and the existence check refuses
    it a moment later.

    ⚠️ THIS CHECKS A PATH, NOT AN OPEN FILE, so it promises less than it looks like it
    promises (Pocholo, 2026-08-21). The check runs when the job is built and the file is
    opened phases later; a symlink swapped into the path between those two moments still
    wins. That gap is inherent to checking a name rather than a handle, it is no worse
    than the door this replaced, and it is written down here so the next reader does not
    assume more.

    Ensures:
        - returns True when the resolved path is the project root or inside it
        - returns False when it escapes, including via `..` segments and symlinks
          (os.path.realpath resolves both before the comparison)
    """
    project_root = os.path.realpath( cu.get_project_root() )
    resolved     = os.path.realpath( resolve_source_path( path ) )
    return resolved.startswith( project_root + "/" ) or resolved == project_root


class PresentationGeneratorJob( AgenticJobBase ):
    """
    Background job for Presentation Generator execution.

    Runs multi-phase presentation generation from a source document:
    1. Ingest source document
    2. Analyze narrative structure
    3. Generate slide outline with titles + visual types
    4. Elaborate full slide content with presenter notes
    5. Serialize to YAML intermediate file
    6. Render Marp Markdown (Phase 2+)
    7. Render visuals via Mermaid (Phase 2+)
    8. Deliver final artifacts

    Attributes:
        source_path: Path to the source document (markdown/text)
        yaml_path: Path to generated YAML (set after completion)
        marp_path: Path to generated Marp Markdown (set after completion)
        cost_summary: Execution cost summary (set after completion)
    """

    JOB_TYPE   = "presentation"
    JOB_PREFIX = "pr"

    def __init__(
        self,
        source_path: str,
        user_id: str,
        user_email: str,
        session_id: str,
        target_duration_minutes: Optional[ int ] = None,
        target_slide_count: Optional[ int ] = None,
        audience: Optional[ str ] = None,
        audience_context: Optional[ str ] = None,
        theme: Optional[ str ] = None,
        content_model: Optional[ str ] = None,
        render_only: bool = False,
        dry_run: bool = False,
        force_failure_mode: Optional[ str ] = None,
        debug: bool = False,
        verbose: bool = False
    ) -> None:
        """
        Initialize a Presentation Generator job.

        Requires:
            - source_path is a valid path to a source document
            - user_id is a valid system ID
            - user_email is a valid email address
            - session_id is a WebSocket session ID

        Ensures:
            - Job ID generated with "pr-" prefix
            - All parameters stored for execution

        Args:
            source_path: Path to the source document (markdown/text)
            user_id: System ID of the job owner
            user_email: Email address for output storage
            session_id: WebSocket session for notifications
            target_duration_minutes: Override target duration (None = use INI default)
            target_slide_count: Explicit slide count overriding the duration formula (None = use INI default / derive from duration)
            audience: Override audience level (None = use INI default)
            audience_context: Custom audience description (None = use INI default)
            theme: Override theme name (None = use INI default)
            content_model: Override Claude model (None = use INI default, e.g. claude-haiku-4-5-20251001)
            dry_run: Simulate execution without API calls
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

        # THE PATH GUARD, ENFORCED WHERE THE FILE IS ACTUALLY OPENED. The retiring door
        # checked this and refused with a 403; nothing downstream re-checked, so moving
        # the guard here is what keeps a retirement from quietly becoming a path-traversal
        # hole. Raising rather than returning False: a job that cannot be built safely
        # must not be built at all, and the factory's caller degrades on the exception.
        if not source_path_is_inside_the_project( source_path ):
            raise ValueError(
                f"Source path escapes the project root, refusing to build the job: {source_path!r}"
            )

        # Presentation parameters
        self.source_path             = source_path
        self.target_duration_minutes = target_duration_minutes
        self.target_slide_count      = target_slide_count
        self.audience                = audience
        self.audience_context        = audience_context
        self.theme                   = theme
        self.content_model           = content_model
        self.render_only             = render_only
        self.dry_run                 = dry_run
        self.force_failure_mode      = force_failure_mode

        # Results (populated after execution)
        self.yaml_path    = None
        self.marp_path    = None
        self.cost_summary = None

    @property
    def last_question_asked( self ) -> str:
        """
        Display string for queue UI.

        Returns source path filename with [Presentation] prefix.

        Returns:
            str: Human-readable job description
        """
        import os
        filename = os.path.basename( self.source_path )
        prefix   = "[Render] " if self.render_only else "[Presentation] "
        return f"{prefix}{filename}"

    def do_all( self ) -> str:
        """
        Execute presentation generation and return conversational answer.

        This is the main entry point called by RunningFifoQueue.
        Bridges to the async _execute() method via asyncio.run().

        Returns:
            str: Conversational answer summarizing generation results
        """
        if self.debug:
            print( f"[PresentationGeneratorJob] Starting do_all() for: {self.source_path}" )

        self.state      = JobState.RUNNING
        self.started_at = cu.get_current_datetime_iso()

        try:
            result = asyncio.run( self._execute() )

            # Check if cancellation was requested during execution
            if self._cancel_requested:
                self.state                 = JobState.CANCELLED
                self.completed_at          = cu.get_current_datetime_iso()
                self.error                 = "Cancelled by user request"
                self.answer_conversational = result or "Presentation generation was cancelled by the user."
                if self.debug:
                    print( "[PresentationGeneratorJob] Cancelled by user request" )
                return self.answer_conversational

            self.state        = JobState.COMPLETED
            self.completed_at = cu.get_current_datetime_iso()
            self.result       = result
            self.answer_conversational = result

            if self.debug:
                duration = self.get_execution_duration_seconds()
                print( f"[PresentationGeneratorJob] Completed in {duration:.1f}s" )

            return result

        except Exception as e:
            self.state        = JobState.FAILED
            self.completed_at = cu.get_current_datetime_iso()
            self.error        = str( e )
            self.answer_conversational = f"Presentation generation failed: {str( e )}"

            if self.debug:
                print( f"[PresentationGeneratorJob] Failed: {e}" )
                import traceback
                traceback.print_exc()

            # Re-raise so the agentic-pool Future captures the exception.
            # Backlog item 5 (2026-04-29): canonical Future contract.
            raise

    def _apply_job_overrides( self, config ) -> None:
        """
        Overlay this job's per-request args onto the INI-loaded config, in place.

        Requires:
            - config is a PresentationConfig instance

        Ensures:
            - Each job arg that is not None replaces the matching config field
            - audience_context treats the expeditor "none" sentinel (and the empty
              string) as "not provided" and is NOT copied — otherwise the prompt
              builders would inject a bogus "Additional audience context: none" line
        """
        if self.target_duration_minutes is not None:
            config.target_duration_minutes = self.target_duration_minutes
        if self.target_slide_count is not None:
            config.target_slide_count = self.target_slide_count
        if self.audience is not None:
            config.audience = self.audience
        if self.theme is not None:
            config.default_theme = self.theme
        if self.content_model is not None:
            config.content_model = self.content_model
        if self.audience_context is not None and self.audience_context.strip().lower() not in ( "", "none" ):
            config.audience_context = self.audience_context

    async def _execute( self ) -> str:
        """
        Internal async presentation generation execution.

        Uses the PresentationOrchestratorAgent to run the full workflow.
        When dry_run=True, sends breadcrumb notifications and returns mock results.

        Returns:
            str: Conversational summary of generation results
        """
        from cosa.agents.presentation_generator import voice_io, cosa_interface
        import os

        # Re-establish core voice_io binding (import-order race: last configure() wins)
        voice_io.reconfigure()

        # Handle dry-run mode with breadcrumb notifications
        if self.dry_run:
            return await self._execute_dry_run( voice_io, cosa_interface )

        # Import presentation components (only needed for normal mode)
        from cosa.agents.presentation_generator.orchestrator import PresentationOrchestratorAgent
        from cosa.agents.presentation_generator.config import PresentationConfig
        from cosa.config.configuration_manager import ConfigurationManager

        # Set sender_id and target_user for notifications
        cosa_interface.SENDER_ID   = cosa_interface._get_sender_id( suffix=self.base_id )
        cosa_interface.TARGET_USER = self.user_email

        # Set job_id for auto-injection into all notify() calls
        voice_io.set_job_id( self.id_hash )

        try:
            # Validate source document exists
            # ONE RESOLUTION RULE, shared with the guard above. This used to read a
            # leading slash as filesystem-absolute while the guard read it as
            # project-relative — harmless only for as long as the door handed this job an
            # already-absolute path. It no longer does.
            full_path = resolve_source_path( self.source_path )

            if not os.path.exists( full_path ):
                raise FileNotFoundError( f"Source document not found: {self.source_path}" )

            if self.debug:
                print( f"[PresentationGeneratorJob] Source document: {full_path}" )

            # Notify start
            mode_label = "render-only" if self.render_only else "presentation generation"
            await voice_io.notify(
                f"Starting {mode_label} from: {os.path.basename( full_path )}",
                priority="medium",
                queue_name="run"
            )

            # Create config from INI
            config_mgr = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )
            config = PresentationConfig.from_config( config_mgr, debug=self.debug )

            # Apply this job's per-request args onto the INI-loaded config.
            # Extracted to _apply_job_overrides for unit-testability (the copy
            # otherwise runs only inside the full async pipeline).
            self._apply_job_overrides( config )

            # Create orchestrator
            agent = PresentationOrchestratorAgent(
                source_path  = full_path,
                user_id      = self.user_email,
                config       = config,
                offline_mode = self.dry_run,   # JOB dry_run early-returns before here; this only ever passes False. Renamed keyword (row ec8ca1ce); RHS is the JOB flag and stays.
                debug        = self.debug,
                verbose      = self.verbose,
            )
            self._orchestrator = agent  # Store ref for cancellation from API thread

            # Branch: render-only (Phases 6-8) vs full pipeline (Phases 1-8)
            if self.render_only:
                presentation = await agent.render_from_yaml_async( full_path )
            else:
                presentation = await agent.do_all_async()

            if presentation is None:
                await voice_io.notify( "Presentation generation was cancelled.", priority="medium", queue_name="run" )
                return "Presentation generation was cancelled by the user."

            # Extract results from orchestrator state
            state = agent._presentation_state
            self.yaml_path = state.get( "yaml_path" )
            self.marp_path = state.get( "marp_path" )
            self.pptx_path = state.get( "pptx_path" )

            # Store artifacts
            self.artifacts[ "yaml_path" ]        = self.yaml_path
            self.artifacts[ "marp_path" ]        = self.marp_path
            self.artifacts[ "pptx_path" ]        = self.pptx_path
            self.artifacts[ "presentation_id" ]  = agent.presentation_id
            self.artifacts[ "slide_count" ]      = presentation.total_slides

            # Build cost summary from API client
            cost_est = agent.api_client.cost_estimate if agent._api_client else None
            api_cost = cost_est.estimated_cost_usd if cost_est else 0.0
            self.cost_summary = {
                "content_cost_usd"   : api_cost,
                "total_cost_usd"     : api_cost,
                "total_input_tokens" : cost_est.total_input_tokens if cost_est else 0,
                "total_output_tokens": cost_est.total_output_tokens if cost_est else 0,
                "total_api_calls"    : cost_est.total_api_calls if cost_est else 0,
            }
            self.artifacts[ "cost_summary" ] = self.cost_summary

            # Build clickable links for notification abstract
            import urllib.parse
            import cosa.utils.util as cu
            io_base = cu.get_project_root() + "/io/"

            yaml_link = self.yaml_path
            marp_link = self.marp_path
            pptx_link = self.pptx_path
            if self.yaml_path and self.yaml_path.startswith( io_base ):
                rel_path  = self.yaml_path.replace( io_base, "" )
                yaml_link = f"[View YAML](/app/docs?path={urllib.parse.quote( rel_path )})"
            if self.marp_path and self.marp_path.startswith( io_base ):
                rel_path  = self.marp_path.replace( io_base, "" )
                marp_link = f"[View Presentation](/app/docs?path={urllib.parse.quote( rel_path )})"
            if self.pptx_path and self.pptx_path.startswith( io_base ):
                rel_path  = self.pptx_path.replace( io_base, "" )
                pptx_link = f"[Download PPTX](/api/io/file?path={urllib.parse.quote( rel_path )}&download=true)"

            # Build abstract and report_path for queue metadata → UI job card
            total_slides = presentation.total_slides
            duration_min = config.target_duration_minutes

            pptx_line = f"\n\n**PPTX**: {pptx_link}" if self.pptx_path else ""
            completion_abstract = f"""**Presentation Complete!**

**Slides**: {total_slides} slides, ~{duration_min} minutes

**YAML**: {yaml_link}

**Marp**: {marp_link}{pptx_line}

**Stats**: ${api_cost:.4f} | ID: {agent.presentation_id}"""

            self.artifacts[ "abstract" ]    = completion_abstract
            # Store relative paths (strip io_base prefix) for /app/docs URL generation
            marp_rel = self.marp_path.replace( io_base, "" ) if self.marp_path and self.marp_path.startswith( io_base ) else self.marp_path
            yaml_rel = self.yaml_path.replace( io_base, "" ) if self.yaml_path and self.yaml_path.startswith( io_base ) else self.yaml_path
            pptx_rel = self.pptx_path.replace( io_base, "" ) if self.pptx_path and self.pptx_path.startswith( io_base ) else self.pptx_path
            self.artifacts[ "report_path" ] = marp_rel
            self.artifacts[ "yaml_path" ]   = yaml_rel
            self.artifacts[ "pptx_path" ]   = pptx_rel

            # Notify completion (with job_id and queue_name for job card routing)
            await voice_io.notify(
                f"Presentation complete! {total_slides} slides, ~{duration_min} minutes.",
                priority="medium",
                abstract=completion_abstract,
                job_id=self.id_hash,
                queue_name="run"
            )

            # Return conversational answer
            return f"Presentation complete! Generated {total_slides} slides, ~{duration_min} minutes. ID: {agent.presentation_id}"

        finally:
            voice_io.clear_job_id()

    async def _execute_dry_run( self, voice_io, cosa_interface ) -> str:
        """
        Execute dry-run mode with breadcrumb notifications.

        Simulates the presentation generation workflow without making API calls.
        Sends low-priority notifications at each phase and returns mock results.

        Args:
            voice_io: Voice I/O module for notifications
            cosa_interface: COSA interface module for sender ID

        Returns:
            str: Mock conversational summary
        """
        import os

        # Set sender_id and target_user for notifications
        cosa_interface.SENDER_ID   = cosa_interface._get_sender_id( suffix=self.base_id )
        cosa_interface.TARGET_USER = self.user_email

        # Set job_id for auto-injection into all notify() calls
        voice_io.set_job_id( self.id_hash )

        filename = os.path.basename( self.source_path )

        if self.debug:
            print( f"[PresentationGeneratorJob] DRY RUN MODE for: {filename}" )

        try:
            # Breadcrumb: Starting
            await voice_io.notify( f"Dry run: Starting presentation simulation from {filename}", priority="low", job_id=self.id_hash, queue_name="run" )
            await asyncio.sleep( 0.5 )

            # Breadcrumb: Phase 1 — Ingest
            await voice_io.notify( "Dry run: Skipping document ingestion", priority="low", job_id=self.id_hash, queue_name="run" )
            await asyncio.sleep( 0.5 )

            # Breadcrumb: Phase 2 — Analyze
            await voice_io.notify( "Dry run: Skipping narrative analysis", priority="low", job_id=self.id_hash, queue_name="run" )
            await asyncio.sleep( 0.5 )

            # Breadcrumb: Phase 3 — Outline
            await voice_io.notify( "Dry run: Skipping slide outline generation", priority="low", job_id=self.id_hash, queue_name="run" )
            await asyncio.sleep( 0.5 )

            # Breadcrumb: Phase 4 — Elaborate
            await voice_io.notify( "Dry run: Skipping slide content elaboration", priority="low", job_id=self.id_hash, queue_name="run" )
            await asyncio.sleep( 0.5 )

            # Breadcrumb: Phase 5 — Serialize
            await voice_io.notify( "Dry run: Skipping YAML serialization", priority="low", job_id=self.id_hash, queue_name="run" )
            await asyncio.sleep( 0.5 )

            # Set mock results
            self.yaml_path = f"/io/presentations/{self.user_email}/dry-run-{self.id_hash}/presentation.yaml"
            self.marp_path = f"/io/presentations/{self.user_email}/dry-run-{self.id_hash}/presentation.md"

            # Store mock artifacts
            self.artifacts[ "yaml_path" ]        = self.yaml_path
            self.artifacts[ "marp_path" ]        = self.marp_path
            self.artifacts[ "presentation_id" ]  = f"dry-run-{self.id_hash}"
            self.artifacts[ "slide_count" ]      = 0   # dry-run: no real presentation built

            # Mock cost summary
            self.cost_summary = {
                "content_cost_usd"   : 0.0,
                "total_cost_usd"     : 0.0,
                "total_input_tokens" : 0,
                "total_output_tokens": 0,
                "total_api_calls"    : 0,
            }
            self.artifacts[ "cost_summary" ] = self.cost_summary

            # Phase 6 repair loop hook: deliberately fail the dry-run to exercise
            # the dead-queue watchdog + BFE auto-fix pipeline.
            if self.force_failure_mode:
                await self._raise_forced_failure( voice_io )

            completion_abstract = f"""**Dry Run Complete!**

**YAML**: {self.yaml_path} (mock - not actually created)

**Marp**: {self.marp_path} (mock - not actually created)

**Stats**: $0.00 | slide_count={self.artifacts[ "slide_count" ]} (no deck built) | simulated (no real work)"""

            # Notify completion
            await voice_io.notify(
                "Dry run complete! Presentation simulation finished.",
                priority="medium",
                abstract=completion_abstract,
                job_id=self.id_hash,
                queue_name="run"
            )

            return "Dry run complete. Presentation simulation finished."

        finally:
            voice_io.clear_job_id()


def quick_smoke_test():
    """Quick smoke test for PresentationGeneratorJob."""
    import cosa.utils.util as cu

    cu.print_banner( "PresentationGeneratorJob Smoke Test", prepend_nl=True )

    try:
        # Test 1: Import
        print( "Testing module import..." )
        from cosa.agents.presentation_generator.job import PresentationGeneratorJob
        print( "  PASS" )

        # Test 2: Instantiation
        print( "Testing job instantiation..." )
        job = PresentationGeneratorJob(
            source_path             = "/io/deep-research/test@test.com/test-article.md",
            user_id                 = "user123",
            user_email              = "test@test.com",
            session_id              = "session456",
            target_duration_minutes = 15,
            audience                = "general",
            dry_run                 = True,
            debug                   = True
        )
        print( f"  Job created with id: {job.id_hash}" )
        print( "  PASS" )

        # Test 3: ID format
        print( "Testing ID format..." )
        assert job.id_hash.startswith( "pr-" ), f"ID should start with pr-, got: {job.id_hash}"
        print( f"  ID: {job.id_hash}" )
        print( "  PASS" )

        # Test 4: last_question_asked
        print( "Testing last_question_asked..." )
        lqa = job.last_question_asked
        assert "[Presentation]" in lqa
        assert "test-article.md" in lqa
        print( f"  last_question_asked: {lqa}" )
        print( "  PASS" )

        # Test 5: is_cacheable
        print( "Testing is_cacheable property..." )
        assert job.is_cacheable is False
        print( "  PASS" )

        # Test 6: Class constants
        print( "Testing class constants..." )
        assert PresentationGeneratorJob.JOB_TYPE == "presentation"
        assert PresentationGeneratorJob.JOB_PREFIX == "pr"
        print( "  PASS" )

        # Test 7: Attributes
        print( "Testing job attributes..." )
        assert job.source_path == "/io/deep-research/test@test.com/test-article.md"
        assert job.target_duration_minutes == 15
        assert job.audience == "general"
        assert job.dry_run is True
        assert job.state == JobState.PENDING
        print( "  PASS" )

        print( "\nAll PresentationGeneratorJob smoke tests passed" )

    except Exception as e:
        print( f"\nSmoke test failed: {e}" )
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    quick_smoke_test()
