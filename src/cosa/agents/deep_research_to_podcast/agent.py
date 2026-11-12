#!/usr/bin/env python3
"""
Deep Research to Podcast Agent - Wrapper for chained workflow.

Orchestrates a pipeline: Deep Research → Podcast Generation.

This agent:
1. Runs Deep Research to produce a research report
2. Extracts the report path from Deep Research output
3. Passes the report to Podcast Generator
4. Returns combined results with both artifacts

Design Pattern: Wrapper Agent
- Composes two existing agents into a single workflow
- Handles modality (voice vs CLI) for both agents
- Tracks combined costs and artifacts
"""

import asyncio
import time
import os
from datetime import datetime
from typing import Optional, List

from cosa.agents.utils.agent_notification_dispatcher import set_dispatch_context
from cosa.agents.chained_pipeline_state import ChainedDeepResearchAgent
from .state import ChainedResult, PipelineState


class DeepResearchToPodcastAgent( ChainedDeepResearchAgent ):
    """
    Orchestrates a chained workflow: Deep Research → Podcast Generation.

    Requires:
        - query is a non-empty string (research topic)
        - user_email is a valid email address

    Ensures:
        - Runs Deep Research first
        - Extracts report_path from DR output
        - Passes report_path to Podcast Generator
        - Returns combined result with both artifacts

    Example:
        agent = DeepResearchToPodcastAgent(
            query      = "State of quantum computing in 2026",
            user_email = "researcher@example.com",
            budget     = 3.00,
            cli_mode   = True,  # Force text mode
        )
        result = await agent.run_async()
        print( f"Research: {result.research_path}" )
        print( f"Audio: {result.audio_path}" )
    """

    PIPELINE_STATE = PipelineState
    RESULT_CLASS   = ChainedResult
    STAGE_LABEL    = "Podcast Generation"

    def __init__(
        self,
        query: str,
        user_email: str,
        # Deep Research options
        budget: Optional[ float ] = None,
        lead_model: Optional[ str ] = None,
        no_confirm: bool = False,
        audience: Optional[ str ] = None,
        audience_context: Optional[ str ] = None,
        source_document: Optional[ list ] = None,
        # Podcast Generator options
        target_languages: Optional[ List[ str ] ] = None,
        max_segments: Optional[ int ] = None,
        script_type: Optional[ str ] = None,
        review: Optional[ str ] = None,
        # Common options
        cli_mode: bool = False,
        debug: bool = False,
        verbose: bool = False
    ):
        """
        Initialize the chained agent.

        Args:
            query: Research topic/question for Deep Research
            user_email: User email for output directories

            # Deep Research options
            budget: Maximum budget in USD for DR (None = unlimited)
            lead_model: Model for DR lead agent (None = use default)
            no_confirm: Skip confirmation prompts in DR
            audience: Expertise level (beginner/general/expert/academic)
            audience_context: Custom audience description
            source_document: Absolute paths to local documents the research leg reads
                first, as seed context. The v2 door has already scope-validated and
                resolved them; this constructor receives real paths.

            # Podcast Generator options
            target_languages: List of ISO language codes (default: ["en"])
            max_segments: Limit TTS to first N segments (cost control)
            script_type: Script type name (research_critical or status_report); None means research_critical
            review: Review mode (ask or one_shot); None means the script type's default

            # Common options
            cli_mode: Force CLI text mode (default: voice-driven)
            debug: Enable debug output
            verbose: Enable verbose output
        """
        super().__init__(
            query, user_email, budget=budget, lead_model=lead_model, no_confirm=no_confirm,
            audience=audience, audience_context=audience_context, source_document=source_document,
            cli_mode=cli_mode, debug=debug, verbose=verbose
        )

        # Podcast Generator options
        self.target_languages = target_languages or [ "en" ]
        self.max_segments     = max_segments
        self.script_type      = script_type
        self.review           = review
    def _stage_voice_io( self ):
        """Return the podcast generator's voice_io module."""
        from cosa.agents.podcast_generator import voice_io

        return voice_io

    async def _run_second_stage( self, research_path: str ) -> dict:
        """Run the Podcast Generator on the research report."""
        return await self._run_podcast_generator( research_path )

    def _store_second_stage_result( self, pg_result: dict ) -> None:
        """Keep the podcast's audio and script paths on the result."""
        self.result.audio_path  = pg_result.get( "audio_path" )
        self.result.script_path = pg_result.get( "script_path" )

    def _skipped_topic_names( self, dr_artifacts: dict ) -> list:
        """Name the research topics Deep Research skipped, so the checkpoint can say so."""
        return [ g[ "topic" ] for g in dr_artifacts.get( "skipped_topics", [] ) ]

    async def _run_podcast_generator( self, research_path: str ) -> dict:
        """
        Execute Podcast Generator on the research report.

        Args:
            research_path: Path to the Deep Research report

        Returns:
            dict with keys: audio_path, script_path, cost, artifacts, cancelled
        """
        self.result.state = PipelineState.RUNNING_PODCAST_GEN

        # Re-establish PG voice_io binding before podcast phase
        from cosa.agents.podcast_generator import voice_io as pg_voice_io
        from cosa.agents.podcast_generator import cosa_interface as pg_cosa_interface
        pg_voice_io.reconfigure()
        pg_cosa_interface.TARGET_USER = self.user_email
        set_dispatch_context( target_user=self.user_email )

        # Import Podcast Generator components
        from cosa.agents.podcast_generator.orchestrator import PodcastOrchestratorAgent
        from cosa.agents.podcast_generator.script_types import resolve_podcast_config
        import cosa.utils.util as cu

        # Validate research document exists
        if not os.path.exists( research_path ):
            raise Exception( f"Research document not found: {research_path}" )

        if self.debug:
            print( f"[PG] Research document: {research_path}" )
            print( f"[PG] Target languages: {self.target_languages}" )
            if self.max_segments:
                print( f"[PG] Max segments: {self.max_segments}" )

        # Request beats script-type profile beats INI
        from cosa.config.configuration_manager import ConfigurationManager
        config = resolve_podcast_config(
            ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" ),
            script_type      = self.script_type,
            review           = self.review,
            audience         = self.audience,
            audience_context = self.audience_context,
            debug            = self.debug,
        )

        # Create orchestrator
        agent = PodcastOrchestratorAgent(
            research_doc_path = research_path,
            user_id           = self.user_email,
            config            = config,
            target_languages  = self.target_languages,
            max_segments      = self.max_segments,
            debug             = self.debug,
            verbose           = self.verbose,
        )

        if self.debug:
            print( f"[PG] Podcast ID: {agent.podcast_id}" )

        # Run the workflow
        script = await agent.do_all_async()

        if script is None:
            return { "cancelled": True }

        # Get results from agent state
        state = agent._podcast_state
        audio_path = state.get( "final_audio_path" )
        script_path = state.get( "script_path" )
        cost = agent.api_client.cost_estimate.estimated_cost_usd if agent._api_client else 0.0

        # Per-language artifact maps from the orchestrator state (bugs 00e6aba1 /
        # 2da4095a): a multi-language run writes one audio+script pair per language.
        # Thread ALL of them through so the job's completion abstract can link every
        # language, not just the primary. Absent (single-language / older state) → None.
        return {
            "audio_path"  : audio_path,
            "script_path" : script_path,
            "cost"        : cost,
            "artifacts"   : {
                "podcast_id"   : agent.podcast_id,
                "title"        : script.title if script else None,
                "segment_count": script.get_segment_count() if script else 0,
                "duration_min" : script.estimated_duration_minutes if script else 0,
                "audio_paths_by_language"  : state.get( "audio_paths_by_language" ),
                "script_paths_by_language" : state.get( "script_paths_by_language" ),
                # Languages whose translation failed; the card names them, since they have no links.
                "failed_translations"      : dict( agent._failed_translations ),
            },
            "cancelled"   : False,
        }


