"""
Podcast Generator background job for queue-based execution.

Wraps the existing PodcastOrchestratorAgent functionality for execution
within the COSA queue system. Enables users to submit podcast generation
requests via the API and receive results asynchronously.

Example:
    job = PodcastGeneratorJob(
        research_path  = "/io/deep-research/user@email/2026.01.26-topic.md",
        user_id        = "user123",
        user_email     = "user@example.com",
        session_id     = "wise-penguin",
        target_languages = [ "en" ],
        max_segments   = None,
        debug          = True
    )
    result = job.do_all()  # Runs podcast generation and returns conversational answer
"""

import asyncio
import time
from datetime import datetime
from typing import Optional, List

import cosa.utils.util as cu
from cosa.agents.agentic_job_base import AgenticJobBase
from cosa.rest.job_state import JobState


class PodcastGeneratorJob( AgenticJobBase ):
    """
    Background job for Podcast Generator execution.

    Runs multi-phase podcast generation from a research document:
    1. Script generation from research content
    2. Script review and optional revision
    3. TTS audio generation
    4. Audio stitching into final podcast

    Sends progress notifications via cosa-voice and completion notification
    with links to generated artifacts.

    Attributes:
        research_path: Path to the Deep Research markdown document
        target_languages: List of ISO language codes for audio generation
        max_segments: Limit TTS to first N segments (cost control)
        audio_path: Path to generated audio (set after completion)
        script_path: Path to generated script (set after completion)
        cost_summary: Execution cost summary (set after completion)
    """

    JOB_TYPE   = "podcast"
    JOB_PREFIX = "pg"

    def __init__(
        self,
        research_path: str,
        user_id: str,
        user_email: str,
        session_id: str,
        target_languages: Optional[ List[ str ] ] = None,
        max_segments: Optional[ int ] = None,
        dry_run: bool = False,
        force_failure_mode: Optional[ str ] = None,
        audience: Optional[ str ] = None,
        audience_context: Optional[ str ] = None,
        debug: bool = False,
        verbose: bool = False
    ) -> None:
        """
        Initialize a Podcast Generator job.

        Requires:
            - research_path is a valid path to a research document
            - user_id is a valid system ID
            - user_email is a valid email address
            - session_id is a WebSocket session ID

        Ensures:
            - Job ID generated with "pg-" prefix
            - All parameters stored for execution

        Args:
            research_path: Path to the Deep Research markdown document
            user_id: System ID of the job owner
            user_email: Email address for output storage
            session_id: WebSocket session for notifications
            target_languages: List of ISO language codes (default: ["en"])
            max_segments: Limit TTS to first N segments (None = all)
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

        # Podcast parameters
        self.research_path      = research_path
        self.target_languages   = target_languages or [ "en" ]
        self.max_segments       = max_segments
        self.dry_run            = dry_run
        self.force_failure_mode = force_failure_mode
        self.audience           = audience
        self.audience_context   = audience_context

        # Results (populated after execution)
        self.audio_path    = None
        self.script_path   = None
        self.cost_summary  = None

    @property
    def last_question_asked( self ) -> str:
        """
        Display string for queue UI.

        Returns research path filename with [Podcast] prefix.
        JS header truncates independently via truncateText().

        Returns:
            str: Human-readable job description
        """
        import os
        filename = os.path.basename( self.research_path )
        return f"[Podcast] {filename}"

    def do_all( self ) -> str:
        """
        Execute podcast generation and return conversational answer.

        This is the main entry point called by RunningFifoQueue.
        Bridges to the async _execute() method via asyncio.run().

        Returns:
            str: Conversational answer summarizing generation results
        """
        if self.debug:
            print( f"[PodcastGeneratorJob] Starting do_all() for: {self.research_path}" )

        self.state      = JobState.RUNNING
        self.started_at = cu.get_current_datetime_iso()

        try:
            result = asyncio.run( self._execute() )

            # Check if cancellation was requested during execution
            if self._cancel_requested:
                self.state                 = JobState.CANCELLED
                self.completed_at          = cu.get_current_datetime_iso()
                self.error                 = "Cancelled by user request"
                self.answer_conversational = result or "Podcast generation was cancelled by the user."
                if self.debug:
                    print( f"[PodcastGeneratorJob] Cancelled by user request" )
                return self.answer_conversational

            self.state        = JobState.COMPLETED
            self.completed_at = cu.get_current_datetime_iso()
            self.result       = result
            self.answer_conversational = result

            if self.debug:
                duration = self.get_execution_duration_seconds()
                print( f"[PodcastGeneratorJob] Completed in {duration:.1f}s" )

            return result

        except Exception as e:
            self.state        = JobState.FAILED
            self.completed_at = cu.get_current_datetime_iso()
            self.error        = str( e )
            self.answer_conversational = f"Podcast generation failed: {str( e )}"

            if self.debug:
                print( f"[PodcastGeneratorJob] Failed: {e}" )
                import traceback
                traceback.print_exc()

            # Re-raise so the agentic-pool Future captures the exception.
            # Backlog item 5 (2026-04-29): canonical Future contract.
            raise

    async def _execute( self ) -> str:
        """
        Internal async podcast generation execution.

        Uses the PodcastOrchestratorAgent to run the full workflow.
        When dry_run=True, sends breadcrumb notifications and returns mock results.

        Returns:
            str: Conversational summary of generation results
        """
        from cosa.agents.podcast_generator import voice_io, cosa_interface
        import cosa.utils.util as cu
        import os

        self._start_time = time.time()

        # Re-establish core voice_io binding (import-order race: last configure() wins)
        voice_io.reconfigure()

        # Handle dry-run mode with breadcrumb notifications
        if self.dry_run:
            return await self._execute_dry_run( voice_io, cosa_interface )

        # Import podcast components
        from cosa.agents.podcast_generator.orchestrator import PodcastOrchestratorAgent
        from cosa.agents.podcast_generator.config import PodcastConfig

        # Validate research document exists
        if not self.research_path.startswith( "/" ):
            full_path = cu.get_project_root() + "/" + self.research_path
        else:
            full_path = self.research_path

        if not os.path.exists( full_path ):
            raise FileNotFoundError( f"Research document not found: {self.research_path}" )

        # Set sender_id and target_user for notifications
        cosa_interface.SENDER_ID   = cosa_interface._get_sender_id( suffix=self.base_id )
        cosa_interface.TARGET_USER = self.user_email

        # Set job_id for auto-injection into all orchestrator notify() calls
        voice_io.set_job_id( self.id_hash )

        if self.debug:
            print( f"[PodcastGeneratorJob] Research document: {full_path}" )
            print( f"[PodcastGeneratorJob] Target languages: {self.target_languages}" )
            if self.max_segments:
                print( f"[PodcastGeneratorJob] Max segments: {self.max_segments}" )

        try:
            # Notify start
            await voice_io.notify(
                f"Starting podcast generation from: {os.path.basename( full_path )}",
                priority="medium",
                queue_name="run"
            )

            # Create config from INI
            from cosa.config.configuration_manager import ConfigurationManager
            config_mgr = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )
            config = PodcastConfig.from_config( config_mgr, debug=self.debug )

            # Job args override INI values
            if self.audience:
                config.audience = self.audience
            if self.audience_context:
                config.audience_context = self.audience_context

            # Create orchestrator
            agent = PodcastOrchestratorAgent(
                research_doc_path = full_path,
                user_id           = self.user_email,
                config            = config,
                target_languages  = self.target_languages,
                max_segments      = self.max_segments,
                debug             = self.debug,
                verbose           = self.verbose,
            )
            self._orchestrator = agent  # Store ref for cancellation from API thread

            # Run the full workflow
            script = await agent.do_all_async()

            if script is None:
                await voice_io.notify( "Podcast generation was cancelled.", priority="medium", queue_name="run" )
                return "Podcast generation was cancelled by the user."

            # Extract results from agent state
            state = agent._podcast_state
            self.audio_path  = state.get( "final_audio_path" )
            self.script_path = state.get( "final_script_path" )

            # Every run generates one artifact pair PER language (default en,es-MX).
            # The orchestrator stores them keyed by language; thread ALL of them into
            # the card, not just the English primary (bug 00e6aba1).
            audio_by_lang  = dict( state.get( "audio_paths_by_language" )  or {} )
            script_by_lang = dict( state.get( "script_paths_by_language" ) or {} )

            # Build relative paths under io/ for URL generation + UI job-card metadata.
            # Mirrors presentation_generator/job.py:301-341 — match the receiving
            # logic in cosa/rest/routers/io_files.py:88-98 (handles abs / "io/" / "/" prefixes).
            import urllib.parse
            from cosa.agents.podcast_generator.config import LANGUAGE_NAMES
            io_base = cu.get_project_root() + "/io/"

            def _to_rel( p ):
                if not p: return None
                if p.startswith( io_base ): return p[ len( io_base ): ]
                if p.startswith( "io/" ):   return p[ 3: ]
                return p.lstrip( "/" )

            languages  = getattr( self, "target_languages", [] ) or [ "en" ]

            # Fallback for single-language or older orchestrator state that only set
            # the primary path: seed the by-language maps from it under the first
            # requested language so the multi-language code path below stays uniform.
            if not audio_by_lang and self.audio_path:
                audio_by_lang = { languages[ 0 ]: self.audio_path }
            if not script_by_lang and self.script_path:
                script_by_lang = { languages[ 0 ]: self.script_path }

            # Ordered language list: requested order first, then any extra languages
            # that actually produced an artifact but were not in target_languages.
            ordered_langs = [ l for l in languages if l in audio_by_lang or l in script_by_lang ]
            for l in list( audio_by_lang ) + list( script_by_lang ):
                if l not in ordered_langs:
                    ordered_langs.append( l )

            audio_rel  = _to_rel( self.audio_path )
            script_rel = _to_rel( self.script_path )

            # Store relative paths in artifacts so the UI job-card builds correct URLs
            # (matches presentation_generator convention at job.py:336-341). Primary
            # (English) stays under the historical keys; the full per-language maps are
            # added so any downstream consumer can reach every artifact.
            self.artifacts[ "audio_path" ]  = audio_rel
            self.artifacts[ "script_path" ] = script_rel
            self.artifacts[ "report_path" ] = script_rel
            self.artifacts[ "podcast_id" ]  = agent.podcast_id
            self.artifacts[ "audio_paths_by_language" ]  = { l: _to_rel( p ) for l, p in audio_by_lang.items() }
            self.artifacts[ "script_paths_by_language" ] = { l: _to_rel( p ) for l, p in script_by_lang.items() }

            # Build cost summary
            api_cost = agent.api_client.cost_estimate.estimated_cost_usd if agent._api_client else 0.0
            self.cost_summary = {
                "script_cost_usd" : api_cost,
                "audio_cost_usd"  : 0.0,  # TODO: Calculate from TTS results
                "total_cost_usd"  : api_cost,
            }
            self.artifacts[ "cost_summary" ] = self.cost_summary

            # ── Completion report (Phase 11 pattern: outcome-aware TTS + rich abstract) ──
            n_segments    = script.get_segment_count()
            script_minutes = script.estimated_duration_minutes
            elapsed_sec   = round( time.time() - self._start_time, 1 )
            has_audio     = bool( self.audio_path )
            n_langs       = len( languages )

            # Three-variant TTS
            if has_audio and n_segments > 0:
                tts_msg = (
                    f"Podcast complete. {n_segments} segment{'s' if n_segments != 1 else ''} "
                    f"rendered in {n_langs} language{'s' if n_langs != 1 else ''}."
                )
            elif n_segments > 0:
                tts_msg = f"Podcast script complete. Audio rendering pending or failed."
            else:
                tts_msg = "Podcast generation complete with no segments produced."

            # Build clickable links — ONE labelled set PER LANGUAGE (bug 00e6aba1: a
            # two-language run wrote two mp3s but the card linked only English). All
            # audio links target the same in-app HTML5 player page (/app/audio); they
            # differ only by the &embed=1 flag:
            #   - Play Here → &embed=1: floating in-place overlay (Rick's on-stage default).
            #   - Listen → no flag: opens the player as a standalone tab.
            #   - Download streams the raw mp3 with attachment disposition.
            def _script_link( rel ):
                return f"[📝 Script](/app/docs?path={urllib.parse.quote( rel )})" if rel else None

            def _audio_triplet( rel ):
                enc = urllib.parse.quote( rel )
                return (
                    f"[▶️ Play Here](/app/audio?path={enc}&embed=1) | "
                    f"[🎧 Listen](/app/audio?path={enc}) | "
                    f"[⬇️ Download](/api/io/file?path={enc}&download=true)"
                )

            # One line per language: "**Mexican Spanish**: 📝 Script | ▶️ Play Here | 🎧 Listen | ⬇️ Download"
            per_language_lines = []
            for lang in ordered_langs:
                label  = LANGUAGE_NAMES.get( lang, lang )
                a_rel  = _to_rel( audio_by_lang.get( lang ) )
                s_rel  = _to_rel( script_by_lang.get( lang ) )
                parts  = []
                s_link = _script_link( s_rel )
                if s_link: parts.append( s_link )
                if a_rel:  parts.append( _audio_triplet( a_rel ) )
                if parts:
                    per_language_lines.append( f"**{label}**: " + " | ".join( parts ) )

            # Rich markdown abstract
            lines = [ "**Podcast Activity Report**", "" ]
            lines.append( f"**Segments**: {n_segments} (~{script_minutes:.1f} min)" )
            lines.append( f"**Languages**: {', '.join( languages )}" )
            lines.extend( per_language_lines )
            if self.cost_summary:  # pragma: no branch - cost_summary is set unconditionally (3-key dict) earlier, so it is always truthy here; the False arc is unreachable
                total_cost = self.cost_summary.get( "total_cost_usd", 0.0 )
                lines.append( f"**Cost**: ${total_cost:.4f}" )
            lines.append( f"**Duration**: {elapsed_sec}s" )
            completion_abstract = "\n".join( lines )

            try:
                await voice_io.notify(
                    tts_msg,
                    priority   = "medium",
                    abstract   = completion_abstract,
                    job_id     = self.id_hash,
                    queue_name = "run",
                )
            except Exception as notify_err:
                print( f"[PodcastGeneratorJob] completion notify failed: {notify_err}" )

            # Conversational answer
            return (
                f"Podcast complete! Generated {n_segments} segment{'s' if n_segments != 1 else ''}, "
                f"~{script_minutes:.1f} minutes. Audio: {self.audio_path}"
            )

        finally:
            voice_io.clear_job_id()

    async def _execute_dry_run( self, voice_io, cosa_interface ) -> str:
        """
        Execute dry-run mode with breadcrumb notifications.

        Simulates the podcast generation workflow without making API calls.
        Sends low-priority notifications at each phase and returns mock results.

        Args:
            voice_io: Voice I/O module for notifications
            cosa_interface: COSA interface module for sender ID

        Returns:
            str: Mock conversational summary
        """
        import asyncio
        import os
        import urllib.parse

        # Set sender_id and target_user for notifications
        cosa_interface.SENDER_ID   = cosa_interface._get_sender_id( suffix=self.base_id )
        cosa_interface.TARGET_USER = self.user_email

        filename = os.path.basename( self.research_path )

        if self.debug:
            print( f"[PodcastGeneratorJob] DRY RUN MODE for: {filename}" )

        # Breadcrumb: Starting
        await voice_io.notify( f"🧪 Dry run: Starting podcast simulation from {filename}", priority="low", job_id=self.id_hash, queue_name="run" )
        await asyncio.sleep( 1.0 )

        # Breadcrumb: Content analysis
        await voice_io.notify( "🧪 Dry run: skipping content analysis", priority="low", job_id=self.id_hash, queue_name="run" )
        await asyncio.sleep( 1.0 )

        # Breadcrumb: Script generation
        await voice_io.notify( "🧪 Dry run: skipping script generation", priority="low", job_id=self.id_hash, queue_name="run" )
        await asyncio.sleep( 1.0 )

        # Breadcrumb: TTS generation
        await voice_io.notify( "🧪 Dry run: skipping TTS generation (10 segments)", priority="low", job_id=self.id_hash, queue_name="run" )
        await asyncio.sleep( 1.0 )

        # Breadcrumb: Audio stitching
        await voice_io.notify( "🧪 Dry run: skipping audio stitching", priority="low", job_id=self.id_hash, queue_name="run" )
        await asyncio.sleep( 1.0 )

        # Audio: point at the committed, pre-rendered dry-run fixture (io-relative).
        # This is a REAL mp3 that ships with the repo — Maria + Mr. Radio literally
        # narrating what dry-run mode does (rendered once from mock_clients.
        # MOCK_SCRIPT_RESPONSE via the production TTS path; see io/fixtures/
        # podcast-dry-run/README.md). Serving it exercises the entire overlay path
        # (Play Here link → &embed=1 interception → iframe render → blob-fetch auth →
        # auto-start) at zero per-run cost.
        #
        # Script stays a mock: dry-run does NOT generate a script, so that path is
        # deliberately fake and framed "(mock - not actually created)".
        audio_rel        = "fixtures/podcast-dry-run/podcast-dry-run.mp3"
        self.audio_path  = audio_rel
        self.script_path = f"/io/podcasts/{self.user_email}/dry-run-{self.id_hash}/script.md"

        # Store artifacts
        self.artifacts[ "audio_path" ]  = self.audio_path
        self.artifacts[ "script_path" ] = self.script_path
        self.artifacts[ "podcast_id" ]  = f"dry-run-{self.id_hash}"

        # Clickable audio links — same shape as the real path (job.py:346-348):
        #   Play Here → &embed=1 floating overlay (auto-starts) · Listen → standalone
        #   tab · Download → raw mp3 attachment.
        encoded     = urllib.parse.quote( audio_rel )
        audio_links = (
            f"[▶️ Play Here](/app/audio?path={encoded}&embed=1) | "
            f"[🎧 Listen](/app/audio?path={encoded}) | "
            f"[⬇️ Download](/api/io/file?path={encoded}&download=true)"
        )

        # Mock cost summary
        self.cost_summary = {
            "script_cost_usd" : 0.0,
            "audio_cost_usd"  : 0.0,
            "total_cost_usd"  : 0.0,
        }
        self.artifacts[ "cost_summary" ] = self.cost_summary

        # Phase 6 repair loop hook: deliberately fail the dry-run to exercise
        # the dead-queue watchdog + BFE auto-fix pipeline.
        if self.force_failure_mode:
            await self._raise_forced_failure( voice_io )

        completion_abstract = f"""**🧪 Dry Run Complete!**

