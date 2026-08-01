#!/usr/bin/env python3
"""
Podcast Orchestrator Agent - Top-level coordinator for podcast generation.

This agent manages the entire podcast generation workflow internally as a single
queue entry, yielding control at I/O boundaries via async/await.

Design Pattern: Top-Level Orchestrator
- Single job in queue, multi-phase internal state machine
- Async execution for non-blocking queue behavior
- Queryable state for external monitoring
- Controllable via pause/resume/stop

Phase 1 (This File): Script generation from research documents
Phase 2 (Future): TTS audio generation and stitching
"""

import asyncio
import time
import logging
import os
import urllib.parse
import uuid
from typing import Optional, List, Tuple
from datetime import datetime

from .config import PodcastConfig
from .state import (
    OrchestratorState,
    PodcastState,
    PodcastScript,
    ScriptSegment,
    ContentAnalysis,
    PodcastMetadata,
    create_initial_state,
    validate_prosody_preservation,
)
from .config import LANGUAGE_NAMES
from . import cosa_interface
from . import voice_io
from .api_client import PodcastAPIClient
from .tts_client import PodcastTTSClient, TTSSegmentResult
from .audio_stitcher import PodcastAudioStitcher, StitchingResult
from .prompts import (
    SCRIPT_GENERATION_SYSTEM_PROMPT,
    CONTENT_ANALYSIS_SYSTEM_PROMPT,
    get_script_generation_prompt,
    get_content_analysis_prompt,
    get_script_revision_prompt,
    parse_script_response,
    parse_analysis_response,
    get_dynamic_duo_description,
)

logger = logging.getLogger( __name__ )

# ElevenLabs pricing (standard tier)
ELEVENLABS_COST_PER_1K_CHARS = 0.30  # $0.30 per 1000 characters


class PodcastGenerationError( Exception ):
    """
    Raised when a core LLM-backed generation step (content analysis or script
    generation) fails, so the job fails LOUDLY instead of silently producing a
    fake placeholder script that reaches the review gate looking review-ready.

    Requires:
        - message is a non-empty, user-facing string

    Ensures:
        - carries a clear user-facing message up to the run() handler, which
          sets state=FAILED, notifies the user, and re-raises
    """
    pass


