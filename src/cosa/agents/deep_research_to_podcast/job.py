"""
Deep Research to Podcast background job for queue-based execution.

Wraps the existing DeepResearchToPodcastAgent functionality for execution
within the COSA queue system. Enables users to submit chained research→podcast
workflows via the API and receive results asynchronously.

Example:
    job = DeepResearchToPodcastJob(
        query          = "State of AI safety in 2026",
        user_id        = "user123",
        user_email     = "user@example.com",
        session_id     = "wise-penguin",
        budget         = 3.00,
        target_languages = [ "en" ],
        max_segments   = None,
        debug          = True
    )
    result = job.do_all()  # Runs full pipeline and returns conversational answer
"""

import asyncio
from datetime import datetime
from typing import Optional, List

import cosa.utils.util as cu
from cosa.agents.agentic_job_base import AgenticJobBase
from cosa.rest.job_state import JobState


# Display labels for the completion-abstract per-language lines. Kept local (not
# imported from cosa.agents.podcast_generator.config) so building a card does not
# drag in the whole podcast_generator package __init__ at runtime — that chain
# pulls mcp/pydantic and is heavier than a text abstract needs. Unknown codes fall
# back to the raw code via .get(lang, lang). Mirror of that module's LANGUAGE_NAMES.
_LANGUAGE_NAMES = {
    "en"    : "English",
    "es"    : "Spanish",
    "es-ES" : "Castilian Spanish (Spain)",
    "es-MX" : "Mexican Spanish",
    "es-AR" : "Argentinian Spanish",
}


