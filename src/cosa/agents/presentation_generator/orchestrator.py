#!/usr/bin/env python3
"""
Presentation Orchestrator Agent — Top-level coordinator for presentation generation.

This agent manages the entire presentation generation workflow internally as a single
queue entry, yielding control at I/O boundaries via async/await.

Design Pattern: Top-Level Orchestrator (same as Podcast Generator)
- Single job in queue, multi-phase internal state machine
- Async execution for non-blocking queue behavior
- Queryable state for external monitoring
- Controllable via pause/stop

Phase progression:
    INGESTING → ANALYZING → OUTLINING → ELABORATING → SERIALIZING
    → RENDERING_TEXT → RENDERING_VISUALS → DELIVERING → COMPLETED

Current status: Skeleton with stub phase methods (Phase 2 foundation).
Real implementations will be added in Phases 3-8.
"""

import asyncio
import logging
import os
import re
import uuid
import yaml
from typing import Optional, List, Tuple
from datetime import datetime

import cosa.utils.util as cu
from .config import PresentationConfig
from .state import (
    OrchestratorState,
    PresentationModel,
    NarrativeSection,
    SlideOutline,
    SlideModel,
    create_initial_state,
)
from . import cosa_interface
from . import voice_io

logger = logging.getLogger( __name__ )