def quick_smoke_test():
    """Quick smoke test for DeepResearchToPodcastAgent."""
    import cosa.utils.util as cu

    cu.print_banner( "DeepResearchToPodcastAgent Smoke Test", prepend_nl=True )

    try:
        # Test 1: Import
        print( "Testing module import..." )
        from cosa.agents.deep_research_to_podcast import DeepResearchToPodcastAgent
        print( "✓ Module imported successfully" )

        # Test 2: Instantiation
        print( "Testing agent instantiation..." )
        agent = DeepResearchToPodcastAgent(
            query      = "test query for smoke test",
            user_email = "test@test.com",
            budget     = 1.00,
            cli_mode   = True,  # Force CLI mode for testing
            debug      = False,
        )
        print( "✓ Agent created successfully" )

        # Test 3: Verify attributes
        print( "Testing agent attributes..." )
        assert agent.query == "test query for smoke test"
        assert agent.user_email == "test@test.com"
        assert agent.budget == 1.00
        assert agent.cli_mode is True
        assert agent.target_languages == [ "en" ]
        print( "✓ Attributes set correctly" )

        # Test 4: Initial state
        print( "Testing initial state..." )
        assert agent.get_state() == PipelineState.INITIALIZED
        assert agent.result.is_success() is False
        print( "✓ Initial state correct" )

        # Test 5: _set_modality (without running full agent)
        print( "Testing _set_modality..." )
        agent._set_modality()
        from cosa.agents.deep_research import voice_io as dr_voice_io
        from cosa.agents.podcast_generator import voice_io as pg_voice_io
        # Both should be in CLI mode
        dr_desc = dr_voice_io.get_mode_description()
        pg_desc = pg_voice_io.get_mode_description()
        assert "forced" in dr_desc.lower()
        assert "forced" in pg_desc.lower()
        # Reset
        dr_voice_io.set_cli_mode( False )
        pg_voice_io.set_cli_mode( False )
        print( "✓ _set_modality works correctly" )

        # Test 6: Async method exists
        print( "Testing async method signatures..." )
        import inspect
        assert inspect.iscoroutinefunction( agent.run_async )
        assert inspect.iscoroutinefunction( agent._run_deep_research )
        assert inspect.iscoroutinefunction( agent._run_podcast_generator )
        assert inspect.iscoroutinefunction( agent._notify )
        print( "✓ All async methods have correct signatures" )

        # Note: We don't test run_async() here as it requires API keys
        print( "\n⚠ Note: run_async() not tested (requires API keys and services)" )

        print( "\n✓ DeepResearchToPodcastAgent smoke test completed successfully" )

    except Exception as e:
        print( f"\n✗ Smoke test failed: {e}" )
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    quick_smoke_test()