class DeepResearchToPodcastJob( AgenticJobBase ):
    """
    Background job for Deep Research → Podcast pipeline execution.

    Runs a chained workflow:
    1. Deep Research: Web search, synthesis, report generation
    2. Podcast Generation: Script creation, TTS, audio stitching

    Sends progress notifications via cosa-voice and completion notification
    with links to all generated artifacts.

    Attributes:
        query: The research topic/question to investigate
        budget: Maximum budget in USD for Deep Research (None = unlimited)
        target_languages: List of ISO language codes for audio generation
        max_segments: Limit TTS to first N segments (cost control)
        research_path: Path to generated research report (set after completion)
        audio_path: Path to generated audio (set after completion)
        script_path: Path to generated script (set after completion)
        cost_summary: Combined execution cost summary (set after completion)
    """

    JOB_TYPE   = "research_to_podcast"
    JOB_PREFIX = "rp"

    def __init__(
        self,
        query: str,
        user_id: str,
        user_email: str,
        session_id: str,
        budget: Optional[ float ] = None,
        target_languages: Optional[ List[ str ] ] = None,
        max_segments: Optional[ int ] = None,
        dry_run: bool = False,
        audience: Optional[ str ] = None,
        audience_context: Optional[ str ] = None,
        debug: bool = False,
        verbose: bool = False
    ) -> None:
        """
        Initialize a Deep Research to Podcast job.

        Requires:
            - query is a non-empty string
            - user_id is a valid system ID
            - user_email is a valid email address
            - session_id is a WebSocket session ID

        Ensures:
            - Job ID generated with "rp-" prefix
            - All parameters stored for execution

        Args:
            query: The research topic/question to investigate
            user_id: System ID of the job owner
            user_email: Email address for output storage
            session_id: WebSocket session for notifications
            budget: Maximum budget in USD for Deep Research (None = unlimited)
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

        # Pipeline parameters
        self.query            = query
        self.budget           = budget
        self.target_languages = target_languages or [ "en" ]
        self.max_segments     = max_segments
        self.dry_run          = dry_run
        self.audience         = audience
        self.audience_context = audience_context

        # Results (populated after execution)
        self.research_path = None
        self.audio_path    = None
        self.script_path   = None
        self.cost_summary  = None

    @property
    def last_question_asked( self ) -> str:
        """
        Display string for queue UI.

        Returns truncated query with [Research→Podcast] prefix.

        Returns:
            str: Human-readable job description
        """
        return f"[Research→Podcast] {self.query}"

    def do_all( self ) -> str:
        """
        Execute research→podcast pipeline and return conversational answer.

        This is the main entry point called by RunningFifoQueue.
        Bridges to the async _execute() method via asyncio.run().

        Returns:
            str: Conversational answer summarizing pipeline results
        """
        if self.debug:
            print( f"[DeepResearchToPodcastJob] Starting do_all() for: {self.query[ :50 ]}..." )

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
                print( f"[DeepResearchToPodcastJob] Completed in {duration:.1f}s" )

            return result

        except Exception as e:
            self.state        = JobState.FAILED
            self.completed_at = cu.get_current_datetime_iso()
            self.error        = str( e )
            self.answer_conversational = f"Research→Podcast pipeline failed: {str( e )}"

            if self.debug:
                print( f"[DeepResearchToPodcastJob] Failed: {e}" )
                import traceback
                traceback.print_exc()

            # Re-raise so the agentic-pool Future captures the exception.
            # Backlog item 5 (2026-04-29): canonical Future contract.
            raise

    async def _execute( self ) -> str:
        """
        Internal async pipeline execution.

        Uses the DeepResearchToPodcastAgent to run the full workflow.
        When dry_run=True, sends breadcrumb notifications and returns mock results.

        Returns:
            str: Conversational summary of pipeline results
        """
        from cosa.agents.deep_research import voice_io, cosa_interface

        # Handle dry-run mode with breadcrumb notifications
        if self.dry_run:
            return await self._execute_dry_run( voice_io, cosa_interface )

        # Import pipeline components
        from cosa.agents.deep_research_to_podcast.agent import DeepResearchToPodcastAgent
        from cosa.agents.deep_research_to_podcast.state import PipelineState

        # Set sender_id and target_user for notifications (use base_id to strip ::user_id scope suffix)
        cosa_interface.SENDER_ID   = cosa_interface._get_sender_id( suffix=self.base_id )
        cosa_interface.TARGET_USER = self.user_email

        # Set job_id for auto-injection into all downstream notify() calls (same pattern as DeepResearchJob)
        voice_io.set_job_id( self.id_hash )

        if self.debug:
            print( f"[DeepResearchToPodcastJob] Query: {self.query[ :80 ]}..." )
            print( f"[DeepResearchToPodcastJob] Budget: ${self.budget}" if self.budget else "[DeepResearchToPodcastJob] Budget: unlimited" )
            print( f"[DeepResearchToPodcastJob] Target languages: {self.target_languages}" )

        try:
            # Notify start
            await voice_io.notify(
                f"Starting research→podcast pipeline: {self.query[ :60 ]}...",
                priority="medium",
                job_id=self.id_hash,
                queue_name="run"
            )

            # Create the chained agent
            agent = DeepResearchToPodcastAgent(
                query            = self.query,
                user_email       = self.user_email,
                budget           = self.budget,
                audience         = self.audience,
                audience_context = self.audience_context,
                target_languages = self.target_languages,
                max_segments     = self.max_segments,
                cli_mode         = False,  # Voice-driven mode for queue
                debug            = self.debug,
                verbose          = self.verbose,
            )

            # Run the full pipeline
            result = await agent.run_async()

            # Check result state
            if result.state == PipelineState.CANCELLED:
                await voice_io.notify( "Pipeline was cancelled.", priority="medium", job_id=self.id_hash, queue_name="run" )
                return "Research→Podcast pipeline was cancelled by the user."

            if result.state == PipelineState.FAILED:
                error_msg = result.error or "Unknown error"
                await voice_io.notify( f"Pipeline failed: {error_msg[ :80 ]}", priority="urgent", job_id=self.id_hash, queue_name="run" )
                raise Exception( error_msg )

            # Store results
            self.research_path = result.research_path
            self.audio_path    = result.audio_path
            self.script_path   = result.script_path

            # Store artifacts
            self.artifacts[ "research_path" ]     = result.research_path
            self.artifacts[ "research_abstract" ] = result.research_abstract
            self.artifacts[ "audio_path" ]        = result.audio_path
            self.artifacts[ "script_path" ]       = result.script_path

            # Build cost summary
            self.cost_summary = {
                "dr_cost_usd"    : result.dr_cost,
                "pg_cost_usd"    : result.pg_cost,
                "total_cost_usd" : result.total_cost,
            }
            self.artifacts[ "cost_summary" ] = self.cost_summary

            # ── Completion report: build a rich abstract with clickable per-language
            #    links so the promoted running→done card renders Play Here WITHOUT a
            #    page reload. Before this, the real path returned a bare "Pipeline
            #    complete!" string and stored NO abstract, so _transition_to_done
            #    emitted abstract=None → blank done card (bug 2da4095a; sibling of
            #    9b481811, but a missing BUILD, not just a missing store). Mirrors
            #    podcast_generator/job.py:358-406. ──
            import urllib.parse
            io_base = cu.get_project_root() + "/io/"

            def _to_rel( p ):
                if not p: return None
                if p.startswith( io_base ): return p[ len( io_base ): ]
                if p.startswith( "io/" ):   return p[ 3: ]
                return p.lstrip( "/" )

            def _script_link( rel ):
                return f"[📝 Script](/app/docs?path={urllib.parse.quote( rel )})" if rel else None

            def _audio_triplet( rel ):
                enc = urllib.parse.quote( rel )
                return (
                    f"[▶️ Play Here](/app/audio?path={enc}&embed=1) | "
                    f"[🎧 Listen](/app/audio?path={enc}) | "
                    f"[⬇️ Download](/api/io/file?path={enc}&download=true)"
                )

            # One labelled link set PER language (bug 00e6aba1: a two-language run
            # writes two mp3s but must link BOTH, not just the primary). The maps ride
            # pg_artifacts from the orchestrator; fall back to the single primary path
            # for single-language / older state so the loop below stays uniform.
            audio_by_lang  = dict( result.pg_artifacts.get( "audio_paths_by_language" )  or {} )
            script_by_lang = dict( result.pg_artifacts.get( "script_paths_by_language" ) or {} )
            languages      = self.target_languages or [ "en" ]
            if not audio_by_lang and result.audio_path:
                audio_by_lang = { languages[ 0 ]: result.audio_path }
            if not script_by_lang and result.script_path:
                script_by_lang = { languages[ 0 ]: result.script_path }

            # Requested order first, then any extra language that produced an artifact.
            ordered_langs = [ l for l in languages if l in audio_by_lang or l in script_by_lang ]
            for l in list( audio_by_lang ) + list( script_by_lang ):
                if l not in ordered_langs:
                    ordered_langs.append( l )

            per_language_lines = []
            for lang in ordered_langs:
                label  = _LANGUAGE_NAMES.get( lang, lang )
                a_rel  = _to_rel( audio_by_lang.get( lang ) )
                s_rel  = _to_rel( script_by_lang.get( lang ) )
                parts  = []
                s_link = _script_link( s_rel )
                if s_link: parts.append( s_link )
                if a_rel:  parts.append( _audio_triplet( a_rel ) )
                if parts:
                    per_language_lines.append( f"**{label}**: " + " | ".join( parts ) )

            lines   = [ "**Research → Podcast Complete!**", "" ]
            r_rel   = _to_rel( result.research_path )
            if r_rel:
                lines.append( f"**Research Report**: [📄 View](/app/docs?path={urllib.parse.quote( r_rel )})" )
            lines.extend( per_language_lines )
            lines.append( f"**Cost**: ${result.total_cost:.4f}" )
            completion_abstract = "\n".join( lines )

            # Store the abstract in artifacts so it rides the running→done transition
            # (running_fifo_queue._transition_to_done reads artifacts.get("abstract")).
            self.artifacts[ "abstract" ] = completion_abstract

            try:
                await voice_io.notify(
                    f"Research to podcast complete. Total cost ${result.total_cost:.4f}.",
                    priority   = "medium",
                    abstract   = completion_abstract,
                    job_id     = self.id_hash,
                    queue_name = "run",
                )
            except Exception as notify_err:
                print( f"[DeepResearchToPodcastJob] completion notify failed: {notify_err}" )

            # Return conversational answer
            return f"Pipeline complete! Research report and podcast generated. Total cost: ${result.total_cost:.4f}. Audio: {self.audio_path}"

        finally:
            voice_io.clear_job_id()

    async def _execute_dry_run( self, voice_io, cosa_interface ) -> str:
        """
        Execute dry-run mode with breadcrumb notifications.

        Simulates the full research→podcast pipeline without making API calls.
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
            print( f"[DeepResearchToPodcastJob] DRY RUN MODE for: {self.query[ :50 ]}..." )

        # === Deep Research Phase Breadcrumbs ===
        await voice_io.notify( f"🧪 Dry run: Starting research→podcast simulation", priority="low", job_id=self.id_hash, queue_name="run" )
        await asyncio.sleep( 1.0 )

        await voice_io.notify( "🧪 Dry run: [RESEARCH] skipping query clarification", priority="low", job_id=self.id_hash, queue_name="run" )
        await asyncio.sleep( 1.0 )

        await voice_io.notify( "🧪 Dry run: [RESEARCH] skipping research planning", priority="low", job_id=self.id_hash, queue_name="run" )
        await asyncio.sleep( 1.0 )

        await voice_io.notify( "🧪 Dry run: [RESEARCH] skipping subquery research (5 queries)", priority="low", job_id=self.id_hash, queue_name="run" )
        await asyncio.sleep( 1.0 )

        await voice_io.notify( "🧪 Dry run: [RESEARCH] skipping report synthesis", priority="low", job_id=self.id_hash, queue_name="run" )
        await asyncio.sleep( 1.0 )

        await voice_io.notify( "🧪 Dry run: [RESEARCH] skipping report write to disk", priority="low", job_id=self.id_hash, queue_name="run" )
        await asyncio.sleep( 1.0 )

        # === Podcast Generation Phase Breadcrumbs ===
        await voice_io.notify( "🧪 Dry run: [PODCAST] skipping content analysis", priority="low", job_id=self.id_hash, queue_name="run" )
        await asyncio.sleep( 1.0 )

        await voice_io.notify( "🧪 Dry run: [PODCAST] skipping script generation", priority="low", job_id=self.id_hash, queue_name="run" )
        await asyncio.sleep( 1.0 )

        await voice_io.notify( "🧪 Dry run: [PODCAST] skipping TTS generation (10 segments)", priority="low", job_id=self.id_hash, queue_name="run" )
        await asyncio.sleep( 1.0 )

        await voice_io.notify( "🧪 Dry run: [PODCAST] skipping audio stitching", priority="low", job_id=self.id_hash, queue_name="run" )
        await asyncio.sleep( 1.0 )

        # Set mock results
        self.research_path = f"/io/deep-research/{self.user_email}/dry-run-{self.id_hash}/report.md"
        self.audio_path    = f"/io/podcasts/{self.user_email}/dry-run-{self.id_hash}/podcast.mp3"
        self.script_path   = f"/io/podcasts/{self.user_email}/dry-run-{self.id_hash}/script.md"

        # Store mock artifacts
        self.artifacts[ "research_path" ]     = self.research_path
        self.artifacts[ "research_abstract" ] = "Mock abstract from dry-run mode."
        self.artifacts[ "audio_path" ]        = self.audio_path
        self.artifacts[ "script_path" ]       = self.script_path

        # Mock cost summary
        self.cost_summary = {
            "dr_cost_usd"    : 0.0,
            "pg_cost_usd"    : 0.0,
            "total_cost_usd" : 0.0,
        }
        self.artifacts[ "cost_summary" ] = self.cost_summary

        completion_abstract = f"""**🧪 Dry Run Complete!**

**Research Report**: {self.research_path} (mock - not actually created)

**Podcast Script**: {self.script_path} (mock - not actually created)

**Podcast Audio**: {self.audio_path} (mock - not actually created)

**Stats**: $0.00 total | 0 tokens | 10.0s (simulated)"""

        # Store the abstract in artifacts so it rides the running→done transition (bug 9b481811 sweep)
        self.artifacts[ "abstract" ] = completion_abstract

        # Notify completion
        await voice_io.notify(
            "🧪 Dry run complete! Pipeline simulation finished.",
            priority="medium",
            abstract=completion_abstract,
            job_id=self.id_hash,
            queue_name="run"
        )

        voice_io.clear_job_id()
        return "Dry run complete. Research and podcast simulation finished."