**Script**: {self.script_path} (mock - not actually created)

**🧪 Audio**: {audio_links}

_🧪 Pre-rendered dry-run fixture — Maria & Mr. Radio narrating what dry-run mode does. Not a real podcast; no content was generated for this submission._

**Stats**: $0.00 | 10 segments | 5.0s (simulated)"""

        # Store the abstract so it rides the running→done job_state_transition
        # (running_fifo_queue.py reads artifacts.get("abstract")). Without this the
        # promoted done card renders empty ("loading…" + no Play Here) until a page
        # reload re-fetches from the persisted notification — the SAME consume bug
        # (9b481811) fixed on the real path. The dry-run path needs it too, or a
        # dry-run on stage shows a blank card.
        self.artifacts[ "abstract" ] = completion_abstract

        # Notify completion
        await voice_io.notify(
            "🧪 Dry run complete! Podcast simulation finished.",
            priority="medium",
            abstract=completion_abstract,
            job_id=self.id_hash,
            queue_name="run"
        )

        return "Dry run complete. Podcast simulation finished."


def quick_smoke_test():
    """
    Quick smoke test for PodcastGeneratorJob.
    """
    import cosa.utils.util as cu

    cu.print_banner( "PodcastGeneratorJob Smoke Test", prepend_nl=True )

    try:
        # Test 1: Import
        print( "Testing module import..." )
        from cosa.agents.podcast_generator.job import PodcastGeneratorJob
        print( "✓ Module imported successfully" )

        # Test 2: Instantiation
        print( "Testing job instantiation..." )
        job = PodcastGeneratorJob(
            research_path    = "/io/deep-research/test@test.com/test-report.md",
            user_id          = "user123",
            user_email       = "test@test.com",
            session_id       = "session456",
            target_languages = [ "en" ],
            max_segments     = 5,
            debug            = True
        )
        print( f"✓ Job created with id: {job.id_hash}" )

        # Test 3: ID format
        print( "Testing ID format..." )
        assert job.id_hash.startswith( "pg-" ), "ID should start with pg-"
        print( f"✓ ID format correct: {job.id_hash}" )

        # Test 4: last_question_asked
        print( "Testing last_question_asked..." )
        lqa = job.last_question_asked
        assert "[Podcast]" in lqa
        print( f"✓ last_question_asked: {lqa}" )

        # Test 5: is_cacheable
        print( "Testing is_cacheable property..." )
        assert job.is_cacheable == False
        print( "✓ is_cacheable correctly returns False" )

        # Test 6: Check attributes
        print( "Testing job attributes..." )
        assert job.research_path == "/io/deep-research/test@test.com/test-report.md"
        assert job.target_languages == [ "en" ]
        assert job.max_segments == 5
        assert job.user_email == "test@test.com"
        assert job.state == JobState.PENDING
        print( "✓ All attributes set correctly" )

        # Test 7: Check JOB_TYPE and JOB_PREFIX
        print( "Testing class constants..." )
        assert PodcastGeneratorJob.JOB_TYPE == "podcast"
        assert PodcastGeneratorJob.JOB_PREFIX == "pg"
        print( "✓ Class constants correct" )

        # Note: We don't test do_all() here as it requires API keys and files
        print( "\n⚠ Note: do_all() not tested (requires API keys and research doc)" )

        print( "\n✓ Smoke test completed successfully" )

    except Exception as e:
        print( f"\n✗ Smoke test failed: {e}" )
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    quick_smoke_test()
