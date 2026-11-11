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
from cosa.agents.deep_research.seed_context import normalize_source_document
from cosa.agents.podcast_generator.script_types import get_profile, validate_review
from cosa.rest.job_state import JobState


# Display labels for the completion-abstract per-language lines. Imported from the
# canonical LEAF map (row 81040071) — cosa.agents.language_names has NO heavy
# imports, so building a card does not drag in the podcast_generator package
# __init__ (mcp/pydantic, ~900 modules) the way importing config.py would. One
# copy, so the labels can never drift. Unknown codes fall back via .get(lang, lang).
from cosa.agents.language_names import LANGUAGE_NAMES as _LANGUAGE_NAMES


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

    CHAIN_TITLE          = "Research→Podcast"
    CHAIN_NOUN           = "podcast"
    DRY_RUN_ICON         = "🧪 "
    DRY_RUN_SECOND_STAGE = (
        "[PODCAST] skipping content analysis",
        "[PODCAST] skipping script generation",
        "[PODCAST] skipping TTS generation (10 segments)",
        "[PODCAST] skipping audio stitching",
    )

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
        source_document: Optional[ list ] = None,
        script_type: Optional[ str ] = None,
        review: Optional[ str ] = None,
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
            source_document: Absolute paths to local documents the research leg reads
                first, as seed context. The v2 door ( cosa/rest/v2/source_document.py )
                has already scope-validated and resolved them. This constructor receives
                real paths and does not re-decide whether they may be read. None or []
                means no seed documents.
            script_type: Script type name (research_critical or status_report); None means research_critical
            review: Review mode (ask or one_shot); None means the script type's default
            debug: Enable debug output
            verbose: Enable verbose output

        Raises:
            - ValueError when script_type or review is unknown
        """
        get_profile( script_type )
        validate_review( review )
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
        self.source_document  = normalize_source_document( source_document )
        self.script_type      = script_type
        self.review           = review

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
        return self._run_execute( "DeepResearchToPodcastJob", self.query[ :50 ], "Research→Podcast pipeline failed" )

    def _make_agent( self ):
        """
        Build the chained agent this job runs.

        This is a method, not an inline expression in `_execute`, so a test can reach the agent the job
        builds without running the whole pipeline. A test that rebuilt the argument list would prove only
        its own copy. Driving this method on a job from the real factory leaves no copy.

        Ensures:
            - returns a fully-configured agent carrying this job's own arguments
        """
        from cosa.agents.deep_research_to_podcast.agent import DeepResearchToPodcastAgent

        return DeepResearchToPodcastAgent(
            query            = self.query,
            user_email       = self.user_email,
            budget           = self.budget,
            audience         = self.audience,
            audience_context = self.audience_context,
            source_document  = self.source_document,
            target_languages = self.target_languages,
            script_type      = self.script_type,
            review           = self.review,
            max_segments     = self.max_segments,
            cli_mode         = False,  # Voice-driven mode for queue
            debug            = self.debug,
            verbose          = self.verbose,
        )

    async def _execute( self ) -> str:
        """
        Run the research→podcast pipeline, or its dry-run simulation when dry_run is set.

        Returns:
            str: Conversational summary of pipeline results
        """
        return await self._run_chained_pipeline()

    def _chain_pipeline_state( self ):
        """
        Return this pipeline's state enum, imported late so a test can fake the module graph.

        Ensures:
            - returns the PipelineState enum of deep_research_to_podcast.state
        """
        from cosa.agents.deep_research_to_podcast.state import PipelineState

        return PipelineState

    def _chain_debug_lines( self ) -> list:
        """
        Return the job-specific debug lines printed after the shared query and budget lines.

        Ensures:
            - returns a list with the target languages line
        """
        return [ f"Target languages: {self.target_languages}" ]

    def _store_chain_artifacts( self, result ) -> None:
        """
        Keep the podcast paths from a finished run on the job and in its artifacts.

        Requires:
            - result carries research_path, audio_path and script_path

        Ensures:
            - the three paths are job attributes and artifacts entries
        """
        self.research_path = result.research_path
        self.audio_path    = result.audio_path
        self.script_path   = result.script_path

        self.artifacts[ "audio_path" ]  = result.audio_path
        self.artifacts[ "script_path" ] = result.script_path

    def _chain_return_tail( self ) -> str:
        """
        Return the last sentence of the conversational answer.

        Ensures:
            - returns the audio path sentence
        """
        return f"Audio: {self.audio_path}"

    async def _chain_completion( self, result ) -> tuple:
        """
        Build the completion card for a finished run.

        Requires:
            - result is a completed ChainedResult

        Ensures:
            - the card holds per-language links and the optional Drive copy
            - returns ( abstract, spoken_suffix )
            - the suffix is empty, or names how many topics were skipped
            - a Drive folder link, when made, is stored in artifacts
        """
        import urllib.parse
        from cosa.agents.podcast_generator.play_links import audio_triplet, read_script_title, script_link, source_ref
        io_base = cu.get_project_root() + "/io/"

        def _to_rel( p ):
            if not p: return None
            if p.startswith( io_base ): return p[ len( io_base ): ]
            if p.startswith( "io/" ):   return p[ 3: ]
            return p.lstrip( "/" )

        # The original document rides the link when it lives inside the project.
        source_rel = source_ref( result.research_path, cu.get_project_root() )

        # One labelled link set for each language (bug 00e6aba1: a two-language run
        # writes two mp3s and must link both, not just the primary). The maps ride
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

        # Optional Google Drive copy (flag off = no-op and no Google import). The source document is
        # the generated research report; the hook loads the config and resolves the path inside its
        # own boundary, so a config error here cannot fail the job.
        from cosa.agents.podcast_generator.drive_hook import publish_podcast_to_drive
        drive = await publish_podcast_to_drive( audio_by_lang, script_by_lang, result.research_path, user_email=self.user_email )
        if drive[ "folder_link" ]: self.artifacts[ "drive_folder_link" ] = drive[ "folder_link" ]

        per_language_lines = []
        for lang in ordered_langs:
            label  = _LANGUAGE_NAMES.get( lang, lang )
            a_rel  = _to_rel( audio_by_lang.get( lang ) )
            s_rel  = _to_rel( script_by_lang.get( lang ) )
            parts  = []
            s_link = script_link( s_rel )
            if s_link: parts.append( s_link )
            if a_rel:
                title = read_script_title( io_base + s_rel ) if s_rel else None
                parts.append( audio_triplet( a_rel, s_rel, source_rel, title ) )
            if lang in drive[ "language_links" ]: parts.append( f"[☁️ Drive]({drive[ 'language_links' ][ lang ]})" )
            if parts:
                per_language_lines.append( f"**{label}**: " + " | ".join( parts ) )

        lines   = [ "**Research → Podcast Complete!**", "" ]
        r_rel   = _to_rel( result.research_path )
        if r_rel:
            lines.append( f"**Research Report**: [📄 View](/app/docs?path={urllib.parse.quote( r_rel )})" )
        lines.extend( per_language_lines )
        lines.extend( drive[ "extra_lines" ] )
        skipped_names = [ g[ "topic" ] for g in result.dr_artifacts.get( "skipped_topics", [] ) ]
        if skipped_names:
            lines.append( f"**Skipped topics ({len( skipped_names )})**: " + "; ".join( skipped_names ) )
        lines.append( f"**Cost**: ${result.total_cost:.4f}" )
        completion_abstract = "\n".join( lines )

        spoken_suffix = f" {len( skipped_names )} topics were skipped; see the card." if skipped_names else ""
        return completion_abstract, spoken_suffix

    def _store_dry_run_results( self ) -> str:
        """
        Store the mock podcast results of a dry run.

        Ensures:
            - mock paths are job attributes and artifacts entries
            - returns the dry-run completion abstract
        """
        self.research_path = f"/io/deep-research/{self.user_email}/dry-run-{self.id_hash}/report.md"
        self.audio_path    = f"/io/podcasts/{self.user_email}/dry-run-{self.id_hash}/podcast.mp3"
        self.script_path   = f"/io/podcasts/{self.user_email}/dry-run-{self.id_hash}/script.md"

        self.artifacts[ "research_path" ]     = self.research_path
        self.artifacts[ "research_abstract" ] = "Mock abstract from dry-run mode."
        self.artifacts[ "audio_path" ]        = self.audio_path
        self.artifacts[ "script_path" ]       = self.script_path

        return f"""**🧪 Dry Run Complete!**

**Research Report**: {self.research_path} (mock - not actually created)

**Podcast Script**: {self.script_path} (mock - not actually created)

**Podcast Audio**: {self.audio_path} (mock - not actually created)

**Stats**: $0.00 total | 0 tokens | 10.0s (simulated)"""


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
