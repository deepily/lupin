#!/usr/bin/env python3
"""
Deep Research to Presentation Agent - Wrapper for chained workflow.

Orchestrates a pipeline: Deep Research → Presentation Generation.

This agent:
1. Runs Deep Research to produce a research report
2. Extracts the report path from Deep Research output
3. Passes the report to Presentation Generator as source_path
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


class DeepResearchToPresentationAgent( ChainedDeepResearchAgent ):
    """
    Orchestrates a chained workflow: Deep Research → Presentation Generation.

    Requires:
        - query is a non-empty string (research topic)
        - user_email is a valid email address

    Ensures:
        - Runs Deep Research first
        - Extracts report_path from DR output
        - Passes report_path to Presentation Generator as source_path
        - Returns combined result with both artifacts

    Example:
        agent = DeepResearchToPresentationAgent(
            query      = "State of quantum computing in 2026",
            user_email = "researcher@example.com",
            budget     = 3.00,
            cli_mode   = True,  # Force text mode
        )
        result = await agent.run_async()
        print( f"Research: {result.research_path}" )
        print( f"Presentation: {result.marp_path}" )
    """

    PIPELINE_STATE = PipelineState
    RESULT_CLASS   = ChainedResult
    STAGE_LABEL    = "Presentation Generation"

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
        # Presentation Generator options
        target_duration_minutes: Optional[ int ] = None,
        target_slide_count: Optional[ int ] = None,
        theme: Optional[ str ] = None,
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
                first, as seed context. Already scope-validated and resolved by the
                v2 door; this constructor receives real paths.

            # Presentation Generator options
            target_duration_minutes: Override target duration (None = use default)
            target_slide_count: Explicit slide count overriding the duration formula (None = use default)
            theme: Override theme name (None = use default)

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

        # Presentation Generator options
        self.target_duration_minutes = target_duration_minutes
        self.target_slide_count      = target_slide_count
        self.theme                   = theme
    def _stage_voice_io( self ):
        """Return the presentation generator's voice_io module."""
        from cosa.agents.presentation_generator import voice_io

        return voice_io

    async def _run_second_stage( self, research_path: str ) -> dict:
        """Run the Presentation Generator on the research report."""
        return await self._run_presentation_generator( research_path )

    def _store_second_stage_result( self, pg_result: dict ) -> None:
        """Keep the deck's YAML and Marp paths and its slide count on the result."""
        self.result.yaml_path   = pg_result.get( "yaml_path" )
        self.result.marp_path   = pg_result.get( "marp_path" )
        # Surface the slide count as a top-level field for downstream consumers
        # (R2P job.py copies it onto its own artifacts dict so live tests can
        # assert on it). _run_presentation_generator reports it as "total_slides".
        self.result.slide_count = pg_result.get( "artifacts", {} ).get( "total_slides" )

    async def _run_presentation_generator( self, research_path: str ) -> dict:
        """
        Execute Presentation Generator on the research report.

        Args:
            research_path: Path to the Deep Research report

        Returns:
            dict with keys: yaml_path, marp_path, cost, artifacts, cancelled
        """
        self.result.state = PipelineState.RUNNING_PRESENTATION_GEN

        # Re-establish PG voice_io binding before presentation phase
        from cosa.agents.presentation_generator import voice_io as pg_voice_io
        from cosa.agents.presentation_generator import cosa_interface as pg_cosa_interface
        pg_voice_io.reconfigure()
        pg_cosa_interface.TARGET_USER = self.user_email
        set_dispatch_context( target_user=self.user_email )

        # Import Presentation Generator components
        from cosa.agents.presentation_generator.orchestrator import PresentationOrchestratorAgent
        from cosa.agents.presentation_generator.config import PresentationConfig, apply_job_overrides
        from cosa.config.configuration_manager import ConfigurationManager
        import cosa.utils.util as cu

        # Validate research document exists
        if not os.path.exists( research_path ):
            raise Exception( f"Research document not found: {research_path}" )

        if self.debug:
            print( f"[PG] Research document: {research_path}" )
            if self.target_duration_minutes:
                print( f"[PG] Target duration: {self.target_duration_minutes} min" )
            if self.theme:
                print( f"[PG] Theme: {self.theme}" )

        # Create config from INI
        config_mgr = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )
        config = PresentationConfig.from_config( config_mgr, debug=self.debug )

        # Apply overrides (the same rule the presentation job uses; this chain has no content_model arg)
        apply_job_overrides(
            config,
            target_duration_minutes = self.target_duration_minutes,
            target_slide_count      = self.target_slide_count,
            audience                = self.audience,
            theme                   = self.theme,
            audience_context        = self.audience_context,
        )

        # Create orchestrator
        agent = PresentationOrchestratorAgent(
            source_path  = research_path,
            user_id      = self.user_email,
            config       = config,
            offline_mode = False,
            debug        = self.debug,
            verbose      = self.verbose,
        )

        if self.debug:
            print( f"[PG] Presentation ID: {agent.presentation_id}" )

        # Run the workflow
        presentation = await agent.do_all_async()

        if presentation is None:
            return { "cancelled": True }

        # Get results from orchestrator state
        state     = agent._presentation_state
        yaml_path = state.get( "yaml_path" )
        marp_path = state.get( "marp_path" )
        cost      = agent.api_client.cost_estimate.estimated_cost_usd if agent._api_client else 0.0

        return {
            "yaml_path"   : yaml_path,
            "marp_path"   : marp_path,
            "cost"        : cost,
            "artifacts"   : {
                "presentation_id" : agent.presentation_id,
                "total_slides"    : presentation.total_slides if presentation else 0,
                "theme"           : presentation.theme if presentation else None,
                "delivery_summary": state.get( "delivery_summary" ),
            },
            "cancelled"   : False,
        }


def quick_smoke_test():
    """Quick smoke test for DeepResearchToPresentationAgent."""
    import cosa.utils.util as cu

    cu.print_banner( "DeepResearchToPresentationAgent Smoke Test", prepend_nl=True )

    try:
        # Test 1: Import
        print( "Testing module import..." )
        from cosa.agents.deep_research_to_presentation import DeepResearchToPresentationAgent
        print( "✓ Module imported successfully" )

        # Test 2: Instantiation
        print( "Testing agent instantiation..." )
        agent = DeepResearchToPresentationAgent(
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
        assert agent.target_duration_minutes is None
        assert agent.target_slide_count is None
        assert agent.theme is None
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
        from cosa.agents.presentation_generator import voice_io as pg_voice_io
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
        assert inspect.iscoroutinefunction( agent._run_presentation_generator )
        assert inspect.iscoroutinefunction( agent._notify )
        print( "✓ All async methods have correct signatures" )

        # Note: We don't test run_async() here as it requires API keys
        print( "\n⚠ Note: run_async() not tested (requires API keys and services)" )

        print( "\n✓ DeepResearchToPresentationAgent smoke test completed successfully" )

    except Exception as e:
        print( f"\n✗ Smoke test failed: {e}" )
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    quick_smoke_test()