def quick_smoke_test():
    """
    Quick smoke test for DeepResearchToPodcastJob.
    """
    import cosa.utils.util as cu

    cu.print_banner( "DeepResearchToPodcastJob Smoke Test", prepend_nl=True )

    try:
        # Test 1: Import
        print( "Testing module import..." )
        from cosa.agents.deep_research_to_podcast.job import DeepResearchToPodcastJob
        print( "✓ Module imported successfully" )

        # Test 2: Instantiation
        print( "Testing job instantiation..." )
        job = DeepResearchToPodcastJob(
            query            = "test query for smoke test",
            user_id          = "user123",
            user_email       = "test@test.com",
            session_id       = "session456",
            budget           = 2.00,
            target_languages = [ "en" ],
            max_segments     = 5,
            debug            = True
        )
        print( f"✓ Job created with id: {job.id_hash}" )

        # Test 3: ID format
        print( "Testing ID format..." )
        assert job.id_hash.startswith( "rp-" ), "ID should start with rp-"
        print( f"✓ ID format correct: {job.id_hash}" )

        # Test 4: last_question_asked
        print( "Testing last_question_asked..." )
        lqa = job.last_question_asked
        assert "[Research→Podcast]" in lqa
        print( f"✓ last_question_asked: {lqa}" )

        # Test 5: is_cacheable
        print( "Testing is_cacheable property..." )
        assert job.is_cacheable == False
        print( "✓ is_cacheable correctly returns False" )

        # Test 6: Check attributes
        print( "Testing job attributes..." )
        assert job.query == "test query for smoke test"
        assert job.budget == 2.00
        assert job.target_languages == [ "en" ]
        assert job.max_segments == 5
        assert job.user_email == "test@test.com"
        assert job.state == JobState.PENDING
        print( "✓ All attributes set correctly" )

        # Test 7: Check JOB_TYPE and JOB_PREFIX
        print( "Testing class constants..." )
        assert DeepResearchToPodcastJob.JOB_TYPE == "research_to_podcast"
        assert DeepResearchToPodcastJob.JOB_PREFIX == "rp"
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