class PodcastOrchestratorAgent:
    """
    Top-level orchestrator for podcast generation - single job, multi-phase, async.

    This is a standalone class (not inheriting from AgentBase) because:
    - AgentBase is synchronous, this is async
    - Different execution model (yields on await vs blocking)
    - Composition over inheritance for COSA integration

    Requires:
        - research_doc_path points to a valid file
        - user_id is a valid system identifier

    Ensures:
        - Manages entire podcast workflow internally
        - Yields control at I/O boundaries (await points)
        - State is queryable via get_state()
        - Can be paused, resumed, or stopped externally
    """

    def __init__(
        self,
        research_doc_path  : str,
        user_id            : str,
        config             : Optional[ PodcastConfig ] = None,
        max_segments       : Optional[ int ] = None,
        target_languages   : Optional[ List[ str ] ] = None,
        debug              : bool = False,
        verbose            : bool = False
    ):
        """
        Initialize the podcast orchestrator.

        Args:
            research_doc_path: Path to the Deep Research markdown document
            user_id: System user ID for event routing
            config: Podcast configuration (uses defaults if None)
            max_segments: Limit TTS to first N segments (for cost control)
            target_languages: List of ISO language codes (default: from config or ["en"])
            debug: Enable debug output
            verbose: Enable verbose output
        """
        self.research_doc_path = research_doc_path
        self.user_id           = user_id
        self.config            = config or PodcastConfig()
        self.max_segments      = max_segments
        self.debug             = debug
        self.verbose           = verbose

        # Set target languages (CLI arg > config > default ["en"])
        if target_languages is not None:
            self.target_languages = target_languages
        elif self.config.target_languages:
            self.target_languages = self.config.target_languages
        else:
            self.target_languages = [ "en" ]

        # State management
        self.state = OrchestratorState.LOADING_RESEARCH
        self._pause_requested = False
        self._stop_requested  = False

        # Initialize internal state (TypedDict for tracking)
        self._podcast_state = create_initial_state( research_doc_path, user_id )

        # Generate podcast ID
        self.podcast_id = f"podcast-{uuid.uuid4().hex[ :8 ]}"

        # Initialize API client (lazy - created on first use)
        self._api_client: Optional[ PodcastAPIClient ] = None

        # Initialize TTS client and audio stitcher (lazy - created on first use)
        self._tts_client: Optional[ PodcastTTSClient ] = None
        self._audio_stitcher: Optional[ PodcastAudioStitcher ] = None

        # Track original script path for revisions (to preserve filename)
        self._original_script_path: Optional[ str ] = None

        # Progress group IDs for in-place DOM updates
        self._audio_progress_group_id = None

        # Metrics
        self.metrics = {
            "start_time"  : None,
            "end_time"    : None,
            "api_calls"   : 0,
            "tokens_used" : 0,
        }

        if self.debug:
            print( f"[PodcastOrchestratorAgent] Initialized for: {research_doc_path}" )
            print( f"[PodcastOrchestratorAgent] Podcast ID: {self.podcast_id}" )

    @property
    def api_client( self ) -> PodcastAPIClient:
        """Lazy initialization of API client."""
        if self._api_client is None:
            self._api_client = PodcastAPIClient(
                config  = self.config,
                debug   = self.debug,
                verbose = self.verbose,
            )
        return self._api_client

    @property
    def tts_client( self ) -> PodcastTTSClient:
        """Lazy initialization of TTS client."""
        if self._tts_client is None:
            self._tts_client = PodcastTTSClient(
                config_mgr        = None,  # Will use defaults from config
                progress_callback = self._audio_progress_callback,
                retry_callback    = self._audio_retry_callback,
                debug             = self.debug,
                verbose           = self.verbose,
            )
        return self._tts_client

    @property
    def audio_stitcher( self ) -> PodcastAudioStitcher:
        """Lazy initialization of audio stitcher."""
        if self._audio_stitcher is None:
            self._audio_stitcher = PodcastAudioStitcher(
                silence_between_speakers_ms = self.config.silence_between_speakers_ms,
                audio_bitrate               = self.config.audio_bitrate,
                debug                       = self.debug,
                verbose                     = self.verbose,
            )
        return self._audio_stitcher

    @classmethod
    async def from_saved_script(
        cls,
        script_path      : str,
        user_id          : str,
        config           : Optional[ PodcastConfig ] = None,
        max_segments     : Optional[ int ] = None,
        target_languages : Optional[ List[ str ] ] = None,
        debug            : bool = False,
        verbose          : bool = False
    ) -> "PodcastOrchestratorAgent":
        """
        Create orchestrator from a saved script, skipping generation phases.

        Loads an existing script markdown file and creates an orchestrator
        ready to enter the review/revision workflow directly.

        Requires:
            - script_path points to a valid podcast script markdown file
            - user_id is a valid identifier

        Ensures:
            - Returns orchestrator with script pre-loaded
            - State is set to WAITING_SCRIPT_REVIEW
            - Revision count is preserved from loaded script

        Args:
            script_path: Path to saved script markdown file
            user_id: User identifier for output directory
            config: Podcast configuration (uses defaults if None)
            max_segments: Limit TTS to first N segments (for cost control)
            target_languages: List of ISO language codes (default: from config or ["en"])
            debug: Enable debug output
            verbose: Enable verbose output

        Returns:
            PodcastOrchestratorAgent: Ready for review workflow
        """
        import cosa.utils.util as cu

        # Resolve path
        if not script_path.startswith( "/" ):
            script_path = cu.get_project_root() + "/" + script_path

        # Load and parse script
        with open( script_path, "r", encoding="utf-8" ) as f:
            markdown_content = f.read()

        script = PodcastScript.from_markdown( markdown_content )

        # Create orchestrator with dummy research path (not used in edit mode)
        agent = cls(
            research_doc_path = script.research_source or "edit-mode",
            user_id           = user_id,
            config            = config,
            max_segments      = max_segments,
            target_languages  = target_languages,
            debug             = debug,
            verbose           = verbose,
        )

        # Pre-populate state
        agent._podcast_state[ "draft_script" ]      = script
        agent._podcast_state[ "draft_script_path" ] = script_path
        agent._podcast_state[ "revision_count" ]    = script.revision_count
        agent.state = OrchestratorState.WAITING_SCRIPT_REVIEW

        # Preserve original path for revisions (prevents filename changes)
        agent._original_script_path = script_path

        if debug:
            print( f"[PodcastOrchestratorAgent] Loaded script from: {script_path}" )
            print( f"[PodcastOrchestratorAgent] Title: {script.title}" )
            print( f"[PodcastOrchestratorAgent] Segments: {script.get_segment_count()}" )

        return agent

    async def do_all_async( self ) -> Optional[ PodcastScript ]:
        """
        Main execution - yields on I/O, doesn't block other jobs.

        Phase 1 Implementation:
        1. Load research document
        2. Analyze content for key topics
        3. Generate podcast script
        4. Wait for script review
        5. Save script to file

        Requires:
            - Research document exists and is readable
            - COSA interface is configured (for human feedback)

        Ensures:
            - Executes complete script generation workflow
            - Returns PodcastScript on success, None on cancellation
            - Updates state throughout execution

        Returns:
            PodcastScript or None: Generated script, or None if cancelled
        """
        self.metrics[ "start_time" ] = time.time()

        try:
            # =================================================================
            # Phase 1: Load Research Document
            # =================================================================
            self.state = OrchestratorState.LOADING_RESEARCH
            await voice_io.notify(
                "Starting podcast generation - loading research document..."
            )

            research_content = await self._load_research_async()
            if not research_content:
                raise ValueError( f"Could not load research document: {self.research_doc_path}" )

            self._podcast_state[ "research_content" ] = research_content

            if self._check_stop(): return await self._handle_stop()

            # =================================================================
            # Phase 2: Analyze Content
            # =================================================================
            self.state = OrchestratorState.ANALYZING_CONTENT
            await voice_io.notify( "Analyzing content for key topics..." )

            analysis = await self._analyze_content_async( research_content )
            self._podcast_state[ "content_analysis" ] = analysis
            self._podcast_state[ "topics_extracted" ] = True

            if self.debug:
                print( f"[PodcastOrchestratorAgent] Analysis complete: {analysis.main_topic}" )
                print( f"[PodcastOrchestratorAgent] Key subtopics: {analysis.key_subtopics}" )

            if self._check_stop(): return await self._handle_stop()

            # =================================================================
            # Phase 3: Generate Script
            # =================================================================
            self.state = OrchestratorState.GENERATING_SCRIPT
            await voice_io.notify(
                f"Generating podcast script about {analysis.main_topic}..."
            )

            script = await self._generate_script_async( research_content, analysis )
            self._podcast_state[ "draft_script" ] = script

            if self.debug:
                print( f"[PodcastOrchestratorAgent] Script generated: {script.get_segment_count()} segments" )

            if self._check_stop(): return await self._handle_stop()

            # =================================================================
            # Phase 4: Script Review - ITERATIVE LOOP
            # =================================================================
            script_approved = False
            script_path     = None  # Track current script location

            while not script_approved:
                self.state = OrchestratorState.WAITING_SCRIPT_REVIEW

                # Save script as draft for review (so user can access full script via link)
                if script_path is None:
                    if self._original_script_path:
                        script_path = self._original_script_path
                    else:
                        # First generation - save as draft
                        script.revision_count = self._podcast_state[ "revision_count" ]
                        script_path = await self._save_script_async( script )
                        self._podcast_state[ "draft_script_path" ] = script_path

                # Build clickable link to full script using /api/io/file endpoint
                import cosa.utils.util as cu
                io_base = cu.get_project_root() + "/io/"
                if script_path and script_path.startswith( io_base ):
                    rel_path    = script_path.replace( io_base, "" )
                    script_link = f"[View Full Script](/app/docs?path={urllib.parse.quote( rel_path )})"
                else:
                    script_link = f"`{script_path}`"

                # Present script preview for approval, including clickable link
                script_preview = self._get_script_preview( script )
                script_preview += f"\n\n**Full Script**: {script_link}"

                revision_label = f" (Revision {self._podcast_state[ 'revision_count' ]})" if self._podcast_state[ "revision_count" ] > 0 else ""

                choice = await voice_io.present_choices(
                    questions = [ {
                        "question"    : "Podcast script is ready. How would you like to proceed?",
                        "header"      : "Script Review",
                        "multiSelect" : False,
                        "options"     : [
                            { "label": "Approve script", "description": "Keep script and continue" },
                            { "label": "Revise script", "description": "Provide feedback for changes" },
                            { "label": "Cancel", "description": "Discard script and stop" }
                        ]
                    } ],
                    timeout  = self.config.script_review_timeout_seconds,
                    abstract = script_preview,
                    title    = f"Script Review{revision_label}",
                )

                review_choice = choice.get( "answers", {} ).get( "Script Review", "" )

                if review_choice == "Cancel":
                    self.state = OrchestratorState.STOPPED
                    await voice_io.notify( "Podcast generation cancelled." )
                    return None

                elif review_choice == "Approve script":
                    # Explicit approval - save and exit loop
                    script.revision_count = self._podcast_state[ "revision_count" ]
                    script_path = await self._save_script_async( script )
                    self._podcast_state[ "draft_script_path" ] = script_path
                    script_approved = True

                else:
                    # "Revise script" or "Other" with custom text
                    if review_choice == "Revise script":
                        feedback = await voice_io.get_input(
                            "What changes would you like to the script?",
                            timeout = self.config.feedback_timeout_seconds
                        )
                    else:
                        # "Other" - custom text IS the feedback
                        feedback = review_choice

                    if feedback:
                        self._podcast_state[ "human_feedback" ] = feedback
                        self._podcast_state[ "revision_count" ] += 1

                        # Revise script
                        self.state = OrchestratorState.GENERATING_SCRIPT
                        await voice_io.notify( f"Revising script (revision {self._podcast_state[ 'revision_count' ]})..." )

                        script = await self._revise_script_async( script, feedback )
                        self._podcast_state[ "draft_script" ] = script

                        # Save revision with version suffix (e.g., -v2.md)
                        script.revision_count = self._podcast_state[ "revision_count" ]
                        script_path = await self._save_script_async( script, is_revision=True )
                        self._podcast_state[ "draft_script_path" ] = script_path

                        # Loop continues - will show revised script for review again

                if self._check_stop(): return await self._handle_stop()

            self._podcast_state[ "script_approved" ] = True
            self._podcast_state[ "final_script_path" ] = script_path

            # =================================================================
            # Phase 4b: Generate Additional Language Versions
            # =================================================================
            import cosa.utils.util as cu

            scripts_by_language = {}
            script_paths_by_language = {}

            # Only include English audio if explicitly requested
            if "en" in self.target_languages:
                scripts_by_language[ "en" ] = script
                script_paths_by_language[ "en" ] = script_path

            non_english_languages = [ lang for lang in self.target_languages if lang != "en" ]

            if non_english_languages:
                lang_count = len( non_english_languages )
                if "en" in self.target_languages:
                    await voice_io.notify(
                        f"English script approved. Now generating {lang_count} additional language version(s)...",
                        priority = "medium"
                    )
                else:
                    await voice_io.notify(
                        f"Script approved. Now generating {lang_count} language version(s): {', '.join( non_english_languages )}...",
                        priority = "medium"
                    )

            for lang in non_english_languages:
                lang_name = LANGUAGE_NAMES.get( lang, lang )

                # Notify: Starting translation
                await voice_io.notify(
                    f"Generating {lang_name} version of the script...",
                    priority = "low"
                )

                # Generate translated script
                translated_script = await self._generate_translated_script_async( script, lang )
                scripts_by_language[ lang ] = translated_script

                # Save translated script
                translated_path = await self._save_script_async( translated_script, language=lang )
                script_paths_by_language[ lang ] = translated_path

                if self._check_stop(): return await self._handle_stop()

                # Build clickable link for translated script
                io_base = cu.get_project_root() + "/io/"
                if translated_path.startswith( io_base ):
                    rel_path = translated_path.replace( io_base, "" )
                    translated_link = f"[View {lang_name} Script](/app/docs?path={urllib.parse.quote( rel_path )})"
                else:
                    translated_link = f"`{translated_path}`"

                # Review loop for translated script
                translated_approved = False
                while not translated_approved:
                    # Notify: Ready for review
                    await voice_io.notify(
                        f"{lang_name} script ready for review",
                        priority = "medium"
                    )

                    # Present for approval
                    translated_preview = self._get_script_preview( translated_script )
                    translated_preview += f"\n\n**Full Script**: {translated_link}"

                    choice = await voice_io.present_choices(
                        questions = [ {
                            "question"    : f"How would you like to proceed with the {lang_name} script?",
                            "header"      : f"{lang_name} Review",
                            "multiSelect" : False,
                            "options"     : [
                                { "label": "Approve script", "description": f"Keep {lang_name} script and continue" },
                                { "label": "Revise script", "description": "Provide feedback for changes" },
                                { "label": "Skip language", "description": f"Skip {lang_name} version entirely" }
                            ]
                        } ],
                        timeout  = self.config.script_review_timeout_seconds,
                        abstract = translated_preview,
                        title    = f"{lang_name} Script Review",
                    )

                    review_choice = choice.get( "answers", {} ).get( f"{lang_name} Review", "" )

                    if review_choice == "Skip language":
                        await voice_io.notify( f"Skipping {lang_name} version." )
                        del scripts_by_language[ lang ]
                        del script_paths_by_language[ lang ]
                        translated_approved = True  # Exit loop

                    elif review_choice == "Approve script":
                        translated_approved = True

                    else:
                        # Revise
                        if review_choice == "Revise script":
                            feedback = await voice_io.get_input(
                                f"What changes would you like to the {lang_name} script?",
                                timeout = self.config.feedback_timeout_seconds
                            )
                        else:
                            feedback = review_choice

                        if feedback:
                            await voice_io.notify( f"Revising {lang_name} script..." )
                            translated_script = await self._revise_script_async( translated_script, feedback )
                            scripts_by_language[ lang ] = translated_script
                            translated_path = await self._save_script_async( translated_script, language=lang )
                            script_paths_by_language[ lang ] = translated_path

                if self._check_stop(): return await self._handle_stop()

            # =================================================================
            # Phase 5: Generate Audio (Per Language)
            # =================================================================
            self.state = OrchestratorState.GENERATING_AUDIO

            audio_paths_by_language = {}
            tts_results_by_language = {}

            for lang, lang_script in scripts_by_language.items():
                lang_name = LANGUAGE_NAMES.get( lang, lang )

                # Initialize progress milestone tracking (for 10% increment notifications)
                self._reported_milestones         = set()
                self._audio_progress_group_id     = f"pg-{uuid.uuid4().hex[ :8 ]}"

                # Per-language progress group for start/stitch/complete notifications
                lang_audio_group_id = f"pg-{uuid.uuid4().hex[ :8 ]}"

                segment_count = lang_script.get_segment_count()
                await voice_io.notify(
                    f"Starting {lang_name} audio generation ({segment_count} segments)...",
                    priority          = "medium" if lang == "en" else "low",
                    progress_group_id = lang_audio_group_id,
                )

                tts_results, failed_indices = await self._generate_audio_async( lang_script, language=lang )
                tts_results_by_language[ lang ] = tts_results

                # Handle partial failures
                if failed_indices:
                    # Extract first error for diagnosis
                    first_error = next(
                        ( r.error_message for r in tts_results if not r.success and r.error_message ),
                        "Unknown error"
                    )
                    continue_anyway = await voice_io.ask_yes_no(
                        f"{lang_name}: {len( failed_indices )} segments failed. Continue with partial audio?",
                        default  = "yes",
                        abstract = f"**Language**: {lang_name}\n**Failed**: {len( failed_indices )}\n**Successful**: {len( tts_results ) - len( failed_indices )}\n**Error**: {first_error}"
                    )
                    if not continue_anyway:
                        await voice_io.notify( f"Skipping {lang_name} audio due to failures." )
                        continue  # Skip this language, continue with others

                if self._check_stop(): return await self._handle_stop()

                # Guard: check that at least one segment succeeded before stitching
                successful_count = sum( 1 for r in tts_results if r.success and r.pcm_audio )
                if successful_count == 0:
                    await voice_io.notify(
                        f"{lang_name}: All segments failed — skipping audio stitching.",
                        priority = "urgent"
                    )
                    continue  # Skip this language

                # =================================================================
                # Phase 6: Stitch Audio (Per Language)
                # =================================================================
                self.state = OrchestratorState.STITCHING_AUDIO
                await voice_io.notify(
                    f"Stitching {lang_name} audio segments...",
                    progress_group_id = lang_audio_group_id,
                )

                audio_path = await self._stitch_audio_async( tts_results, lang_script, language=lang )
                audio_paths_by_language[ lang ] = audio_path

                await voice_io.notify(
                    f"{lang_name} podcast complete!",
                    priority          = "low",
                    progress_group_id = lang_audio_group_id,
                )

                if self._check_stop(): return await self._handle_stop()

            # Guard: if NO language produced audio, this is a fatal failure
            if not audio_paths_by_language:
                raise RuntimeError(
                    "All TTS audio generation failed — no audio produced for any language. "
                    "Check ELEVENLABS_API_KEY and ElevenLabs API status."
                )

            # Store paths in state
            self._podcast_state[ "final_audio_path" ] = audio_paths_by_language.get( "en", "" )
            self._podcast_state[ "audio_paths_by_language" ] = audio_paths_by_language
            self._podcast_state[ "script_paths_by_language" ] = script_paths_by_language

            # =================================================================
            # Completion
            # =================================================================
            self.state = OrchestratorState.COMPLETED
            self.metrics[ "end_time" ] = time.time()

            duration = self.metrics[ "end_time" ] - self.metrics[ "start_time" ]

            # Get primary (English) paths for metadata
            primary_audio_path  = audio_paths_by_language.get( "en", list( audio_paths_by_language.values() )[ 0 ] if audio_paths_by_language else "" )
            primary_script_path = script_paths_by_language.get( "en", script_path )

            # Create metadata
            metadata = PodcastMetadata(
                podcast_id            = self.podcast_id,
                user_id               = self.user_id,
                research_doc_path     = self.research_doc_path,
                script_path           = primary_script_path,
                audio_path            = primary_audio_path,
                generated_at          = datetime.now().isoformat(),
                generation_duration_seconds = duration,
                api_calls_count       = self.api_client.cost_estimate.total_api_calls,
                total_tokens_used     = (
                    self.api_client.cost_estimate.total_input_tokens +
                    self.api_client.cost_estimate.total_output_tokens
                ),
                estimated_cost_usd    = self.api_client.cost_estimate.estimated_cost_usd,
                script_revision_count = self._podcast_state[ "revision_count" ],
            )
            self._podcast_state[ "metadata" ] = metadata

            # Calculate audio duration from primary audio
            audio_duration_mins = script.estimated_duration_minutes
            if primary_audio_path and os.path.exists( primary_audio_path ):
                try:
                    from pydub import AudioSegment
                    audio = AudioSegment.from_mp3( primary_audio_path )
                    audio_duration_mins = len( audio ) / 1000.0 / 60.0
                except Exception:
                    pass  # Use script estimate if audio read fails

            # Build clickable links for notification abstract
            io_base = cu.get_project_root() + "/io/"

            # Build links for research
            research_link = self.research_doc_path
            if self.research_doc_path and self.research_doc_path.startswith( io_base ):
                rel_path      = self.research_doc_path.replace( io_base, "" )
                research_link = f"[View Research](/app/docs?path={urllib.parse.quote( rel_path )})"

            # Build links for each language's outputs
            output_lines = []
            for lang in scripts_by_language.keys():
                lang_name    = LANGUAGE_NAMES.get( lang, lang )
                lang_script  = script_paths_by_language.get( lang, "" )
                lang_audio   = audio_paths_by_language.get( lang, "" )

                # Script link
                if lang_script and lang_script.startswith( io_base ):
                    rel_path    = lang_script.replace( io_base, "" )
                    script_link = f"[{lang_name} Script](/app/docs?path={urllib.parse.quote( rel_path )})"
                else:
                    script_link = f"`{lang_script}`"

                # Audio link
                if lang_audio and lang_audio.startswith( io_base ):
                    rel_path   = lang_audio.replace( io_base, "" )
                    audio_link = f"[{lang_name} MP3](/app/audio?path={urllib.parse.quote( rel_path )})"
                else:
                    audio_link = f"`{lang_audio}`"

                output_lines.append( f"**{lang_name}**: {script_link} | {audio_link}" )

            # Calculate total audio cost from all TTS results
            total_chars = 0
            for lang in scripts_by_language.keys():
                lang_results = self._podcast_state.get( f"tts_results_{lang}", [] )
                total_chars += sum( r.character_count for r in lang_results if r.success )
            audio_cost = ( total_chars / 1000.0 ) * ELEVENLABS_COST_PER_1K_CHARS
            total_cost = metadata.estimated_cost_usd + audio_cost

            # Build summary
            lang_count = len( scripts_by_language )
            lang_summary = f"{lang_count} language(s)" if lang_count > 1 else "1 language"

            await voice_io.notify(
                f"All podcasts complete! {lang_summary}, ~{audio_duration_mins:.1f} min each",
                priority = "high",
                abstract = f"**Languages**: {lang_summary}\n"
                           f"**Segments**: {script.get_segment_count()} per language\n"
                           f"**Duration**: ~{audio_duration_mins:.1f} minutes\n"
                           f"**Script Cost**: ${metadata.estimated_cost_usd:.4f}\n"
                           f"**Audio Cost**: ${audio_cost:.4f} ({total_chars:,} chars)\n"
                           f"**Total Cost**: ${total_cost:.4f}\n\n"
                           + "\n".join( output_lines ) + "\n\n"
                           f"**Research**: {research_link}"
            )

            return script

        except Exception as e:
            self.state = OrchestratorState.FAILED
            self.metrics[ "end_time" ] = time.time()
            logger.error( f"Podcast generation failed: {e}" )
            await voice_io.notify(
                f"Podcast generation failed: {str( e )[ :100 ]}",
                priority = "urgent"
            )
            raise

    async def do_review_only_async( self ) -> Optional[ PodcastScript ]:
        """
        Run only the review/revision workflow (skip generation phases).

        Used when resuming from a saved script via --edit-script flag.
        Enters directly at Phase 4 (WAITING_SCRIPT_REVIEW).

        Requires:
            - Script already loaded via from_saved_script()
            - State is WAITING_SCRIPT_REVIEW

        Ensures:
            - Executes review/revision workflow
            - Returns updated PodcastScript on success
            - Returns None on cancellation

        Returns:
            PodcastScript or None: Updated script, or None if cancelled
        """
        self.metrics[ "start_time" ] = time.time()

        try:
            script = self._podcast_state.get( "draft_script" )
            if not script:
                raise ValueError( "No script loaded - use from_saved_script() first" )

            draft_script_path = self._podcast_state.get( "draft_script_path", "" )

            await voice_io.notify(
                f"Loaded script: {script.title}",
                abstract = f"**Segments**: {script.get_segment_count()}\n"
                           f"**Duration**: ~{script.estimated_duration_minutes:.1f} minutes\n"
                           f"**Revisions**: {script.revision_count}"
            )

            # =================================================================
            # Phase 4: Script Review - ITERATIVE LOOP (edit mode entry point)
            # =================================================================
            script_approved = False
            script_path     = self._original_script_path  # Track current script location

            while not script_approved:
                self.state = OrchestratorState.WAITING_SCRIPT_REVIEW

                # Build clickable link to full script using /api/io/file endpoint
                import cosa.utils.util as cu
                io_base       = cu.get_project_root() + "/io/"
                display_path  = script_path or self._original_script_path

                if display_path and display_path.startswith( io_base ):
                    rel_path    = display_path.replace( io_base, "" )
                    script_link = f"[View Full Script](/app/docs?path={urllib.parse.quote( rel_path )})"
                else:
                    script_link = f"`{display_path}`"

                # Present script preview for approval
                script_preview = self._get_script_preview( script )
                script_preview += f"\n\n**Full Script**: {script_link}"

                revision_label = f" (Revision {self._podcast_state[ 'revision_count' ]})" if self._podcast_state[ "revision_count" ] > 0 else ""

                choice = await voice_io.present_choices(
                    questions = [ {
                        "question"    : "How would you like to proceed with this script?",
                        "header"      : "Script Review",
                        "multiSelect" : False,
                        "options"     : [
                            { "label": "Approve script", "description": "Keep script and finish" },
                            { "label": "Revise script", "description": "Provide feedback for changes" },
                            { "label": "Cancel", "description": "Discard changes and stop" }
                        ]
                    } ],
                    timeout  = self.config.script_review_timeout_seconds,
                    abstract = script_preview,
                    title    = f"Script Review{revision_label}",
                )

                review_choice = choice.get( "answers", {} ).get( "Script Review", "" )

                if review_choice == "Cancel":
                    self.state = OrchestratorState.STOPPED
                    await voice_io.notify( "Script editing cancelled." )
                    return None

                elif review_choice == "Approve script":
                    # Explicit approval - save and exit loop
                    script.revision_count = self._podcast_state[ "revision_count" ]
                    script_path = await self._save_script_async( script )
                    self._podcast_state[ "draft_script_path" ] = script_path
                    script_approved = True

                else:
                    # "Revise script" or "Other" with custom text
                    if review_choice == "Revise script":
                        feedback = await voice_io.get_input(
                            "What changes would you like to the script?",
                            timeout = self.config.feedback_timeout_seconds
                        )
                    else:
                        # "Other" - custom text IS the feedback
                        feedback = review_choice

                    if feedback:
                        self._podcast_state[ "human_feedback" ] = feedback
                        self._podcast_state[ "revision_count" ] += 1

                        # Revise script
                        self.state = OrchestratorState.GENERATING_SCRIPT
                        await voice_io.notify( f"Revising script (revision {self._podcast_state[ 'revision_count' ]})..." )

                        script = await self._revise_script_async( script, feedback )
                        self._podcast_state[ "draft_script" ] = script

                        # Save revision with version suffix (e.g., -v2.md)
                        script.revision_count = self._podcast_state[ "revision_count" ]
                        script_path = await self._save_script_async( script, is_revision=True )
                        self._podcast_state[ "draft_script_path" ] = script_path

                        # Loop continues - will show revised script for review again

            self._podcast_state[ "script_approved" ] = True
            self._podcast_state[ "final_script_path" ] = script_path

            # =================================================================
            # Completion
            # =================================================================
            self.state = OrchestratorState.COMPLETED
            self.metrics[ "end_time" ] = time.time()

            # Build clickable link for script
            import cosa.utils.util as cu
            io_base = cu.get_project_root() + "/io/"

            script_link = script_path
            if script_path and script_path.startswith( io_base ):
                rel_path    = script_path.replace( io_base, "" )
                script_link = f"[View Script](/app/docs?path={urllib.parse.quote( rel_path )})"

            await voice_io.notify(
                f"Script editing complete!",
                abstract = f"**Segments**: {script.get_segment_count()}\n"
                           f"**Duration**: ~{script.estimated_duration_minutes:.1f} minutes\n"
                           f"**Revisions**: {script.revision_count}\n"
                           f"**Script**: {script_link}"
            )

            return script

        except Exception as e:
            self.state = OrchestratorState.FAILED
            self.metrics[ "end_time" ] = time.time()
            logger.error( f"Script editing failed: {e}" )
            await voice_io.notify(
                f"Script editing failed: {str( e )[ :100 ]}",
                priority = "urgent"
            )
            raise

    async def do_audio_only_async( self ) -> Optional[ PodcastScript ]:
        """
        Run only the audio generation workflow (skip script review).

        Used when resuming from a saved script via --generate-audio flag.
        Enters directly at Phase 5 (GENERATING_AUDIO).

        Requires:
            - Script already loaded via from_saved_script()

        Ensures:
            - Executes audio generation and stitching only
            - Returns PodcastScript on success
            - Returns None on cancellation

        Returns:
            PodcastScript or None: Script with audio path, or None if cancelled
        """
        self.metrics[ "start_time" ] = time.time()

        try:
            script = self._podcast_state.get( "draft_script" )
            if not script:
                raise ValueError( "No script loaded - use from_saved_script() first" )

            script_path = self._podcast_state.get( "draft_script_path", "" )

            await voice_io.notify(
                f"Loaded script: {script.title}",
                abstract = f"**Segments**: {script.get_segment_count()}\n"
                           f"**Duration**: ~{script.calculated_duration_minutes:.1f} minutes"
            )

            # =================================================================
            # Phase 5: Generate Audio
            # =================================================================
            self.state = OrchestratorState.GENERATING_AUDIO

            # Initialize progress milestone tracking (for 10% increment notifications)
            self._reported_milestones         = set()
            self._audio_progress_group_id     = f"pg-{uuid.uuid4().hex[ :8 ]}"

            segment_count = script.get_segment_count()
            await voice_io.notify(
                f"Starting English audio generation ({segment_count} segments)...",
                priority          = "medium",
                progress_group_id = self._audio_progress_group_id,
            )

            tts_results, failed_indices = await self._generate_audio_async( script )

            # Handle partial failures - HIGH priority for TTS announcement
            if failed_indices:
                # Extract first error for diagnosis
                first_error = next(
                    ( r.error_message for r in tts_results if not r.success and r.error_message ),
                    "Unknown error"
                )
                continue_anyway = await voice_io.ask_yes_no(
                    f"{len( failed_indices )} segments failed. Continue with partial audio?",
                    default  = "yes",
                    timeout  = 120,
                    abstract = f"**Failed**: {len( failed_indices )}\n**Successful**: {len( tts_results ) - len( failed_indices )}\n**Error**: {first_error}"
                )
                if not continue_anyway:
                    self.state = OrchestratorState.STOPPED
                    await voice_io.notify( "Audio generation cancelled by user." )
                    return None

            if self._check_stop(): return await self._handle_stop()

            # Guard: check that at least one segment succeeded before stitching
            successful_count = sum( 1 for r in tts_results if r.success and r.pcm_audio )
            if successful_count == 0:
                raise RuntimeError( "Audio generation failed: no segments produced audio data" )

            # =================================================================
            # Phase 6: Stitch Audio
            # =================================================================
            self.state = OrchestratorState.STITCHING_AUDIO
            await voice_io.notify( "Stitching English audio segments..." )

            audio_path = await self._stitch_audio_async( tts_results, script )
            self._podcast_state[ "final_audio_path" ] = audio_path

            if self._check_stop(): return await self._handle_stop()

            # =================================================================
            # Completion
            # =================================================================
            self.state = OrchestratorState.COMPLETED
            self.metrics[ "end_time" ] = time.time()

            duration = self.metrics[ "end_time" ] - self.metrics[ "start_time" ]

            # Calculate audio duration
            audio_duration_mins = script.calculated_duration_minutes
            if audio_path and os.path.exists( audio_path ):
                try:
                    from pydub import AudioSegment
                    audio = AudioSegment.from_mp3( audio_path )
                    audio_duration_mins = len( audio ) / 1000.0 / 60.0
                except Exception:
                    pass  # Use script estimate if audio read fails

            # Build clickable links for notification abstract
            import cosa.utils.util as cu
            io_base = cu.get_project_root() + "/io/"

            # Convert absolute paths to relative for API endpoint
            script_link   = script_path
            audio_link    = audio_path
            research_link = None  # Only set if valid research path exists

            if script_path and script_path.startswith( io_base ):
                rel_path    = script_path.replace( io_base, "" )
                script_link = f"[View Script](/app/docs?path={urllib.parse.quote( rel_path )})"
            if audio_path and audio_path.startswith( io_base ):
                rel_path   = audio_path.replace( io_base, "" )
                audio_link = f"[Download MP3](/app/audio?path={urllib.parse.quote( rel_path )})"
            # Only create research link if it's a valid path (not "edit-mode" or other placeholder)
            if ( self.research_doc_path
                 and self.research_doc_path != "edit-mode"
                 and self.research_doc_path.startswith( io_base ) ):
                rel_path      = self.research_doc_path.replace( io_base, "" )
                research_link = f"[View Research](/app/docs?path={urllib.parse.quote( rel_path )})"

            # Calculate audio cost from TTS character usage (language-specific key)
            tts_results = self._podcast_state.get( "tts_results_en", [] )
            total_chars = sum( r.character_count for r in tts_results if r.success )
            audio_cost  = ( total_chars / 1000.0 ) * ELEVENLABS_COST_PER_1K_CHARS

            # Build abstract - conditionally include research link only if valid
            abstract_lines = [
                f"**Segments**: {script.get_segment_count()}",
                f"**Duration**: {audio_duration_mins:.1f} minutes",
                f"**Audio Cost**: ${audio_cost:.4f} ({total_chars:,} chars)",
                f"**Audio**: {audio_link}",
                f"**Script**: {script_link}",
            ]
            if research_link:
                abstract_lines.append( f"**Research**: {research_link}" )

            await voice_io.notify(
                f"Podcast audio complete! Duration: {audio_duration_mins:.1f} minutes",
                priority = "high",
                abstract = "\n".join( abstract_lines )
            )

            return script

        except Exception as e:
            self.state = OrchestratorState.FAILED
            self.metrics[ "end_time" ] = time.time()
            logger.error( f"Audio generation failed: {e}" )
            await voice_io.notify(
                f"Audio generation failed: {str( e )[ :100 ]}",
                priority = "urgent"
            )
            raise

    def get_state( self ) -> dict:
        """
        Query current orchestrator state for external monitoring.

        Returns:
            dict: Current state summary
        """
        return {
            "state"          : self.state.value,
            "progress_pct"   : self._calculate_progress(),
            "podcast_id"     : self.podcast_id,
            "research_doc"   : self.research_doc_path,
            "revision_count" : self._podcast_state.get( "revision_count", 0 ),
            "script_approved": self._podcast_state.get( "script_approved", False ),
            "metrics"        : self.metrics,
        }

    async def pause( self ) -> bool:
        """Request graceful pause at next yield point."""
        self._pause_requested = True
        return True

    async def resume( self ) -> bool:
        """Resume from paused state."""
        if self.state == OrchestratorState.PAUSED:
            self._pause_requested = False
            return True
        return False

    async def stop( self ) -> dict:
        """Cancel and return partial results."""
        self._stop_requested = True
        self.state = OrchestratorState.STOPPED
        return {
            "partial_script" : self._podcast_state.get( "draft_script" ),
            "stopped_at"     : self.state.value,
            "analysis"       : self._podcast_state.get( "content_analysis" ),
        }

    # =========================================================================
    # Private Methods - Phase 1 Implementation
    # =========================================================================

    def _check_stop( self ) -> bool:
        """Check if stop was requested."""
        return self._stop_requested

    async def _handle_stop( self ) -> None:
        """Handle stop request gracefully."""
        await voice_io.notify( "Podcast generation stopped by user request." )
        self.state = OrchestratorState.STOPPED
        return None

    def _calculate_progress( self ) -> int:
        """Calculate completion percentage based on current state."""
        state_progress = {
            OrchestratorState.LOADING_RESEARCH      : 10,
            OrchestratorState.ANALYZING_CONTENT     : 30,
            OrchestratorState.GENERATING_SCRIPT     : 60,
            OrchestratorState.WAITING_SCRIPT_REVIEW : 80,
            OrchestratorState.GENERATING_AUDIO      : 85,
            OrchestratorState.STITCHING_AUDIO       : 95,
            OrchestratorState.COMPLETED             : 100,
            OrchestratorState.FAILED                : 0,
            OrchestratorState.PAUSED                : 0,
            OrchestratorState.STOPPED               : 0,
        }
        return state_progress.get( self.state, 0 )

    async def _load_research_async( self ) -> Optional[ str ]:
        """
        Load and validate the research document.

        Returns:
            str or None: Document content, or None if loading fails
        """
        try:
            # Run file I/O in thread pool
            def read_file():
                import cosa.utils.util as cu

                # Handle relative paths
                if self.research_doc_path.startswith( "/" ):
                    path = self.research_doc_path
                else:
                    path = cu.get_project_root() + "/" + self.research_doc_path

                if not os.path.exists( path ):
                    logger.error( f"Research document not found: {path}" )
                    return None

                with open( path, "r", encoding="utf-8" ) as f:
                    content = f.read()

                return content

            content = await asyncio.to_thread( read_file )

            if content and self.debug:
                print( f"[PodcastOrchestratorAgent] Loaded research doc: {len( content )} chars" )

            return content

        except Exception as e:
            logger.error( f"Failed to load research document: {e}" )
            return None

    async def _analyze_content_async( self, research_content: str ) -> ContentAnalysis:
        """
        Analyze research content to extract key topics and discussion points.

        Args:
            research_content: The research document text

        Returns:
            ContentAnalysis: Structured analysis of the content
        """
        try:
            prompt = get_content_analysis_prompt(
                research_content = research_content,
                max_topics       = self.config.key_topics_to_extract,
                audience         = self.config.audience,
                audience_context = self.config.audience_context,
            )

            response = await self.api_client.call_for_analysis(
                system_prompt = CONTENT_ANALYSIS_SYSTEM_PROMPT,
                user_message  = prompt,
            )
            self.metrics[ "api_calls" ] += 1

            result = parse_analysis_response( response.content )

            return ContentAnalysis(
                main_topic                 = result.get( "main_topic", "Unknown Topic" ),
                key_subtopics              = result.get( "key_subtopics", [] ),
                interesting_facts          = result.get( "interesting_facts", [] ),
                discussion_questions       = result.get( "discussion_questions", [] ),
                analogies_suggested        = result.get( "analogies_suggested", [] ),
                # LLM outputs "target_audience" in JSON → mapped to Python field "inferred_audience"
                inferred_audience          = result.get( "target_audience", "general audience" ),
                complexity_level           = result.get( "complexity_level", "intermediate" ),
                estimated_coverage_minutes = result.get( "estimated_coverage_minutes", 10.0 ),
            )

        except Exception as e:
            logger.error( f"Content analysis failed: {e}" )
            if self.debug:
                print( f"[PodcastOrchestratorAgent] Analysis error: {e}" )

            # Fail LOUDLY. A silent placeholder analysis would flow downstream into a
            # fake 0-segment script that reaches the review gate looking review-ready.
            raise PodcastGenerationError(
                "Podcast generation failed: the AI service returned an error while "
                "analyzing the research document. Please try again in a few minutes."
            ) from e

    async def _generate_script_async(
        self,
        research_content: str,
        analysis: ContentAnalysis
    ) -> PodcastScript:
        """
        Generate the podcast script using Claude.

        Args:
            research_content: The research document text
            analysis: Content analysis results

        Returns:
            PodcastScript: Generated script with dialogue segments
        """
        try:
            # Build system prompt with host personalities
            duo_description = get_dynamic_duo_description(
                host_a = self.config.host_a_personality,
                host_b = self.config.host_b_personality,
            )
            system_prompt = SCRIPT_GENERATION_SYSTEM_PROMPT + "\n\n" + duo_description

            # Build user prompt
            user_prompt = get_script_generation_prompt(
                content_analysis       = analysis.model_dump(),
                research_content       = research_content,
                host_a_personality     = self.config.host_a_personality,
                host_b_personality     = self.config.host_b_personality,
                target_duration_minutes = self.config.target_duration_minutes,
                min_exchanges          = self.config.min_exchanges,
                max_exchanges          = self.config.max_exchanges,
                audience               = self.config.audience,
                audience_context       = self.config.audience_context,
            )

            response = await self.api_client.call_for_script(
                system_prompt = system_prompt,
                user_message  = user_prompt,
            )
            self.metrics[ "api_calls" ] += 1

            result = parse_script_response( response.content )

            # Convert to PodcastScript
            segments = [
                ScriptSegment(
                    speaker         = seg.get( "speaker", "Host" ),
                    role            = seg.get( "role", "curious" ),
                    text            = seg.get( "text", "" ),
                    prosody         = seg.get( "prosody", [] ),
                    topic_reference = seg.get( "topic_reference" ),
                )
                for seg in result.get( "segments", [] )
            ]

            return PodcastScript(
                title                      = result.get( "title", f"Podcast: {analysis.main_topic}" ),
                research_source            = self.research_doc_path,
                host_a_name                = self.config.get_host_a_name(),
                host_b_name                = self.config.get_host_b_name(),
                segments                   = segments,
                estimated_duration_minutes = result.get( "estimated_duration_minutes", 10.0 ),
                key_topics                 = result.get( "key_topics", analysis.key_subtopics ),
            )

        except Exception as e:
            logger.error( f"Script generation failed: {e}" )
            if self.debug:
                print( f"[PodcastOrchestratorAgent] Script generation error: {e}" )

            # Fail LOUDLY. A silent 0-segment placeholder script would reach the
            # review gate looking like a normal (if empty) review-ready result.
            raise PodcastGenerationError(
                "Podcast generation failed: the AI service returned an error while "
                "writing the podcast script. Please try again in a few minutes."
            ) from e

    async def _revise_script_async(
        self,
        current_script: PodcastScript,
        feedback: str
    ) -> PodcastScript:
        """
        Revise the script based on user feedback.

        Args:
            current_script: Current script to revise
            feedback: User feedback on changes needed

        Returns:
            PodcastScript: Revised script
        """
        try:
            revision_prompt = get_script_revision_prompt(
                current_script  = current_script.to_markdown(),
                feedback        = feedback,
                revision_number = self._podcast_state[ "revision_count" ],
            )

            response = await self.api_client.call_for_revision(
                system_prompt = SCRIPT_GENERATION_SYSTEM_PROMPT,
                user_message  = revision_prompt,
            )
            self.metrics[ "api_calls" ] += 1

            result = parse_script_response( response.content )

            # Convert to PodcastScript
            segments = [
                ScriptSegment(
                    speaker         = seg.get( "speaker", "Host" ),
                    role            = seg.get( "role", "curious" ),
                    text            = seg.get( "text", "" ),
                    prosody         = seg.get( "prosody", [] ),
                    topic_reference = seg.get( "topic_reference" ),
                )
                for seg in result.get( "segments", [] )
            ]

            revised = PodcastScript(
                title                      = result.get( "title", current_script.title ),
                research_source            = current_script.research_source,
                host_a_name                = current_script.host_a_name,
                host_b_name                = current_script.host_b_name,
                segments                   = segments if segments else current_script.segments,
                estimated_duration_minutes = result.get( "estimated_duration_minutes",
                                                          current_script.estimated_duration_minutes ),
                key_topics                 = result.get( "key_topics", current_script.key_topics ),
                revision_count             = current_script.revision_count + 1,
            )

            return revised

        except Exception as e:
            logger.error( f"Script revision failed: {e}" )
            # Return original script unchanged
            return current_script

    async def _save_script_async(
        self,
        script      : PodcastScript,
        is_revision : bool = False,
        language    : str  = "en"
    ) -> str:
        """
        Save the script to a markdown file.

        For new scripts, generates a new path and stores it.
        For revisions, appends version suffix (e.g., -v2.md) to preserve history.
        For approval (final save), uses original path.
        For non-English languages, generates separate file with language suffix.

        Args:
            script: The script to save
            is_revision: If True, append version suffix (e.g., -v2.md) to filename
            language: ISO language code (default: "en")

        Returns:
            str: Path to saved file
        """
        try:
            import cosa.utils.util as cu

            # For non-English languages, always generate a new language-specific path
            if language != "en":
                topic_slug = script.title.replace( "Podcast: ", "" )[ :40 ]
                # Remove language suffix from title if present (for cleaner slugs)
                for lang_name in LANGUAGE_NAMES.values():
                    topic_slug = topic_slug.replace( f" ({lang_name})", "" )
                output_path = self.config.get_output_path(
                    user_id   = self.user_id,
                    topic     = topic_slug,
                    file_type = "script",
                    language  = language,
                )

            # English language handling (original behavior)
            elif self._original_script_path and is_revision:
                # Generate versioned path: original-script-v2.md (suffix before .md)
                base_path    = self._original_script_path
                revision_num = self._podcast_state.get( "revision_count", 1 )

                # Split: /path/to/name-script.md → /path/to/name-script + .md
                # Result: /path/to/name-script-v2.md
                stem, ext   = os.path.splitext( base_path )  # ext = ".md"
                output_path = f"{stem}-v{revision_num}{ext}"

            elif self._original_script_path:
                # Non-revision save (approval) - use original path
                output_path = self._original_script_path

            else:
                # First save - generate new path
                topic_slug = script.title.replace( "Podcast: ", "" )[ :40 ]
                output_path = self.config.get_output_path(
                    user_id   = self.user_id,
                    topic     = topic_slug,
                    file_type = "script",
                    language  = language,
                )
                # Store for future reference. This first-save branch is reached only
                # on the English path (the `if language != "en":` arm above consumes
                # every non-en case), so the prior `if language == "en":` guard here
                # was redundant/dead and has been removed.
                self._original_script_path = output_path

            # Ensure directory exists
            output_dir = os.path.dirname( output_path )

            def write_file():
                os.makedirs( output_dir, exist_ok=True )
                with open( output_path, "w", encoding="utf-8" ) as f:
                    f.write( script.to_markdown() )
                return output_path

            path = await asyncio.to_thread( write_file )

            if self.debug:
                print( f"[PodcastOrchestratorAgent] Script saved to: {path}" )

            return path

        except Exception as e:
            logger.error( f"Failed to save script: {e}" )
            raise

    async def _delete_draft_script( self, script_path: str ) -> None:
        """
        Delete a draft script file (used when user cancels).

        Args:
            script_path: Path to the script file to delete
        """
        try:
            def delete_file():
                if os.path.exists( script_path ):
                    os.remove( script_path )
                    return True
                return False

            deleted = await asyncio.to_thread( delete_file )

            if self.debug and deleted:
                print( f"[PodcastOrchestratorAgent] Draft script deleted: {script_path}" )

        except Exception as e:
            logger.warning( f"Failed to delete draft script: {e}" )
            # Non-fatal - continue anyway

    def _get_script_preview( self, script: PodcastScript ) -> str:
        """
        Generate a preview summary of the script for review.

        Args:
            script: The script to preview

        Returns:
            str: Markdown preview summary
        """
        word_counts = script.get_speaker_word_counts()
        word_summary = "\n".join( [
            f"- **{speaker}**: {count} words"
            for speaker, count in word_counts.items()
        ] )

        # Get first few segments as sample
        sample_segments = script.segments[ :3 ] if len( script.segments ) >= 3 else script.segments
        sample_text = "\n\n".join( [ seg.to_markdown() for seg in sample_segments ] )

        return f"""## Script Preview: {script.title}

**Segments**: {script.get_segment_count()}
**Estimated Duration**: {script.estimated_duration_minutes:.1f} minutes
**Key Topics**: {', '.join( script.key_topics[ :5 ] )}

### Word Distribution
{word_summary}

### Sample Dialogue
{sample_text}

---
*Full script contains {script.get_segment_count()} dialogue segments.*"""

    # =========================================================================
    # Private Methods - Phase 4b Implementation (Multi-Language Generation)
    # =========================================================================

    async def _generate_translated_script_async(
        self,
        english_script  : PodcastScript,
        target_language : str
    ) -> PodcastScript:
        """
        Generate script in target language based on English script.

        Uses Claude to create natural dialogue in target language,
        not literal translation. Preserves prosody markers and speaker structure.

        Requires:
            - english_script is a valid PodcastScript
            - target_language is a valid ISO language code

        Ensures:
            - Returns PodcastScript in target language
            - Prosody markers are preserved
            - Speaker names remain unchanged

        Args:
            english_script: The approved English script
            target_language: ISO language code (e.g., "es-MX")

        Returns:
            PodcastScript: Script in target language
        """
        language_name = LANGUAGE_NAMES.get( target_language, target_language )

        if self.debug:
            print( f"[PodcastOrchestratorAgent] Generating {language_name} version of script" )

        try:
            # Build prompt for native script generation in target language
            # Include the English script as reference for structure and content
            translation_prompt = f"""Generate a {language_name} version of this podcast script.

IMPORTANT REQUIREMENTS:
1. Generate NATURAL {language_name} dialogue - do NOT translate literally
2. Preserve ALL prosody markers (*[pause]*, *[excited]*, etc.) UNCHANGED in English
3. Keep host names (Maria, Mr. Radio) UNCHANGED
4. Maintain the same dialogue structure (same number of segments, same speaker order)
5. Adapt idioms, cultural references, and examples for {language_name} speakers
6. Match the tone and energy of each segment

ENGLISH SCRIPT TO ADAPT:
---
{english_script.to_markdown()}
---

Generate the {language_name} script in JSON format with the same structure:
{{
    "title": "{language_name} title here",
    "segments": [
        {{"speaker": "Maria", "role": "curious", "text": "{language_name} dialogue with *[prosody]* markers"}},
        ...
    ],
    "key_topics": [...],
    "estimated_duration_minutes": {english_script.estimated_duration_minutes}
}}"""

            response = await self.api_client.call_for_script(
                system_prompt = SCRIPT_GENERATION_SYSTEM_PROMPT,
                user_message  = translation_prompt,
            )
            self.metrics[ "api_calls" ] += 1

            result = parse_script_response( response.content )

            # Convert to PodcastScript
            segments = [
                ScriptSegment(
                    speaker         = seg.get( "speaker", "Host" ),
                    role            = seg.get( "role", "curious" ),
                    text            = seg.get( "text", "" ),
                    prosody         = seg.get( "prosody", [] ),
                    topic_reference = seg.get( "topic_reference" ),
                )
                for seg in result.get( "segments", [] )
            ]

            translated_script = PodcastScript(
                title                      = result.get( "title", f"{english_script.title} ({language_name})" ),
                research_source            = english_script.research_source,
                host_a_name                = english_script.host_a_name,
                host_b_name                = english_script.host_b_name,
                segments                   = segments if segments else english_script.segments,
                estimated_duration_minutes = result.get( "estimated_duration_minutes",
                                                          english_script.estimated_duration_minutes ),
                key_topics                 = result.get( "key_topics", english_script.key_topics ),
                revision_count             = 0,  # Start fresh for translated version
            )

            # Validate prosody preservation
            is_preserved, details = validate_prosody_preservation( english_script, translated_script )
            if not is_preserved:
                logger.warning(
                    f"Prosody mismatch in {language_name} translation: "
                    f"EN={details[ 'english_count' ]}, {target_language}={details[ 'translated_count' ]}, "
                    f"missing={details[ 'missing' ]}"
                )
                await voice_io.notify(
                    f"Warning: Some prosody markers may have changed in {language_name} translation. Please review carefully.",
                    priority = "high"
                )

            return translated_script

        except Exception as e:
            logger.error( f"Script translation to {target_language} failed: {e}" )
            if self.debug:
                print( f"[PodcastOrchestratorAgent] Translation error: {e}" )

            # Return a copy of English script with updated title as fallback
            return PodcastScript(
                title                      = f"{english_script.title} ({language_name} - Translation Failed)",
                research_source            = english_script.research_source,
                host_a_name                = english_script.host_a_name,
                host_b_name                = english_script.host_b_name,
                segments                   = english_script.segments,
                estimated_duration_minutes = english_script.estimated_duration_minutes,
                key_topics                 = english_script.key_topics,
            )

    # =========================================================================
    # Private Methods - Phase 2 Implementation (Audio Generation)
    # =========================================================================

    async def _generate_audio_async(
        self,
        script   : PodcastScript,
        language : str = "en"
    ) -> Tuple[ List[ TTSSegmentResult ], List[ int ] ]:
        """
        Phase 5: Generate TTS audio for all segments.

        Uses the TTS client to generate PCM audio for each dialogue
        segment in the script. For non-English languages, uses
        multilingual model with language_code.

        Requires:
            - script has at least one segment
            - ELEVENLABS_API_KEY is set in environment

        Ensures:
            - Returns list of TTSSegmentResult for all segments
            - Returns list of indices for failed segments

        Args:
            script: Podcast script with dialogue segments
            language: ISO language code for voice selection (default: "en")

        Returns:
            Tuple[List[TTSSegmentResult], List[int]]:
                - All TTS results (including failures)
                - Indices of failed segments
        """
        # Apply max_segments limit if set (for cost control during testing)
        original_count = script.get_segment_count()
        if self.max_segments is not None and self.max_segments < original_count:
            if self.debug:
                print( f"[PodcastOrchestratorAgent] Limiting segments: {self.max_segments} of {original_count}" )
            # Create a shallow copy of script with limited segments
            from copy import copy
            limited_script = copy( script )
            limited_script.segments = script.segments[ :self.max_segments ]
            script = limited_script

        if self.debug:
            lang_name = LANGUAGE_NAMES.get( language, language )
            print( f"[PodcastOrchestratorAgent] Starting audio generation for {script.get_segment_count()} segments ({lang_name})" )

        # Use the lazy-initialized TTS client with language-aware generation
        tts_results, failed_indices = await self.tts_client.generate_all_segments(
            script   = script,
            language = language
        )

        # Store TTS results in state for cost calculation in notifications
        # Use language-specific key to avoid overwriting
        self._podcast_state[ f"tts_results_{language}" ] = tts_results

        success_count = len( tts_results ) - len( failed_indices )
        if self.debug:
            print( f"[PodcastOrchestratorAgent] Audio generation complete: {success_count}/{len( tts_results )} successful" )

        # Always log failure details for diagnosis
        if failed_indices:
            first_error = next(
                ( r.error_message for r in tts_results if not r.success and r.error_message ),
                "Unknown error"
            )
            print( f"[PodcastOrchestratorAgent] Audio failures: {len( failed_indices )}/{len( tts_results )} segments failed" )
            print( f"[PodcastOrchestratorAgent] First error: {first_error}" )

        return tts_results, failed_indices

    async def _stitch_audio_async(
        self,
        tts_results : List[ TTSSegmentResult ],
        script      : PodcastScript,
        language    : str = "en"
    ) -> str:
        """
        Phase 6: Stitch audio segments into final MP3.

        Uses the audio stitcher to concatenate all successful TTS
        results into a single podcast MP3 file.

        Requires:
            - tts_results contains at least one successful result
            - Output directory is writable

        Ensures:
            - Creates MP3 file at the output path
            - Returns path to the created file
            - Non-English files have language suffix in filename

        Args:
            tts_results: List of TTS results from generation phase
            script: Original script (for output path generation)
            language: ISO language code for output filename (default: "en")

        Returns:
            str: Path to the created MP3 file
        """
        # Generate output path with language suffix
        topic_slug  = script.title.replace( "Podcast: ", "" )[ :40 ]
        # Remove language suffix from title if present (for cleaner slugs)
        for lang_name in LANGUAGE_NAMES.values():
            topic_slug = topic_slug.replace( f" ({lang_name})", "" )

        output_path = self.config.get_output_path(
            user_id   = self.user_id,
            topic     = topic_slug,
            file_type = "audio",
            language  = language,
        )

        if self.debug:
            lang_name = LANGUAGE_NAMES.get( language, language )
            print( f"[PodcastOrchestratorAgent] Stitching {lang_name} audio to: {output_path}" )

        # Run stitching in thread pool (pydub is synchronous)
        def do_stitch():
            return self.audio_stitcher.stitch_segments( tts_results, output_path )

        result = await asyncio.to_thread( do_stitch )

        if not result.success:
            raise RuntimeError( f"Audio stitching failed: {result.error_message}" )

        if self.debug:
            print( f"[PodcastOrchestratorAgent] Audio stitched: {result.total_duration_seconds:.1f}s, {result.file_size_bytes / 1024:.1f}KB" )

        return result.output_path

    async def _audio_progress_callback(
        self,
        current     : int,
        total       : int,
        speaker     : str,
        eta_seconds : float = 0.0
    ) -> None:
        """
        Progress callback for audio generation milestones.

        Called by TTS client after each segment. Sends notifications
        at every 10% progress milestone (10%, 20%, ... 100%).

        Args:
            current: Current segment number (1-based)
            total: Total number of segments
            speaker: Speaker name for current segment
            eta_seconds: Estimated time remaining in seconds
        """
        # Calculate percentage and round down to nearest 10%
        pct = int( current / total * 100 )
        milestone = ( pct // 10 ) * 10  # 15% → 10%, 27% → 20%, etc.

        # Notify only when reaching a new 10% milestone
        if milestone not in self._reported_milestones and milestone > 0:
            self._reported_milestones.add( milestone )

            if eta_seconds > 0:
                eta_str = f", ~{int( eta_seconds )}s remaining"
            else:
                eta_str = ""

            await voice_io.notify(
                f"Audio progress: {pct}% ({current}/{total} segments){eta_str}",
                priority          = "low",
                progress_group_id = self._audio_progress_group_id,
            )

    async def _audio_retry_callback(
        self,
        segment_index : int,
        attempt       : int,
        max_attempts  : int,
        speaker       : str
    ) -> None:
        """
        Retry callback for TTS segment failures.

        Called by TTS client when a segment fails and will be retried.
        Sends low priority notification to inform user of retry attempt.

        Args:
            segment_index: Zero-based index of the segment
            attempt: Current attempt number (1-based, e.g., 2 = second attempt)
            max_attempts: Maximum number of attempts
            speaker: Speaker name for the segment
        """
        await voice_io.notify(
            f"Segment {segment_index + 1} ({speaker}) failed, retrying ({attempt}/{max_attempts})...",
            priority = "low"
        )


def quick_smoke_test():
    """Quick smoke test for PodcastOrchestratorAgent."""
    import cosa.utils.util as cu

    cu.print_banner( "Podcast Orchestrator Smoke Test", prepend_nl=True )

    try:
        # Test 1: Instantiation
        print( "Testing instantiation..." )
        agent = PodcastOrchestratorAgent(
            research_doc_path = "/tmp/test-research.md",
            user_id           = "test-user@example.com",
            debug             = True,
        )
        assert agent.state == OrchestratorState.LOADING_RESEARCH
        assert "test-research.md" in agent.research_doc_path
        print( f"✓ Agent instantiated (ID: {agent.podcast_id})" )

        # Test 2: get_state
        print( "Testing get_state..." )
        state = agent.get_state()
        assert "state" in state
        assert "progress_pct" in state
        assert "podcast_id" in state
        assert state[ "state" ] == "loading_research"
        print( f"✓ get_state works (state={state[ 'state' ]}, progress={state[ 'progress_pct' ]}%)" )

        # Test 3: _calculate_progress
        print( "Testing _calculate_progress..." )
        assert agent._calculate_progress() == 10  # LOADING_RESEARCH = 10%
        agent.state = OrchestratorState.GENERATING_SCRIPT
        assert agent._calculate_progress() == 60  # GENERATING_SCRIPT = 60%
        agent.state = OrchestratorState.COMPLETED
        assert agent._calculate_progress() == 100  # COMPLETED = 100%
        print( "✓ _calculate_progress returns correct values" )

        # Test 4: pause/stop methods
        print( "Testing control methods..." )

        async def test_control():
            agent2 = PodcastOrchestratorAgent(
                research_doc_path = "/tmp/test.md",
                user_id           = "test-user",
            )

            # Test pause
            paused = await agent2.pause()
            assert paused is True
            assert agent2._pause_requested is True

            # Test stop
            result = await agent2.stop()
            assert agent2.state == OrchestratorState.STOPPED
            assert "partial_script" in result

            return True

        import asyncio
        result = asyncio.run( test_control() )
        assert result is True
        print( "✓ Control methods (pause/stop) work correctly" )

        # Test 5: _get_script_preview
        print( "Testing _get_script_preview..." )
        agent.state = OrchestratorState.LOADING_RESEARCH  # Reset state

        test_script = PodcastScript(
            title           = "Test Podcast",
            research_source = "/test.md",
            host_a_name     = "Maria",
            host_b_name     = "Mr. Radio",
            segments        = [
                ScriptSegment( speaker="Maria", role="curious", text="Hello!" ),
                ScriptSegment( speaker="Mr. Radio", role="expert", text="Hi there!" ),
            ],
            estimated_duration_minutes = 5.0,
            key_topics      = [ "topic1", "topic2" ],
        )

        preview = agent._get_script_preview( test_script )
        assert "Test Podcast" in preview
        assert "2" in preview  # 2 segments
        assert "Maria" in preview
        print( "✓ _get_script_preview generates proper markdown" )

        print( "\n✓ Podcast Orchestrator smoke test completed successfully" )

    except Exception as e:
        print( f"\n✗ Smoke test failed: {e}" )
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    quick_smoke_test()