class PresentationOrchestratorAgent:
    """
    Top-level orchestrator for presentation generation — single job, multi-phase, async.

    Standalone class (not inheriting from AgentBase) because:
    - AgentBase is synchronous, this is async
    - Different execution model (yields on await vs blocking)
    - Composition over inheritance for COSA integration

    Requires:
        - source_path points to a valid file
        - user_id is a valid system identifier

    Ensures:
        - Manages entire presentation workflow internally
        - Yields control at I/O boundaries (await points)
        - State is queryable via get_state()
        - Can be stopped externally via request_stop()
    """

    def __init__(
        self,
        source_path : str,
        user_id     : str,
        config      : Optional[ PresentationConfig ] = None,
        dry_run     : bool = False,
        debug       : bool = False,
        verbose     : bool = False
    ):
        """
        Initialize the presentation orchestrator.

        Args:
            source_path: Path to the source document (markdown/text)
            user_id: System user ID for event routing
            config: Presentation configuration (uses defaults if None)
            dry_run: Run without API calls — ingest real, analyze/outline/elaborate mock
            debug: Enable debug output
            verbose: Enable verbose output
        """
        self.source_path = source_path
        self.user_id     = user_id
        self.config      = config or PresentationConfig()
        self.dry_run     = dry_run
        self.debug       = debug
        self.verbose     = verbose

        # State management
        self.state            = OrchestratorState.INITIALIZED
        self._stop_requested  = False

        # Initialize internal state tracking dict
        self._presentation_state = create_initial_state( source_path, user_id )

        # Generate presentation ID
        self.presentation_id = f"pres-{uuid.uuid4().hex[ :8 ]}"

        # Metrics
        self.metrics = {
            "start_time"  : None,
            "end_time"    : None,
            "api_calls"   : 0,
            "tokens_used" : 0,
        }

        # Lazy-initialized clients
        self._api_client = None

        if self.debug:
            print( f"[PresentationOrchestratorAgent] Initialized for: {source_path}" )
            print( f"[PresentationOrchestratorAgent] Presentation ID: {self.presentation_id}" )

    # =========================================================================
    # Lazy Properties
    # =========================================================================

    @property
    def api_client( self ):
        """Lazy-initialized API client for Claude calls."""
        if self._api_client is None:
            from .api_client import PresentationAPIClient
            self._api_client = PresentationAPIClient(
                config  = self.config,
                debug   = self.debug,
                verbose = self.verbose
            )
        return self._api_client

    # =========================================================================
    # External Control
    # =========================================================================

    def request_stop( self ):
        """Request graceful stop at next phase boundary."""
        self._stop_requested = True
        if self.debug: print( "[PresentationOrchestratorAgent] Stop requested" )

    def _check_stop( self ) -> bool:
        """
        Check if stop has been requested.

        Returns:
            bool: True if stop was requested
        """
        return self._stop_requested

    async def _handle_stop( self ) -> None:
        """Handle graceful stop — update state and notify."""
        self.state = OrchestratorState.CANCELLED
        await voice_io.notify( "Presentation generation cancelled.", priority="medium" )
        if self.debug: print( "[PresentationOrchestratorAgent] Stopped gracefully" )

    # =========================================================================
    # State Query
    # =========================================================================

    def get_state( self ) -> dict:
        """
        Return current orchestrator state for external monitoring.

        Ensures:
            - Returns dict with state, presentation_id, metrics, internal state

        Returns:
            dict: Current state snapshot
        """
        return {
            "state"           : self.state.value,
            "presentation_id" : self.presentation_id,
            "source_path"     : self.source_path,
            "metrics"         : self.metrics,
            "internal_state"  : {
                k: v is not None for k, v in self._presentation_state.items()
                if k not in ( "user_id", "source_path" )
            },
        }

    # =========================================================================
    # Main Execution
    # =========================================================================

    async def do_all_async( self ) -> Optional[ PresentationModel ]:
        """
        Main execution — run all phases sequentially.

        Yields on I/O, doesn't block other jobs.

        Ensures:
            - Progresses through all phases in order
            - Checks for stop request between phases
            - Returns PresentationModel on success, None if cancelled

        Returns:
            PresentationModel or None if cancelled/failed
        """
        self.metrics[ "start_time" ] = cu.get_current_datetime_iso()

        try:
            # Phase 1: Ingest
            self.state = OrchestratorState.INGESTING
            await voice_io.notify( "Phase 1: Ingesting source document...", priority="low" )
            source_content = await self._ingest_async()
            self._presentation_state[ "source_content" ] = source_content
            if self._check_stop(): await self._handle_stop(); return None

            # Phase 2: Analyze
            self.state = OrchestratorState.ANALYZING
            await voice_io.notify( "Phase 2: Analyzing narrative structure...", priority="low" )
            narrative_sections = await self._analyze_async( source_content )
            self._presentation_state[ "narrative_sections" ] = narrative_sections
            if self._check_stop(): await self._handle_stop(); return None

            # D6-STRICT fail-loud guard: a non-stopped empty result is a degenerate
            # deck — fail the job loudly rather than silently building nothing.
            # (Ordered AFTER the stop-check so a user-requested stop still cancels.)
            if not narrative_sections:
                raise ValueError( "Phase 2 (narrative analysis) produced no sections — failing the job (D6-STRICT)" )

            # Gate 1: Narrative arc review (stub — auto-approve)
            gate1_approved = await self._gate_1_narrative_review( narrative_sections )
            if not gate1_approved: await self._handle_stop(); return None

            # Phase 3: Outline
            self.state = OrchestratorState.OUTLINING
            await voice_io.notify( "Phase 3: Generating slide outline...", priority="low" )
            slide_outline = await self._outline_async( narrative_sections )
            self._presentation_state[ "slide_outline" ] = slide_outline
            if self._check_stop(): await self._handle_stop(); return None

            # D6-STRICT fail-loud guard (see Phase 2 note).
            if not slide_outline:
                raise ValueError( "Phase 3 (slide outline) produced no entries — failing the job (D6-STRICT)" )

            # Gate 2: Slide titles + visual types review (stub — auto-approve)
            gate2_approved = await self._gate_2_outline_review( slide_outline )
            if not gate2_approved: await self._handle_stop(); return None

            # Phase 4: Elaborate
            self.state = OrchestratorState.ELABORATING
            await voice_io.notify( "Phase 4: Elaborating slide content...", priority="low" )
            elaborated_slides = await self._elaborate_async( slide_outline )
            self._presentation_state[ "elaborated_slides" ] = elaborated_slides
            if self._check_stop(): await self._handle_stop(); return None

            # D6-STRICT fail-loud guard (see Phase 2 note).
            if not elaborated_slides:
                raise ValueError( "Phase 4 (slide elaboration) produced no slides — failing the job (D6-STRICT)" )

            # Gate 3: Full content review (stub — auto-approve)
            gate3_approved = await self._gate_3_content_review( elaborated_slides )
            if not gate3_approved: await self._handle_stop(); return None

            # Phase 5: Serialize
            self.state = OrchestratorState.SERIALIZING
            await voice_io.notify( "Phase 5: Serializing to YAML...", priority="low" )
            presentation_model = await self._serialize_async( elaborated_slides )
            self._presentation_state[ "presentation_model" ] = presentation_model
            if self._check_stop(): await self._handle_stop(); return None

            # Phase 6: Render Text
            self.state = OrchestratorState.RENDERING_TEXT
            await voice_io.notify( "Phase 6: Rendering Marp Markdown...", priority="low" )
            await self._render_text_async( presentation_model )
            if self._check_stop(): await self._handle_stop(); return None

            # Phase 7: Render Visuals
            self.state = OrchestratorState.RENDERING_VISUALS
            await voice_io.notify( "Phase 7: Rendering visual elements...", priority="low" )
            await self._render_visuals_async( presentation_model )
            if self._check_stop(): await self._handle_stop(); return None

            # Gate 4: Final rendered output review (stub — auto-approve)
            gate4_approved = await self._gate_4_render_review( presentation_model )
            if not gate4_approved: await self._handle_stop(); return None

            # Phase 8: Deliver
            self.state = OrchestratorState.DELIVERING
            await voice_io.notify( "Phase 8: Delivering final artifacts...", priority="low" )
            await self._deliver_async( presentation_model )

            # Phase 8.5: PPTX Export
            await voice_io.notify( "Phase 8.5: Exporting PowerPoint...", priority="low" )
            await self._export_pptx_async( presentation_model )

            # Complete
            self.state = OrchestratorState.COMPLETED
            self.metrics[ "end_time" ] = cu.get_current_datetime_iso()
            await voice_io.notify( "Presentation generation complete!", priority="medium" )

            return presentation_model

        except Exception as e:
            self.state = OrchestratorState.FAILED
            self.metrics[ "end_time" ] = cu.get_current_datetime_iso()
            logger.error( f"Presentation generation failed: {e}" )
            await voice_io.notify( f"Presentation generation failed: {str( e )[ :100 ]}", priority="urgent" )
            raise

    async def render_from_yaml_async( self, yaml_path: str ) -> Optional[ PresentationModel ]:
        """
        Render-only mode: load existing YAML intermediate, run Phases 6-8 only.

        Skips content generation (Phases 1-5) and gates 1-3.
        Gate 4 (rendered output review) still fires.

        Requires:
            - yaml_path is a valid path to a presentation YAML file
            - File was produced by Phase 5 (PresentationModel.to_yaml())

        Ensures:
            - Phases 6-8 execute with the loaded PresentationModel
            - New Marp + visuals output files are generated
            - Returns PresentationModel on success, None if cancelled/failed
        """
        self.metrics[ "start_time" ] = cu.get_current_datetime_iso()

        try:
            # Load YAML intermediate
            await voice_io.notify( "Render-only: Loading YAML intermediate...", priority="low" )
            with open( yaml_path, "r", encoding="utf-8" ) as f:
                yaml_content = f.read()

            presentation = PresentationModel.from_yaml( yaml_content )
            if self.debug: print( f"[Orchestrator] Render-only: Loaded {presentation.total_slides} slides from {yaml_path}" )

            # Populate state needed by rendering phases
            self._presentation_state[ "yaml_path" ]         = yaml_path
            self._presentation_state[ "presentation_model" ] = presentation

            # Phase 6: Render Text
            self.state = OrchestratorState.RENDERING_TEXT
            await voice_io.notify( "Phase 6: Rendering Marp Markdown...", priority="low" )
            await self._render_text_async( presentation )
            if self._check_stop(): await self._handle_stop(); return None

            # Phase 7: Render Visuals
            self.state = OrchestratorState.RENDERING_VISUALS
            await voice_io.notify( "Phase 7: Rendering visual elements...", priority="low" )
            await self._render_visuals_async( presentation )
            if self._check_stop(): await self._handle_stop(); return None

            # Gate 4: Final rendered output review (stub — auto-approve)
            gate4_approved = await self._gate_4_render_review( presentation )
            if not gate4_approved: await self._handle_stop(); return None

            # Phase 8: Deliver
            self.state = OrchestratorState.DELIVERING
            await voice_io.notify( "Phase 8: Delivering final artifacts...", priority="low" )
            await self._deliver_async( presentation )

            # Phase 8.5: PPTX Export
            await voice_io.notify( "Phase 8.5: Exporting PowerPoint...", priority="low" )
            await self._export_pptx_async( presentation )

            # Complete
            self.state = OrchestratorState.COMPLETED
            self.metrics[ "end_time" ] = cu.get_current_datetime_iso()
            await voice_io.notify( "Render-only complete!", priority="medium" )

            return presentation

        except Exception as e:
            self.state = OrchestratorState.FAILED
            self.metrics[ "end_time" ] = cu.get_current_datetime_iso()
            logger.error( f"Render-only failed: {e}" )
            await voice_io.notify( f"Render-only failed: {str( e )[ :100 ]}", priority="urgent" )
            raise

    # =========================================================================
    # Phase Stubs (to be implemented in Phases 3-8)
    # =========================================================================

    async def _ingest_async( self ) -> Optional[ str ]:
        """
        Phase 1: Ingest source document.

        Reads the source file, detects its format (markdown/plaintext),
        extracts raw sections, and stores metadata in presentation state.

        Requires:
            - self.source_path is set to a file path

        Ensures:
            - Returns raw file content string on success
            - Returns None on file-not-found or read error
            - Populates self._presentation_state with source_content,
              source_format, raw_sections, word_count

        Returns:
            str or None: Source document content, or None on error
        """
        import cosa.utils.util as cu

        if self.debug: print( f"[Orchestrator] Phase 1: Ingest — {self.source_path}" )

        # Resolve path (relative → absolute using project root)
        path = self.source_path
        if not path.startswith( "/" ):
            path = cu.get_project_root() + "/" + path

        # Read file in thread pool (non-blocking)
        try:
            content = await asyncio.to_thread( self._read_file_or_raise, path )
        except FileNotFoundError:
            logger.error( f"Source document not found: {path}" )
            await voice_io.notify( f"Error: Source document not found — {os.path.basename( path )}", priority="urgent" )
            return None
        except Exception as e:
            logger.error( f"Failed to read source document: {e}" )
            await voice_io.notify( f"Error reading source document: {str( e )[ :80 ]}", priority="urgent" )
            return None

        if not content or not content.strip():
            logger.error( f"Source document is empty: {path}" )
            await voice_io.notify( "Error: Source document is empty", priority="urgent" )
            return None

        # Detect format
        source_format = self._detect_format( content )

        # Extract raw sections
        if source_format == "markdown":
            raw_sections = self._parse_markdown_sections( content )
        else:
            raw_sections = self._parse_plaintext_sections( content )

        # Calculate word count
        word_count = len( content.split() )

        # Store in presentation state
        self._presentation_state[ "source_content" ] = content
        self._presentation_state[ "source_format" ]  = source_format
        self._presentation_state[ "raw_sections" ]   = raw_sections
        self._presentation_state[ "word_count" ]     = word_count

        if self.debug:
            print( f"[Orchestrator] Ingested: {word_count} words, {len( raw_sections )} sections, format={source_format}" )

        await voice_io.notify(
            f"Document ingested: {word_count} words, {len( raw_sections )} sections",
            priority="low"
        )

        return content

    @staticmethod
    def _read_file_or_raise( path: str ) -> str:
        """
        Read a file and return its contents.

        Requires:
            - path is an absolute file path

        Ensures:
            - Returns file contents as string

        Raises:
            - FileNotFoundError if path does not exist
        """
        with open( path, "r", encoding="utf-8" ) as f:
            return f.read()

    @staticmethod
    def _detect_format( content: str ) -> str:
        """
        Detect whether content is markdown or plain text.

        Checks for markdown indicators: headings (#), code fences,
        bullet lists (- or *), links, bold/italic markers.

        Returns:
            str: "markdown" or "plaintext"
        """
        markdown_indicators = [
            r'^#{1,6}\s',      # Headings
            r'^```',            # Code fences
            r'^\s*[-*]\s',     # Bullet lists
            r'\[.*?\]\(.*?\)', # Links
            r'\*\*.*?\*\*',    # Bold
        ]
        lines = content[ :5000 ]  # Check first ~5000 chars for speed
        matches = 0
        for pattern in markdown_indicators:
            if re.search( pattern, lines, re.MULTILINE ):
                matches += 1
        return "markdown" if matches >= 2 else "plaintext"

    @staticmethod
    def _parse_markdown_sections( content: str ) -> List[ Tuple[ str, str, int ] ]:
        """
        Parse markdown content into sections by heading boundaries.

        Splits on heading patterns (# through ###). Skips YAML frontmatter
        (--- delimited blocks at start of file).

        Requires:
            - content is a non-empty markdown string

        Ensures:
            - Returns list of (heading, body, heading_level) tuples
            - If no headings found, returns single section with full content
            - Heading level: 1=H1, 2=H2, 3=H3

        Returns:
            List of (heading, body_text, heading_level) tuples
        """
        # Strip YAML frontmatter if present
        if content.startswith( "---" ):
            end_idx = content.find( "---", 3 )
            if end_idx != -1:
                content = content[ end_idx + 3: ].strip()

        # Split on heading lines (# through ###)
        # Pattern matches heading line + captures level and text
        heading_pattern = re.compile( r'^(#{1,3})\s+(.+)$', re.MULTILINE )
        matches = list( heading_pattern.finditer( content ) )

        if not matches:
            # No headings — treat entire content as single section
            return [ ( "(untitled)", content.strip(), 0 ) ]

        sections = []

        # Content before first heading (preamble)
        preamble = content[ :matches[ 0 ].start() ].strip()
        if preamble:
            sections.append( ( "(preamble)", preamble, 0 ) )

        # Extract sections between headings
        for i, match in enumerate( matches ):
            heading_level = len( match.group( 1 ) )
            heading_text  = match.group( 2 ).strip()

            # Body is content from after this heading to start of next heading (or end)
            body_start = match.end()
            body_end   = matches[ i + 1 ].start() if i + 1 < len( matches ) else len( content )
            body       = content[ body_start:body_end ].strip()

            sections.append( ( heading_text, body, heading_level ) )

        return sections

    @staticmethod
    def _parse_plaintext_sections( content: str ) -> List[ Tuple[ str, str, int ] ]:
        """
        Parse plain text content into sections by double-newline boundaries.

        Requires:
            - content is a non-empty string

        Ensures:
            - Returns list of (heading, body, level) tuples
            - Heading is auto-generated as "Section N"
            - Level is always 0 for plain text

        Returns:
            List of (heading, body_text, 0) tuples
        """
        paragraphs = re.split( r'\n\s*\n', content.strip() )
        paragraphs = [ p.strip() for p in paragraphs if p.strip() ]

        if not paragraphs:
            return [ ( "(empty)", "", 0 ) ]

        sections = []
        for i, para in enumerate( paragraphs, 1 ):
            sections.append( ( f"Section {i}", para, 0 ) )

        return sections

    async def _analyze_async( self, source_content: str ) -> List[ NarrativeSection ]:
        """
        Phase 2: Analyze narrative structure using Claude.

        Calls Claude API with the source content and narrative extraction prompt.
        Parses the response into NarrativeSection models.

        Requires:
            - source_content is a non-empty string
            - self._presentation_state has raw_sections from Phase 1

        Ensures:
            - Returns a non-empty list of NarrativeSection models on success
            - Increments metrics["api_calls"]

        Raises:
            - ValueError on parse failure / empty result (D6-STRICT fail-loud) —
              propagates to do_all_async, which marks the job FAILED
            - Returns empty list ONLY on a non-parse API/runtime error (e.g. the
              API call itself raised); do_all_async's empty-result guard then
              fails the job loudly

        Returns:
            List[NarrativeSection]: Classified document sections
        """
        from .prompts.narrative import (
            NARRATIVE_ANALYSIS_SYSTEM_PROMPT,
            get_narrative_analysis_prompt,
            parse_analysis_response,
        )
        from .state import ArcPosition

        raw_sections = self._presentation_state.get( "raw_sections", [] )

        # Dry-run: generate mock NarrativeSections from parsed sections
        if self.dry_run:
            if self.debug: print( "[Orchestrator] Phase 2: Analyze — DRY RUN (mock)" )
            arc_cycle = [ ArcPosition.SETUP, ArcPosition.ARGUMENT, ArcPosition.EVIDENCE,
                          ArcPosition.CONCLUSION, ArcPosition.CTA ]
            sections = []
            for i, ( heading, body, level ) in enumerate( raw_sections or [] ):
                sections.append( NarrativeSection(
                    heading         = heading or f"Section {i + 1}",
                    content         = ( body or "" )[ :200 ],
                    arc_position    = arc_cycle[ i % len( arc_cycle ) ],
                    proposed_slides = max( 1, len( ( body or "" ).split() ) // 100 ),
                ) )
            if not sections:
                sections = [ NarrativeSection( heading="Mock Section", content="Mock content", arc_position=ArcPosition.ARGUMENT, proposed_slides=3 ) ]
            await voice_io.notify( f"[DRY RUN] Mock analysis: {len( sections )} sections", priority="low" )
            return sections

        if self.debug: print( "[Orchestrator] Phase 2: Analyze — calling Claude" )

        try:
            # Build prompt
            prompt = get_narrative_analysis_prompt(
                source_content    = source_content,
                raw_sections      = raw_sections,
                target_duration   = self.config.target_duration_minutes,
                slides_per_minute = self.config.slides_per_minute,
                audience          = self.config.audience,
                audience_context  = getattr( self.config, "audience_context", None ),
            )

            # Call Claude
            response = await self.api_client.call_for_analysis(
                system_prompt = NARRATIVE_ANALYSIS_SYSTEM_PROMPT,
                user_message  = prompt,
            )
            self.metrics[ "api_calls" ] += 1

            # Parse response into section dicts.
            # D6-STRICT: parse_analysis_response RAISES ValueError on unrecoverable /
            # missing / empty / all-non-dict output. That ValueError must propagate
            # (see the dedicated `except ValueError` below) so a malformed LLM result
            # FAILS the job loudly rather than degrading to a degenerate empty deck.
            section_dicts = parse_analysis_response( response.content )

            if not section_dicts:
                # Defensive backstop: the strict parser does not return an empty list
                # (it raises first), but a future/mocked parser could. Fail loud —
                # zero structured content is a real defect, not a silent no-op.
                logger.error( "Narrative analysis produced no sections — failing the job (D6-STRICT)" )
                raise ValueError( "Narrative analysis produced no usable sections" )

            # Convert dicts to NarrativeSection models
            narrative_sections = []
            for sd in section_dicts:
                # Map arc_position string to ArcPosition enum
                try:
                    arc_pos = ArcPosition( sd[ "arc_position" ] )
                except ValueError:
                    arc_pos = ArcPosition.ARGUMENT

                section = NarrativeSection(
                    heading         = sd[ "heading" ],
                    content         = sd.get( "content_summary", "" ),
                    arc_position    = arc_pos,
                    proposed_slides = sd.get( "proposed_slide_count", 1 ),
                )
                narrative_sections.append( section )

            # Calculate totals
            total_proposed = sum( s.proposed_slides for s in narrative_sections )
            slide_budget = int( self.config.target_duration_minutes * self.config.slides_per_minute )

            if self.debug:
                print( f"[Orchestrator] Narrative analysis: {len( narrative_sections )} sections, "
                       f"{total_proposed} proposed slides (budget: {slide_budget})" )

            await voice_io.notify(
                f"Narrative analysis complete: {len( narrative_sections )} sections, "
                f"{total_proposed} proposed slides",
                priority="low"
            )

            return narrative_sections

        except ValueError as e:
            # D6-STRICT fail-loud: a parse/empty failure is a real defect (slide data
            # feeds pptx rendering). Do NOT swallow into an empty deck — notify and
            # re-raise so do_all_async marks the job FAILED.
            logger.error( f"Narrative analysis parse failure (fail-loud): {e}" )
            if self.debug:
                import traceback
                traceback.print_exc()
            await voice_io.notify( f"Narrative analysis failed: {str( e )[ :80 ]}", priority="urgent" )
            raise

        except Exception as e:
            logger.error( f"Narrative analysis failed: {e}" )
            if self.debug:
                import traceback
                traceback.print_exc()
            await voice_io.notify( f"Narrative analysis error: {str( e )[ :80 ]}", priority="urgent" )
            return []

    async def _outline_async( self, narrative_sections: List[ NarrativeSection ] ) -> List[ SlideOutline ]:
        """
        Phase 3: Generate slide outline with titles + visual types.

        Calls Claude to transform narrative sections into a slide-by-slide
        outline with assertion-style titles and visual type assignments.

        Requires:
            - narrative_sections is a non-empty list of NarrativeSection models

        Ensures:
            - Returns a non-empty list of SlideOutline models on success
            - Increments metrics["api_calls"]

        Raises:
            - ValueError on parse failure / empty result (D6-STRICT fail-loud) —
              propagates to do_all_async, which marks the job FAILED
            - Returns empty list ONLY on a non-parse API/runtime error

        Returns:
            List[SlideOutline]: Slide outline entries
        """
        from .prompts.outline import (
            OUTLINE_SYSTEM_PROMPT,
            get_outline_prompt,
            parse_outline_response,
            SLIDE_TYPES,
        )

        slide_budget = int( self.config.target_duration_minutes * self.config.slides_per_minute )

        # Dry-run: generate mock SlideOutlines from narrative sections
        if self.dry_run:
            if self.debug: print( "[Orchestrator] Phase 3: Outline — DRY RUN (mock)" )
            outlines = []
            # Structural formula: 2 opening + N body + 3 closing
            opening_types = [ ( "title", "text_only" ), ( "hook", "chart" ) ]
            closing_types = [ ( "summary", "text_only" ), ( "cta", "text_only" ), ( "qa", "text_only" ) ]
            body_count    = max( 1, slide_budget - len( opening_types ) - len( closing_types ) )

            slide_num = 1
            for stype, vtype in opening_types:
                outlines.append( SlideOutline( number=slide_num, arc_position="opening", type=stype,
                    title=f"[Mock] {stype.title()} Slide", visual_type=vtype ) )
                slide_num += 1
            for i in range( body_count ):
                section = narrative_sections[ i % len( narrative_sections ) ] if narrative_sections else None
                heading = section.heading if section else f"Body Point {i + 1}"
                outlines.append( SlideOutline( number=slide_num, arc_position="body", type="key_point",
                    title=f"[Mock] {heading}", visual_type="diagram" if i % 3 == 0 else "text_only",
                    source_hint=heading ) )
                slide_num += 1
            for stype, vtype in closing_types:
                outlines.append( SlideOutline( number=slide_num, arc_position="closing", type=stype,
                    title=f"[Mock] {stype.title()} Slide", visual_type=vtype ) )
                slide_num += 1

            await voice_io.notify( f"[DRY RUN] Mock outline: {len( outlines )} slides", priority="low" )
            return outlines

        if self.debug: print( "[Orchestrator] Phase 3: Outline — calling Claude" )

        human_feedback = self._presentation_state.get( "human_feedback" )

        try:
            # Build prompt
            prompt = get_outline_prompt(
                narrative_sections = narrative_sections,
                slide_budget       = slide_budget,
                title_style        = self.config.title_style,
                audience           = self.config.audience,
                audience_context   = getattr( self.config, "audience_context", None ),
                human_feedback     = human_feedback,
            )

            # Call API
            response = await self.api_client.call_for_outline(
                system_prompt = OUTLINE_SYSTEM_PROMPT,
                user_message  = prompt,
            )

            self.metrics[ "api_calls" ] += 1
            if hasattr( response, "tokens_used" ):
                self.metrics[ "tokens_used" ] += response.tokens_used

            # Parse response
            outline_dicts = parse_outline_response( response.content )

            # Convert to SlideOutline models
            outlines = []
            for d in outline_dicts:
                outlines.append( SlideOutline(
                    number       = d[ "number" ],
                    arc_position = d[ "arc_position" ],
                    type         = d[ "type" ],
                    title        = d[ "title" ],
                    visual_type  = d[ "visual_type" ],
                    source_hint  = d.get( "source_hint" ),
                ) )

            # Validate structural formula
            opening_count = sum( 1 for o in outlines if o.arc_position == "opening" )
            body_count    = sum( 1 for o in outlines if o.arc_position == "body" )
            closing_count = sum( 1 for o in outlines if o.arc_position == "closing" )

            if self.debug:
                print( f"[Orchestrator] Outline: {len( outlines )} slides "
                       f"({opening_count} opening, {body_count} body, {closing_count} closing)" )

            if opening_count < 1 or closing_count < 1:
                logger.warning( f"Structural formula issue: {opening_count} opening, {closing_count} closing" )

            await voice_io.notify(
                f"Outline generated: {len( outlines )} slides "
                f"({opening_count} opening, {body_count} body, {closing_count} closing)",
                priority="low"
            )

            return outlines

        except ValueError as e:
            # D6-STRICT fail-loud: a parse/empty failure is a real defect — notify
            # and re-raise so do_all_async marks the job FAILED (no empty deck).
            logger.error( f"Outline generation parse failure (fail-loud): {e}" )
            if self.debug:
                import traceback
                traceback.print_exc()
            await voice_io.notify( f"Outline generation failed: {str( e )[ :80 ]}", priority="urgent" )
            raise

        except Exception as e:
            logger.error( f"Outline generation failed: {e}" )
            if self.debug:
                import traceback
                traceback.print_exc()
            await voice_io.notify( f"Outline generation error: {str( e )[ :80 ]}", priority="urgent" )
            return []

    async def _elaborate_async( self, slide_outline: List[ SlideOutline ] ) -> List[ SlideModel ]:
        """
        Phase 4: Elaborate full slide content with presenter notes.

        Calls Claude to produce fully elaborated slides from the outline
        and source document. Uses all-at-once strategy with chunked fallback
        if the response is truncated.

        Requires:
            - slide_outline is a non-empty list of SlideOutline models
            - self._presentation_state has source_content from Phase 1

        Ensures:
            - Returns a non-empty list of SlideModel instances on success
            - On a TRUNCATED response (stop_reason != "end_turn") that fails to
              parse, attempts the chunked fallback before failing
            - Increments metrics["api_calls"]

        Raises:
            - ValueError on a parse failure of a COMPLETE response, or when the
              chunked fallback still yields nothing (D6-STRICT fail-loud) —
              propagates to do_all_async, which marks the job FAILED
            - Returns empty list ONLY on a non-parse API/runtime error

        Returns:
            List[SlideModel]: Fully elaborated slides
        """
        from .prompts.elaboration import (
            ELABORATION_SYSTEM_PROMPT,
            get_elaboration_prompt,
            parse_elaboration_response,
        )
        from .state import PresenterNotes

        # Dry-run: generate mock SlideModels from outlines
        if self.dry_run:
            if self.debug: print( "[Orchestrator] Phase 4: Elaborate — DRY RUN (mock)" )
            avg_timing = ( self.config.target_duration_minutes * 60 ) // max( 1, len( slide_outline ) )
            slides = []
            for o in slide_outline:
                slides.append( SlideModel(
                    number             = o.number,
                    arc_position       = o.arc_position,
                    type               = o.type,
                    title              = o.title,
                    visual_type        = o.visual_type,
                    visual_description = f"[Mock visual: {o.visual_type}]" if o.visual_type != "text_only" else None,
                    content_bullets    = [ f"[Mock bullet {i + 1}]" for i in range( 3 ) ] if o.type not in ( "title", "qa" ) else [],
                    presenter_notes    = PresenterNotes(
                        transition     = f"[Mock transition to slide {o.number}]" if o.number > 1 else None,
                        talking_points = [ f"[Mock talking point {i + 1}]" for i in range( 2 ) ],
                        timing_seconds = avg_timing,
                    ),
                ) )
            await voice_io.notify( f"[DRY RUN] Mock elaboration: {len( slides )} slides", priority="low" )
            return slides

        if self.debug: print( "[Orchestrator] Phase 4: Elaborate — calling Claude" )

        source_content = self._presentation_state.get( "source_content", "" )
        human_feedback = self._presentation_state.get( "human_feedback" )

        try:
            # Build prompt
            prompt = get_elaboration_prompt(
                slide_outlines          = slide_outline,
                source_content          = source_content,
                target_duration_minutes = self.config.target_duration_minutes,
                audience                = self.config.audience,
                audience_context        = getattr( self.config, "audience_context", None ),
                human_feedback          = human_feedback,
            )

            # Call API
            response = await self.api_client.call_for_elaboration(
                system_prompt = ELABORATION_SYSTEM_PROMPT,
                user_message  = prompt,
            )

            self.metrics[ "api_calls" ] += 1
            if hasattr( response, "tokens_used" ):
                self.metrics[ "tokens_used" ] += response.tokens_used

            # Parse — with a truncation-aware chunked fallback.
            # D6-STRICT: parse_elaboration_response RAISES on unrecoverable / empty
            # output (it never returns []). We distinguish two cases:
            #   - TRUNCATED response (stop_reason != "end_turn"): the failure is a
            #     length artifact, not garbage — recover via the chunked fallback.
            #   - COMPLETE response that still fails to parse: a real defect — let
            #     the ValueError propagate (caught by `except ValueError` below).
            is_truncated = hasattr( response, "stop_reason" ) and response.stop_reason != "end_turn"
            try:
                slide_dicts = parse_elaboration_response( response.content )
            except ValueError:
                if not is_truncated:
                    raise   # complete-but-unparseable → fail loud
                slide_dicts = []

            if not slide_dicts:
                if is_truncated:
                    logger.warning( "Elaboration response truncated/unparseable, attempting chunked fallback" )
                    await voice_io.notify( "Response truncated — retrying in batches...", priority="low" )
                    slide_dicts = await self._elaborate_chunked( slide_outline, source_content, human_feedback )
                else:
                    # Complete response yielded zero usable slides → real defect.
                    raise ValueError( "Elaboration produced no usable slides" )

            if not slide_dicts:
                # Chunked fallback also produced nothing → fail loud (no empty deck).
                raise ValueError( "Elaboration produced no slides after truncation fallback" )

            # Convert to SlideModel instances
            slides = []
            for d in slide_dicts:
                notes_dict = d.get( "presenter_notes", {} )
                notes = PresenterNotes(
                    transition     = notes_dict.get( "transition" ),
                    talking_points = notes_dict.get( "talking_points", [] ),
                    timing_seconds = notes_dict.get( "timing_seconds", 60 ),
                    emphasis       = notes_dict.get( "emphasis" ),
                )
                slides.append( SlideModel(
                    number             = d[ "number" ],
                    arc_position       = d[ "arc_position" ],
                    type               = d[ "type" ],
                    title              = d[ "title" ],
                    subtitle           = d.get( "subtitle" ),
                    visual_type        = d[ "visual_type" ],
                    visual_description = d.get( "visual_description" ),
                    content_bullets    = d.get( "content_bullets", [] ),
                    presenter_notes    = notes,
                ) )

            # Calculate timing
            total_timing = sum( s.presenter_notes.timing_seconds for s in slides )
            total_minutes = total_timing / 60

            if self.debug:
                print( f"[Orchestrator] Elaboration: {len( slides )} slides, "
                       f"{total_minutes:.1f}m estimated speaking time" )

            await voice_io.notify(
                f"Content elaborated: {len( slides )} slides, "
                f"{total_minutes:.1f}m estimated speaking time",
                priority="low"
            )

            return slides

        except ValueError as e:
            # D6-STRICT fail-loud: a parse/empty failure is a real defect — notify
            # and re-raise so do_all_async marks the job FAILED (no empty deck).
            logger.error( f"Elaboration parse failure (fail-loud): {e}" )
            if self.debug:
                import traceback
                traceback.print_exc()
            await voice_io.notify( f"Elaboration failed: {str( e )[ :80 ]}", priority="urgent" )
            raise

        except Exception as e:
            logger.error( f"Elaboration failed: {e}" )
            if self.debug:
                import traceback
                traceback.print_exc()
            await voice_io.notify( f"Elaboration error: {str( e )[ :80 ]}", priority="urgent" )
            return []

    async def _elaborate_chunked(
        self,
        slide_outline: List[ SlideOutline ],
        source_content: str,
        human_feedback: Optional[ str ] = None,
    ) -> List[ dict ]:
        """
        Chunked fallback for elaboration when all-at-once response is truncated.

        Splits outline into batches of ~6 slides and calls API per batch.

        Returns:
            List of slide dicts (concatenated from all batches)
        """
        from .prompts.elaboration import (
            ELABORATION_SYSTEM_PROMPT,
            get_elaboration_prompt,
            parse_elaboration_response,
        )

        batch_size = 6
        all_dicts  = []

        for i in range( 0, len( slide_outline ), batch_size ):
            batch = slide_outline[ i : i + batch_size ]

            if self.debug:
                print( f"[Orchestrator] Chunked elaboration: slides {batch[ 0 ].number}-{batch[ -1 ].number}" )

            prompt = get_elaboration_prompt(
                slide_outlines          = batch,
                source_content          = source_content,
                target_duration_minutes = self.config.target_duration_minutes,
                audience                = self.config.audience,
                audience_context        = getattr( self.config, "audience_context", None ),
                human_feedback          = human_feedback,
            )

            response = await self.api_client.call_for_elaboration(
                system_prompt = ELABORATION_SYSTEM_PROMPT,
                user_message  = prompt,
            )
            self.metrics[ "api_calls" ] += 1

            batch_dicts = parse_elaboration_response( response.content )
            all_dicts.extend( batch_dicts )

        return all_dicts

    async def _serialize_async( self, elaborated_slides: List[ SlideModel ] ) -> Optional[ PresentationModel ]:
        """
        Phase 5: Serialize to YAML intermediate file.

        Builds a PresentationModel from elaborated slides and writes it to disk
        as a YAML intermediate file for rendering phases.

        Requires:
            - elaborated_slides is a list of SlideModel instances

        Ensures:
            - Returns PresentationModel with all fields populated
            - Writes YAML file to config-defined output path
            - Stores yaml_path in _presentation_state for job to read
            - Creates output directory if it doesn't exist

        Returns:
            PresentationModel or None on failure
        """
        if self.debug: print( "[Orchestrator] Phase 5: Serialize — building YAML" )

        try:
            # Derive title from first slide or source filename
            if elaborated_slides and elaborated_slides[ 0 ].type == "title":
                title = elaborated_slides[ 0 ].title
            else:
                title = os.path.splitext( os.path.basename( self.source_path ) )[ 0 ]

            # Build PresentationModel
            presentation = PresentationModel(
                title            = title,
                speaker          = "",
                date             = datetime.now().strftime( "%Y-%m-%d" ),
                duration_minutes = self.config.target_duration_minutes,
                source_document  = self.source_path,
                total_slides     = len( elaborated_slides ),
                slides           = elaborated_slides,
                theme            = self.config.default_theme,
            )

            # Serialize to YAML
            yaml_content = presentation.to_yaml()

            # Get output path
            user_id = self._presentation_state.get( "user_id", "unknown" )
            yaml_path = self.config.get_output_path( user_id, title, file_type="yaml" )

            # Write to disk in thread pool (non-blocking)
            loop = asyncio.get_event_loop()
            await loop.run_in_executor( None, self._write_yaml, yaml_path, yaml_content )

            # Store path for job to read
            self._presentation_state[ "yaml_path" ] = yaml_path

            if self.debug:
                print( f"[Orchestrator] YAML written: {yaml_path}" )
                print( f"[Orchestrator] YAML size: {len( yaml_content )} chars" )

            await voice_io.notify(
                f"YAML serialized: {len( elaborated_slides )} slides → {os.path.basename( yaml_path )}",
                priority="low"
            )

            return presentation

        except Exception as e:
            logger.error( f"Serialization failed: {e}" )
            if self.debug:
                import traceback
                traceback.print_exc()
            await voice_io.notify( f"Serialization error: {str( e )[ :80 ]}", priority="urgent" )
            return None

    @staticmethod
    def _write_yaml( yaml_path: str, yaml_content: str ) -> None:
        """
        Write YAML content to disk, creating directories as needed.

        Requires:
            - yaml_path is an absolute file path
            - yaml_content is a non-empty string

        Ensures:
            - Parent directory exists
            - File is written with UTF-8 encoding
        """
        os.makedirs( os.path.dirname( yaml_path ), exist_ok=True )
        with open( yaml_path, "w", encoding="utf-8" ) as f:
            f.write( yaml_content )

    @staticmethod
    def _write_marp( marp_path: str, marp_content: str ) -> None:
        """
        Write Marp Markdown content to disk, creating directories as needed.

        Requires:
            - marp_path is an absolute file path
            - marp_content is a non-empty string

        Ensures:
            - Parent directory exists
            - File is written with UTF-8 encoding
        """
        os.makedirs( os.path.dirname( marp_path ), exist_ok=True )
        with open( marp_path, "w", encoding="utf-8" ) as f:
            f.write( marp_content )

    @staticmethod
    def _load_theme_config( templates_path: str, theme_name: str, debug: bool = False ) -> dict:
        """
        Load theme configuration from YAML file.

        Requires:
            - templates_path is a relative path starting with /src/
            - theme_name is a non-empty string (e.g., "default")

        Ensures:
            - Returns dict with "theme" key containing config
            - Falls back to hardcoded defaults if file missing or invalid

        Returns:
            dict: Theme configuration
        """
        import cosa.utils.util as cu

        theme_path = cu.get_project_root() + templates_path + theme_name + ".yaml"

        if debug: print( f"[Orchestrator] Loading theme: {theme_path}" )

        try:
            if os.path.exists( theme_path ):
                with open( theme_path, "r", encoding="utf-8" ) as f:
                    config = yaml.safe_load( f )
                if isinstance( config, dict ) and "theme" in config:
                    if debug: print( f"[Orchestrator] Theme loaded: {theme_name}" )
                    return config
                else:
                    logger.warning( f"Theme file missing 'theme' key: {theme_path}" )
            else:
                logger.warning( f"Theme file not found: {theme_path}" )

        except Exception as e:
            logger.error( f"Failed to load theme '{theme_name}': {e}" )

        # Fallback to hardcoded defaults
        if debug: print( "[Orchestrator] Using fallback default theme" )
        from .renderers.marp_text_renderer import DEFAULT_THEME_CONFIG
        return DEFAULT_THEME_CONFIG

    async def _render_text_async( self, presentation: Optional[ PresentationModel ] ) -> None:
        """
        Phase 6: Render PresentationModel to Marp Markdown file.

        Loads theme configuration, calls MarpTextRenderer to produce
        Marp-compatible markdown, and writes to disk alongside the YAML.

        Requires:
            - presentation is a valid PresentationModel (not None)
            - self.config has templates_path and default_theme set

        Ensures:
            - Marp markdown file written to config-defined output path
            - self._presentation_state[ "marp_path" ] is set
            - File contains valid Marp frontmatter + slide separators
        """
        if presentation is None:
            logger.warning( "Phase 6: No presentation model — skipping text rendering" )
            return

        if self.debug: print( "[Orchestrator] Phase 6: Render Text — starting" )

        try:
            # Load theme configuration
            theme_config = self._load_theme_config(
                self.config.templates_path,
                self.config.default_theme,
                debug=self.debug
            )

            # Render Marp markdown (pure transformation, no I/O)
            from .renderers import MarpTextRenderer
            marp_content = MarpTextRenderer.render( presentation, theme_config )

            # Get output path (.md alongside .yaml)
            user_id   = self._presentation_state.get( "user_id", "unknown" )
            marp_path = self.config.get_output_path( user_id, presentation.title, file_type="md" )

            # Write to disk in thread pool (non-blocking)
            loop = asyncio.get_event_loop()
            await loop.run_in_executor( None, self._write_marp, marp_path, marp_content )

            # Store path for job to read
            self._presentation_state[ "marp_path" ] = marp_path

            if self.debug:
                file_size = len( marp_content.encode( "utf-8" ) )
                print( f"[Orchestrator] Marp written: {marp_path}" )
                print( f"[Orchestrator] Marp stats: {presentation.total_slides} slides, {file_size:,} bytes" )

            # Notify progress
            await voice_io.notify(
                f"Marp rendered: {presentation.total_slides} slides",
                priority="low"
            )

        except Exception as e:
            logger.error( f"Phase 6 failed: {e}", exc_info=True )
            await voice_io.notify(
                f"Marp rendering failed: {str( e )[ :100 ]}",
                priority="urgent"
            )
            # Non-fatal — marp_path stays None, job delivers YAML only

    async def _render_visuals_async( self, presentation: Optional[ PresentationModel ] ) -> None:
        """
        Phase 7: Replace visual placeholders in Marp file with rendered content.

        Reads the Marp Markdown file (from Phase 6), finds all
        <!-- VISUAL: type | description --> placeholders, dispatches each
        to the appropriate visual renderer, and rewrites the file.

        Requires:
            - presentation is a valid PresentationModel
            - self._presentation_state[ "marp_path" ] is set by Phase 6

        Ensures:
            - Marp file updated with rendered visuals (Mermaid blocks, placeholders)
            - self._presentation_state[ "visuals_rendered" ] is set
        """
        marp_path = self._presentation_state.get( "marp_path" )

        if presentation is None or marp_path is None:
            logger.warning( "Phase 7: No presentation or marp_path — skipping visual rendering" )
            return

        if self.debug: print( "[Orchestrator] Phase 7: Render Visuals — starting" )

        try:
            # Read current Marp file
            loop = asyncio.get_event_loop()
            marp_content = await loop.run_in_executor( None, self._read_file_or_none, marp_path )
            if marp_content is None:
                logger.warning( f"Phase 7: Could not read Marp file: {marp_path}" )
                return

            # Find all visual placeholders
            placeholder_pattern = re.compile( r"<!-- VISUAL: (\S+) \| (.+?) -->" )
            matches = list( placeholder_pattern.finditer( marp_content ) )

            if not matches:
                if self.debug: print( "[Orchestrator] Phase 7: No visual placeholders found" )
                self._presentation_state[ "visuals_rendered" ] = 0
                return

            # Build renderer registry
            registry = self._build_visual_registry()

            # Create visuals directory for file-producing renderers (e.g., MatplotlibRenderer)
            marp_dir    = os.path.dirname( marp_path )
            visuals_dir = os.path.join( marp_dir, "visuals" )
            os.makedirs( visuals_dir, exist_ok=True )

            # Build slide title lookup from presentation
            slide_titles = {}
            for slide in presentation.slides:
                if slide.visual_type != "text_only" and slide.visual_description:
                    slide_titles[ slide.visual_description ] = slide.title

            # Replace each placeholder
            visuals_rendered = 0
            replacements     = []

            for i, match in enumerate( matches ):
                visual_type = match.group( 1 )
                visual_desc = match.group( 2 )
                slide_title = slide_titles.get( visual_desc, "" )

                renderer = registry.get( visual_type )
                rendered = await renderer.render(
                    visual_type        = visual_type,
                    visual_description = visual_desc,
                    api_client         = self.api_client if not self.dry_run else None,
                    slide_title        = slide_title,
                    output_dir         = visuals_dir,
                    slide_index        = i,
                )

                if rendered is None:
                    # Fall back to placeholder
                    from .renderers import PlaceholderRenderer
                    fallback = PlaceholderRenderer()
                    rendered = await fallback.render( visual_type, visual_desc )

                replacements.append( ( match.group( 0 ), rendered ) )
                visuals_rendered += 1

                if self.debug: print( f"[Orchestrator] Visual {visuals_rendered}/{len( matches )}: {visual_type} for '{slide_title[ :30 ]}'" )

            # Apply replacements
            for original, replacement in replacements:
                marp_content = marp_content.replace( original, replacement )

            # Rewrite file
            await loop.run_in_executor( None, self._write_marp, marp_path, marp_content )

            self._presentation_state[ "visuals_rendered" ] = visuals_rendered

            if self.debug:
                print( f"[Orchestrator] Phase 7 complete: {visuals_rendered} visuals rendered" )

            await voice_io.notify(
                f"Visuals rendered: {visuals_rendered} visual{'s' if visuals_rendered != 1 else ''}",
                priority="low"
            )

        except Exception as e:
            logger.error( f"Phase 7 failed: {e}", exc_info=True )
            await voice_io.notify(
                f"Visual rendering failed: {str( e )[ :100 ]}",
                priority="urgent"
            )
            # Non-fatal — visuals stay as placeholders

    def _build_visual_registry( self ) -> "VisualRendererRegistry":
        """
        Build the visual renderer registry for Phase 7.

        In dry_run mode, all types use PlaceholderRenderer (no API calls).

        Returns:
            VisualRendererRegistry: Configured registry
        """
        from .renderers import VisualRendererRegistry, MermaidRenderer, PlaceholderRenderer, MatplotlibRenderer, D2Renderer, NanoBananaRenderer, VeoRenderer

        fallback = PlaceholderRenderer()
        registry = VisualRendererRegistry( fallback=fallback, debug=self.debug )

        if not self.dry_run:
            mermaid = MermaidRenderer( debug=self.debug, verbose=self.verbose )
            registry.register( mermaid )
            matplotlib_renderer = MatplotlibRenderer( debug=self.debug, verbose=self.verbose )
            registry.register( matplotlib_renderer )
            d2_renderer = D2Renderer( debug=self.debug, verbose=self.verbose )
            registry.register( d2_renderer )

            # Gemini-backed renderers (shared client, shared API key)
            # Wrapped in try/except because Gemini API key may not be configured
            try:
                from .gemini_client import GeminiImageClient
                veo_model     = self.config.veo_model if hasattr( self, "config" ) else "veo-2.0-generate-001"
                gemini_client = GeminiImageClient( video_model=veo_model, debug=self.debug )

                nano_banana = NanoBananaRenderer( gemini_client=gemini_client, debug=self.debug, verbose=self.verbose )
                registry.register( nano_banana )

                veo = VeoRenderer( gemini_client=gemini_client, debug=self.debug, verbose=self.verbose )
                registry.register( veo )
            except Exception as e:
                logger.warning( f"Gemini renderers unavailable (API key missing?): {e}" )

        return registry

    @staticmethod
    def _read_file_or_none( file_path: str ) -> Optional[ str ]:
        """
        Read file content from disk.

        Requires:
            - file_path is an absolute path

        Ensures:
            - Returns file content string, or None on error

        Returns:
            str or None
        """
        try:
            with open( file_path, "r", encoding="utf-8" ) as f:
                return f.read()
        except Exception as e:
            logger.error( f"Failed to read file: {file_path}: {e}" )
            return None

    async def _deliver_async( self, presentation: Optional[ PresentationModel ] ) -> None:
        """
        Phase 8: Verify and summarize all generated artifacts.

        The job (job.py) handles artifact collection, cost summary,
        clickable links, and completion notifications. This method
        verifies file existence and builds a delivery summary dict
        for the job to read.

        Requires:
            - presentation is a valid PresentationModel
            - _presentation_state has yaml_path and marp_path from Phases 5-6

        Ensures:
            - delivery_summary stored in _presentation_state
            - All artifact paths verified on disk
            - Total timing calculated from presenter notes
        """
        if presentation is None:
            logger.warning( "Phase 8: No presentation model — skipping delivery" )
            return

        if self.debug: print( "[Orchestrator] Phase 8: Deliver — building summary" )

        yaml_path        = self._presentation_state.get( "yaml_path" )
        marp_path        = self._presentation_state.get( "marp_path" )
        visuals_rendered = self._presentation_state.get( "visuals_rendered", 0 )

        # Verify files exist
        artifacts_verified = {}
        for name, path in [ ( "yaml", yaml_path ), ( "marp", marp_path ) ]:
            if path and os.path.exists( path ):
                file_size = os.path.getsize( path )
                artifacts_verified[ name ] = { "path": path, "size_bytes": file_size, "exists": True }
            else:
                artifacts_verified[ name ] = { "path": path, "size_bytes": 0, "exists": False }
                if path: logger.warning( f"Phase 8: Artifact missing: {name} = {path}" )

        # Calculate total estimated speaking time
        total_timing = sum(
            slide.presenter_notes.timing_seconds
            for slide in presentation.slides
            if slide.presenter_notes and slide.presenter_notes.timing_seconds
        )

        # Build delivery summary
        delivery_summary = {
            "total_slides"      : presentation.total_slides,
            "total_timing_secs" : total_timing,
            "total_timing_min"  : round( total_timing / 60, 1 ),
            "visuals_rendered"  : visuals_rendered,
            "artifacts"         : artifacts_verified,
            "theme"             : presentation.theme,
        }

        self._presentation_state[ "delivery_summary" ] = delivery_summary

        if self.debug:
            print( f"[Orchestrator] Delivery summary:" )
            print( f"  Slides: {presentation.total_slides}" )
            print( f"  Est. duration: {delivery_summary[ 'total_timing_min' ]}m" )
            print( f"  Visuals: {visuals_rendered}" )
            for name, info in artifacts_verified.items():
                status = "OK" if info[ "exists" ] else "MISSING"
                print( f"  {name}: {status} ({info[ 'size_bytes' ]:,} bytes)" )

    async def _export_pptx_async( self, presentation: Optional[ PresentationModel ] ) -> None:
        """
        Phase 8.5: Export Marp Markdown to PowerPoint via Marp CLI.

        Requires:
            - presentation is a valid PresentationModel
            - self._presentation_state[ "marp_path" ] is set by Phase 6
            - self.config.pptx_export_enabled is True
            - Marp CLI binary available in PATH

        Ensures:
            - PPTX file written alongside .md and .yaml
            - self._presentation_state[ "pptx_path" ] set on success
            - Non-fatal: MD + YAML still delivered if PPTX export fails
        """
        if not self.config.pptx_export_enabled:
            if self.debug: print( "[Orchestrator] PPTX export disabled in config" )
            return

        if self.dry_run:
            if self.debug: print( "[Orchestrator] PPTX export skipped (dry run)" )
            return

        marp_path = self._presentation_state.get( "marp_path" )
        if not marp_path or not os.path.exists( marp_path ):
            logger.warning( "Phase 8.5: No marp_path — skipping PPTX export" )
            return

        try:
            user_id = self._presentation_state.get( "user_id", "unknown" )
            pptx_path = self.config.get_output_path( user_id, presentation.title, file_type="pptx" )
            marp_dir  = os.path.dirname( marp_path )

            if self.debug: print( f"[Orchestrator] Phase 8.5: Exporting PPTX → {pptx_path}" )

            proc = await asyncio.create_subprocess_exec(
                "marp", "--pptx", "--allow-local-files", marp_path, "-o", pptx_path,
                cwd    = marp_dir,
                stdout = asyncio.subprocess.PIPE,
                stderr = asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()

            if proc.returncode != 0:
                error_msg = stderr.decode( "utf-8", errors="replace" ).strip()
                logger.warning( f"Phase 8.5: Marp CLI exited {proc.returncode}: {error_msg[ :200 ]}" )
                await voice_io.notify( f"PPTX export failed: {error_msg[ :100 ]}", priority="medium" )
                return

            self._presentation_state[ "pptx_path" ] = pptx_path

            file_size = os.path.getsize( pptx_path ) if os.path.exists( pptx_path ) else 0
            if self.debug: print( f"[Orchestrator] PPTX written: {pptx_path} ({file_size:,} bytes)" )

            await voice_io.notify( f"PPTX exported: {file_size // 1024}KB", priority="low" )

        except FileNotFoundError:
            logger.warning( "Phase 8.5: Marp CLI binary not found in PATH — skipping PPTX export" )
            await voice_io.notify( "PPTX export skipped: Marp CLI not installed", priority="medium" )
        except Exception as e:
            logger.error( f"Phase 8.5 failed: {e}", exc_info=True )
            await voice_io.notify( f"PPTX export failed: {str( e )[ :100 ]}", priority="medium" )

    # =========================================================================
    # Gate Stubs (to be implemented in Phases 3-4)
    # =========================================================================

    async def _gate_1_narrative_review( self, sections: List[ NarrativeSection ] ) -> bool:
        """
        Gate 1: User reviews narrative arc mapping.

        Presents the extracted narrative arc to the user via voice I/O.
        Supports approve, revise (with feedback), or cancel.

        Requires:
            - sections is a list of NarrativeSection models

        Ensures:
            - Returns True if user approves (proceed to outline)
            - Returns False if user cancels (orchestrator stops)
            - On revise: re-runs analysis with feedback, up to max_revisions

        Args:
            sections: List of NarrativeSection models from Phase 2

        Returns:
            bool: True to proceed, False to stop
        """
        if not sections:
            # D6-STRICT: empty sections is NOT something to auto-approve — there is
            # no narrative arc to proceed with. Do NOT proceed (the do_all_async
            # empty-guard fails the main path loudly before this gate is reached;
            # this also covers the recursive re-analysis path).
            if self.debug: print( "[Orchestrator] Gate 1: No sections to review — refusing to proceed" )
            return False

        if self.dry_run:
            if self.debug: print( "[Orchestrator] Gate 1: DRY RUN — auto-approve" )
            return True

        revision_count = self._presentation_state.get( "revision_count", 0 )
        max_revisions  = self.config.max_revisions

        # Build summary for user
        total_slides = sum( s.proposed_slides for s in sections )
        slide_budget = int( self.config.target_duration_minutes * self.config.slides_per_minute )

        summary_lines = [ f"**Narrative Arc Analysis** ({len( sections )} sections, {total_slides} proposed slides, budget: {slide_budget})\n" ]
        for i, section in enumerate( sections, 1 ):
            summary_lines.append(
                f"{i}. **{section.heading}** — {section.arc_position.value} ({section.proposed_slides} slide{'s' if section.proposed_slides != 1 else ''})"
            )

        summary = "\n".join( summary_lines )

        if self.debug: print( f"[Orchestrator] Gate 1: Presenting narrative arc for review" )

        # Present to user via voice I/O
        try:
            result = await voice_io.present_choices(
                questions=[ {
                    "question" : "How does this narrative arc look for your presentation?",
                    "header"   : "Narrative Arc",
                    "multiSelect" : False,
                    "options"  : [
                        { "label": "Approve", "description": "Proceed to slide outline generation" },
                        { "label": "Revise",  "description": f"Re-analyze with feedback ({max_revisions - revision_count} revisions remaining)" },
                        { "label": "Cancel",  "description": "Stop presentation generation" },
                    ]
                } ],
                title    = "Gate 1: Narrative Arc Review",
                abstract = summary,
            )

            # Parse response
            answer = result.get( "answers", {} ).get( "Narrative Arc", "Approve" )

            if answer == "Cancel":
                await voice_io.notify( "Presentation generation cancelled at Gate 1.", priority="medium" )
                return False

            elif answer == "Revise":
                if revision_count >= max_revisions:
                    await voice_io.notify(
                        f"Maximum revisions ({max_revisions}) reached. Proceeding with current analysis.",
                        priority="medium"
                    )
                    return True

                # Get feedback via open-ended input
                feedback = await voice_io.get_input(
                    "What changes would you like to the narrative arc? For example: 'merge sections 3 and 4' or 'the conclusion needs more slides'."
                )

                if feedback:
                    self._presentation_state[ "revision_count" ] = revision_count + 1
                    self._presentation_state[ "human_feedback" ] = feedback

                    await voice_io.notify( "Re-analyzing with your feedback...", priority="low" )

                    # Re-run analysis with feedback appended
                    source_content = self._presentation_state.get( "source_content", "" )
                    new_sections = await self._analyze_async( source_content )
                    self._presentation_state[ "narrative_sections" ] = new_sections

                    # Recursive gate review with new sections
                    return await self._gate_1_narrative_review( new_sections )

                # Empty feedback — treat as approve
                return True

            else:
                # Approve (default)
                return True

        except Exception as e:
            # If voice I/O fails, auto-approve to not block the pipeline
            logger.warning( f"Gate 1 voice I/O failed, auto-approving: {e}" )
            if self.debug: print( f"[Orchestrator] Gate 1: Voice I/O error — auto-approve. {e}" )
            return True

    async def _gate_2_outline_review( self, outline: List[ SlideOutline ] ) -> bool:
        """
        Gate 2: User reviews slide titles + visual types (the "story spine").

        Presents the slide outline grouped by position (opening/body/closing)
        with assertion-style titles and visual types. Supports approve, revise
        (with feedback), or cancel.

        Requires:
            - outline is a list of SlideOutline models

        Ensures:
            - Returns True if user approves (proceed to elaboration)
            - Returns False if user cancels
            - On revise: re-runs outline with feedback, up to max_revisions

        Args:
            outline: List of SlideOutline models from Phase 3

        Returns:
            bool: True to proceed, False to stop
        """
        if not outline:
            # D6-STRICT: empty outline → nothing to proceed with; do NOT auto-approve.
            if self.debug: print( "[Orchestrator] Gate 2: No outline to review — refusing to proceed" )
            return False

        if self.dry_run:
            if self.debug: print( "[Orchestrator] Gate 2: DRY RUN — auto-approve" )
            return True

        revision_count = self._presentation_state.get( "outline_revision_count", 0 )
        max_revisions  = self.config.max_revisions

        # Build "story spine" summary grouped by position
        opening = [ o for o in outline if o.arc_position == "opening" ]
        body    = [ o for o in outline if o.arc_position == "body" ]
        closing = [ o for o in outline if o.arc_position == "closing" ]

        summary_lines = [
            f"**Slide Outline** ({len( outline )} slides: "
            f"{len( opening )} opening + {len( body )} body + {len( closing )} closing)\n"
        ]

        for label, group in [ ( "OPENING", opening ), ( "BODY", body ), ( "CLOSING", closing ) ]:
            if group:
                summary_lines.append( f"\n**{label}**:" )
                for o in group:
                    summary_lines.append( f"  {o.number}. [{o.type}] \"{o.title}\" ({o.visual_type})" )

        summary = "\n".join( summary_lines )

        if self.debug: print( "[Orchestrator] Gate 2: Presenting outline for review" )

        try:
            result = await voice_io.present_choices(
                questions=[ {
                    "question"    : "How does this slide outline look?",
                    "header"      : "Slide Outline",
                    "multiSelect" : False,
                    "options"     : [
                        { "label": "Approve", "description": "Proceed to content elaboration" },
                        { "label": "Revise",  "description": f"Re-generate outline with feedback ({max_revisions - revision_count} revisions remaining)" },
                        { "label": "Cancel",  "description": "Stop presentation generation" },
                    ]
                } ],
                title    = "Gate 2: Slide Outline Review",
                abstract = summary,
            )

            answer = result.get( "answers", {} ).get( "Slide Outline", "Approve" )

            if answer == "Cancel":
                await voice_io.notify( "Presentation generation cancelled at Gate 2.", priority="medium" )
                return False

            elif answer == "Revise":
                if revision_count >= max_revisions:
                    await voice_io.notify(
                        f"Maximum revisions ({max_revisions}) reached. Proceeding with current outline.",
                        priority="medium"
                    )
                    return True

                feedback = await voice_io.get_input(
                    "What changes would you like to the outline? For example: 'make slide 5 title more specific' or 'add a comparison slide before the summary'."
                )

                if feedback:
                    self._presentation_state[ "outline_revision_count" ] = revision_count + 1
                    self._presentation_state[ "human_feedback" ] = feedback

                    await voice_io.notify( "Re-generating outline with your feedback...", priority="low" )

                    narrative_sections = self._presentation_state.get( "narrative_sections", [] )
                    new_outline = await self._outline_async( narrative_sections )
                    self._presentation_state[ "slide_outline" ] = new_outline

                    # Recursive gate review with new outline
                    return await self._gate_2_outline_review( new_outline )

                # Empty feedback — treat as approve
                return True

            else:
                # Approve (default)
                # Clear human_feedback so it doesn't carry into elaboration
                self._presentation_state[ "human_feedback" ] = None
                return True

        except Exception as e:
            logger.warning( f"Gate 2 voice I/O failed, auto-approving: {e}" )
            if self.debug: print( f"[Orchestrator] Gate 2: Voice I/O error — auto-approve. {e}" )
            return True

    async def _gate_3_content_review( self, slides: List[ SlideModel ] ) -> bool:
        """
        Gate 3: User reviews full structured content.

        Presents a condensed summary of all elaborated slides with bullet counts,
        timing, and visual types. Supports approve, revise, or cancel.

        Requires:
            - slides is a list of SlideModel instances

        Ensures:
            - Returns True if user approves (proceed to serialization)
            - Returns False if user cancels
            - On revise: re-runs elaboration with feedback

        Args:
            slides: List of SlideModel instances from Phase 4

        Returns:
            bool: True to proceed, False to stop
        """
        if not slides:
            # D6-STRICT: empty slides → nothing to proceed with; do NOT auto-approve.
            if self.debug: print( "[Orchestrator] Gate 3: No slides to review — refusing to proceed" )
            return False

        if self.dry_run:
            if self.debug: print( "[Orchestrator] Gate 3: DRY RUN — auto-approve" )
            return True

        revision_count = self._presentation_state.get( "elaborate_revision_count", 0 )
        max_revisions  = self.config.max_revisions

        # Build condensed summary
        total_timing = sum( s.presenter_notes.timing_seconds for s in slides )
        total_minutes = total_timing / 60

        # Count visual types
        visual_counts = {}
        for s in slides:
            if s.visual_type != "text_only":
                visual_counts[ s.visual_type ] = visual_counts.get( s.visual_type, 0 ) + 1

        visual_summary = ", ".join( f"{vt}: {ct}" for vt, ct in sorted( visual_counts.items() ) )
        visual_total   = sum( visual_counts.values() )

        summary_lines = [
            f"**Full Content Review** ({len( slides )} slides, {total_minutes:.1f}m estimated)\n"
        ]

        for s in slides:
            bullet_info = f"{len( s.content_bullets )} bullets" if s.content_bullets else "no bullets"
            summary_lines.append(
                f"  {s.number}. \"{s.title}\" — {s.type}, {s.visual_type}, "
                f"{s.presenter_notes.timing_seconds}s, {bullet_info}"
            )

        summary_lines.append( f"\n**Total estimated**: {total_minutes:.1f}m (target: {self.config.target_duration_minutes}m)" )
        if visual_total > 0:
            summary_lines.append( f"**Slides with visuals**: {visual_total} of {len( slides )} ({visual_summary})" )

        summary = "\n".join( summary_lines )

        if self.debug: print( "[Orchestrator] Gate 3: Presenting content for review" )

        try:
            result = await voice_io.present_choices(
                questions=[ {
                    "question"    : "How does the elaborated content look?",
                    "header"      : "Content Review",
                    "multiSelect" : False,
                    "options"     : [
                        { "label": "Approve", "description": "Proceed to serialization" },
                        { "label": "Revise",  "description": f"Re-elaborate with feedback ({max_revisions - revision_count} revisions remaining)" },
                        { "label": "Cancel",  "description": "Stop presentation generation" },
                    ]
                } ],
                title    = "Gate 3: Content Review",
                abstract = summary,
            )

            answer = result.get( "answers", {} ).get( "Content Review", "Approve" )

            if answer == "Cancel":
                await voice_io.notify( "Presentation generation cancelled at Gate 3.", priority="medium" )
                return False

            elif answer == "Revise":
                if revision_count >= max_revisions:
                    await voice_io.notify(
                        f"Maximum revisions ({max_revisions}) reached. Proceeding with current content.",
                        priority="medium"
                    )
                    return True

                feedback = await voice_io.get_input(
                    "What changes would you like to the content? For example: 'slide 3 needs more data' or 'add a transition between slides 7 and 8'."
                )

                if feedback:
                    self._presentation_state[ "elaborate_revision_count" ] = revision_count + 1
                    self._presentation_state[ "human_feedback" ] = feedback

                    await voice_io.notify( "Re-elaborating with your feedback...", priority="low" )

                    slide_outline = self._presentation_state.get( "slide_outline", [] )
                    new_slides = await self._elaborate_async( slide_outline )
                    self._presentation_state[ "elaborated_slides" ] = new_slides

                    # Recursive gate review with new slides
                    return await self._gate_3_content_review( new_slides )

                # Empty feedback — treat as approve
                return True

            else:
                # Approve (default)
                self._presentation_state[ "human_feedback" ] = None
                return True

        except Exception as e:
            logger.warning( f"Gate 3 voice I/O failed, auto-approving: {e}" )
            if self.debug: print( f"[Orchestrator] Gate 3: Voice I/O error — auto-approve. {e}" )
            return True

    async def _gate_4_render_review( self, presentation: Optional[ PresentationModel ] ) -> bool:
        """
        Gate 4: User reviews final rendered output.

        Presents a summary of rendered visuals to the user for approval.
        In dry_run mode, auto-approves without voice interaction.

        Requires:
            - presentation is a PresentationModel (may be None)

        Ensures:
            - Returns True to proceed, False to cancel

        Returns:
            bool: True if approved, False if cancelled
        """
        if self.dry_run:
            if self.debug: print( "[Orchestrator] Gate 4: DRY RUN — auto-approve" )
            return True

        visuals_rendered = self._presentation_state.get( "visuals_rendered", 0 )

        if visuals_rendered == 0:
            if self.debug: print( "[Orchestrator] Gate 4: No visuals — auto-approve" )
            return True

        # Build summary
        marp_path = self._presentation_state.get( "marp_path", "N/A" )
        summary = (
            f"Visual rendering complete: {visuals_rendered} visual{'s' if visuals_rendered != 1 else ''} rendered.\n"
            f"Marp file: {marp_path}\n\n"
            f"Review the presentation and approve to proceed to delivery."
        )

        try:
            result = await voice_io.present_choices(
                questions=[ {
                    "question"    : f"Gate 4: {visuals_rendered} visual{'s' if visuals_rendered != 1 else ''} rendered. Approve?",
                    "header"      : "Visual Review",
                    "multiSelect" : False,
                    "options"     : [
                        { "label": "Approve", "description": "Proceed to delivery" },
                        { "label": "Cancel",  "description": "Stop presentation generation" },
                    ]
                } ],
                title    = "Gate 4: Visual Review",
                abstract = summary,
            )

            answer = result.get( "answers", {} ).get( "Visual Review", "Approve" )

            if answer == "Cancel":
                await voice_io.notify( "Presentation cancelled at Gate 4.", priority="medium" )
                return False

            return True

        except Exception as e:
            logger.warning( f"Gate 4 voice I/O failed: {e} — auto-approving" )
            return True


# =============================================================================
# Smoke Test
# =============================================================================

def quick_smoke_test():
    """Quick smoke test for PresentationOrchestratorAgent."""
    import cosa.utils.util as cu

    cu.print_banner( "PresentationOrchestratorAgent Smoke Test", prepend_nl=True )

    try:
        # Test 1: Construction
        print( "Testing orchestrator construction..." )
        agent = PresentationOrchestratorAgent(
            source_path = "/test/doc.md",
            user_id     = "test-user",
            debug       = True
        )
        assert agent.state == OrchestratorState.INITIALIZED
        assert agent.source_path == "/test/doc.md"
        assert agent.presentation_id.startswith( "pres-" )
        print( f"  Presentation ID: {agent.presentation_id}" )
        print( "  PASS" )

        # Test 2: get_state
        print( "Testing get_state..." )
        state = agent.get_state()
        assert state[ "state" ] == "initialized"
        assert state[ "presentation_id" ].startswith( "pres-" )
        assert "metrics" in state
        assert "internal_state" in state
        print( "  PASS" )

        # Test 3: Stop request
        print( "Testing stop request..." )
        assert agent._check_stop() is False
        agent.request_stop()
        assert agent._check_stop() is True
        print( "  PASS" )

        # Test 4: Default config
        print( "Testing default config..." )
        assert agent.config.target_duration_minutes == 15
        assert agent.config.slides_per_minute == 1.0
        print( "  PASS" )

        # Test 5: Async state progression (run stubs)
        print( "Testing async state progression..." )

        async def run_stub_phases():
            # Reset stop flag
            agent._stop_requested = False

            # Run phase 1 stub
            agent.state = OrchestratorState.INGESTING
            content = await agent._ingest_async()
            assert "[stub]" in content

            # Run phase 2 stub
            agent.state = OrchestratorState.ANALYZING
            sections = await agent._analyze_async( content )
            assert sections == []

            # D6-STRICT: content gates 1-3 REFUSE to proceed on empty input
            # (no auto-approve); the render gate (4) still auto-approves on None.
            assert await agent._gate_1_narrative_review( [] ) is False
            assert await agent._gate_2_outline_review( [] ) is False
            assert await agent._gate_3_content_review( [] ) is False
            assert await agent._gate_4_render_review( None ) is True

            return True

        result = asyncio.run( run_stub_phases() )
        assert result is True
        print( "  PASS" )

        print( "\nAll PresentationOrchestratorAgent smoke tests passed" )

    except Exception as e:
        print( f"\nSmoke test failed: {e}" )
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    quick_smoke_test()
