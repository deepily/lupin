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

from .state import ChainedResult, PipelineState


class DeepResearchToPodcastAgent:
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
        # Podcast Generator options
        target_languages: Optional[ List[ str ] ] = None,
        max_segments: Optional[ int ] = None,
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

            # Podcast Generator options
            target_languages: List of ISO language codes (default: ["en"])
            max_segments: Limit TTS to first N segments (cost control)

            # Common options
            cli_mode: Force CLI text mode (default: voice-driven)
            debug: Enable debug output
            verbose: Enable verbose output
        """
        self.query            = query
        self.user_email       = user_email

        # Deep Research options
        self.budget           = budget
        self.lead_model       = lead_model
        self.no_confirm       = no_confirm
        self.audience          = audience
        self.audience_context  = audience_context

        # Podcast Generator options
        self.target_languages = target_languages or [ "en" ]
        self.max_segments     = max_segments

        # Common options
        self.cli_mode         = cli_mode
        self.debug            = debug
        self.verbose          = verbose

        # Result tracking
        self.result           = ChainedResult()
        self._start_time      = None

        if self.debug:
            print( f"[DeepResearchToPodcastAgent] Initialized" )
            print( f"  Query: {query[ :50 ]}..." )
            print( f"  User: {user_email}" )
            print( f"  Mode: {'CLI' if cli_mode else 'Voice-driven'}" )

    def _set_modality( self ) -> None:
        """
        Set voice/CLI mode on BOTH underlying agents.

        Both Deep Research and Podcast Generator have their own voice_io modules.
        We must set cli_mode on both to ensure consistent behavior.
        """
        from cosa.agents.deep_research import voice_io as dr_voice_io
        from cosa.agents.podcast_generator import voice_io as pg_voice_io

        dr_voice_io.set_cli_mode( self.cli_mode )
        pg_voice_io.set_cli_mode( self.cli_mode )

        # Re-establish DR binding as the default for pipeline notifications
        dr_voice_io.reconfigure()

        if self.debug:
            mode = "CLI" if self.cli_mode else "Voice-driven"
            print( f"[DeepResearchToPodcastAgent] Set modality to: {mode}" )

    async def run_async( self ) -> ChainedResult:
        """
        Execute the full chain: Deep Research → Podcast Generation.

        Returns:
            ChainedResult with research_path, audio_path, combined cost

        Raises:
            Exception: If Deep Research fails critically
        """
        self._start_time = time.time()
        self.result.started_at = datetime.now().isoformat()
        self.result.state = PipelineState.INITIALIZED

        # Set modality before running either agent
        self._set_modality()

        try:
            # Step 1: Run Deep Research
            await self._notify( "Starting Deep Research pipeline...", priority="medium" )
            dr_result = await self._run_deep_research()

            if dr_result.get( "cancelled" ):
                self.result.state = PipelineState.CANCELLED
                self.result.error = "Deep Research was cancelled by user"
                return self._finalize_result()

            # Extract report path
            report_path = dr_result.get( "report_path" )
            if not report_path:
                self.result.state = PipelineState.FAILED
                self.result.error = "Deep Research completed but no report_path returned"
                return self._finalize_result()

            # Store DR results
            self.result.research_path = report_path
            self.result.research_abstract = dr_result.get( "abstract" )
            self.result.dr_cost = dr_result.get( "cost", 0.0 )
            self.result.dr_artifacts = dr_result.get( "artifacts", {} )
            self.result.state = PipelineState.DEEP_RESEARCH_DONE

            # Checkpoint: Confirm DR artifacts before PG handoff
            dr_artifacts = self.result.dr_artifacts
            checkpoint_abstract = (
                f"**Research Report**: {report_path}\n\n"
                f"**Abstract**: {self.result.research_abstract[ :200 ] if self.result.research_abstract else 'N/A'}...\n\n"
                f"**Cost**: ${self.result.dr_cost:.4f} | "
                f"**Tokens**: {dr_artifacts.get( 'tokens_used', 'N/A' ):,} | "
                f"**Duration**: {dr_artifacts.get( 'duration_seconds', 0 ):.0f}s"
            )

            await self._notify(
                f"Deep Research complete! Cost: ${self.result.dr_cost:.4f}",
                priority="medium",
                abstract=checkpoint_abstract
            )

            # Step 2: Run Podcast Generator
            await self._notify( "Starting Podcast Generation...", priority="medium" )
            pg_result = await self._run_podcast_generator( report_path )

            if pg_result.get( "cancelled" ):
                self.result.state = PipelineState.CANCELLED
                self.result.error = "Podcast Generation was cancelled by user"
                return self._finalize_result()

            # Store PG results
            self.result.audio_path = pg_result.get( "audio_path" )
            self.result.script_path = pg_result.get( "script_path" )
            self.result.pg_cost = pg_result.get( "cost", 0.0 )
            self.result.pg_artifacts = pg_result.get( "artifacts", {} )
            self.result.state = PipelineState.COMPLETED

            await self._notify(
                f"Pipeline complete! Total cost: ${self.result.total_cost:.4f}",
                priority="medium"
            )

            return self._finalize_result()

        except Exception as e:
            self.result.state = PipelineState.FAILED
            self.result.error = str( e )

            await self._notify(
                f"Pipeline failed: {str( e )[ :100 ]}",
                priority="urgent"
            )

            if self.debug:
                import traceback
                traceback.print_exc()

            return self._finalize_result()

    async def _run_deep_research( self ) -> dict:
        """
        Execute Deep Research and return results.

        Returns:
            dict with keys: report_path, abstract, cost, artifacts, cancelled
        """
        self.result.state = PipelineState.RUNNING_DEEP_RESEARCH

        # Re-establish DR voice_io binding before DR phase
        from cosa.agents.deep_research import voice_io as dr_voice_io
        from cosa.agents.deep_research import cosa_interface as dr_cosa_interface
        dr_voice_io.reconfigure()
        dr_cosa_interface.TARGET_USER = self.user_email

        # Import Deep Research components
        from cosa.agents.deep_research.config import ResearchConfig
        from cosa.agents.deep_research.cost_tracker import CostTracker, BudgetExceededError
        from cosa.agents.deep_research.cli import (
            run_research,
            generate_abstract_for_cli,
            save_report_with_frontmatter,
        )
        from cosa.config.configuration_manager import ConfigurationManager
        from cosa.memory.gister import Gister
        import cosa.utils.util as cu

        # Initialize configuration
        config_mgr = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )

        # Get storage configuration
        storage_backend = config_mgr.get( "deep research storage backend", default="local" )
        gcs_bucket = config_mgr.get( "deep research gcs bucket", default=None )
        output_dir = config_mgr.get( "deep research output directory", default="/io/deep-research" )

        # Build full output path
        if not output_dir.startswith( "/" ):
            output_dir = cu.get_project_root() + "/" + output_dir
        elif not output_dir.startswith( cu.get_project_root() ):
            output_dir = cu.get_project_root() + output_dir

        # Generate session_name from query using Gister
        gister = Gister( debug=self.debug )
        session_name = gister.get_gist(
            self.query,
            prompt_key="prompt template for deep research session name"
        )
        session_name = session_name.lower().strip() if session_name else "general research query"

        # Derive semantic_topic from session_name
        semantic_topic = session_name.replace( " ", "-" )

        if self.debug:
            print( f"[DR] Session name: {session_name}" )
            print( f"[DR] Semantic topic: {semantic_topic}" )
            print( f"[DR] Storage backend: {storage_backend}" )

        # Create research configuration
        config = ResearchConfig(
            lead_model = self.lead_model if self.lead_model else config_mgr.get(
                "deep research lead model",
                default="claude-opus-4-6"
            ),
            subagent_model = config_mgr.get(
                "deep research subagent model",
                default="claude-sonnet-4-6"
            ),
            audience = self.audience or config_mgr.get(
                "deep research audience",
                default="academic"
            ),
            audience_context = self.audience_context or config_mgr.get(
                "deep research audience context",
                default=None
            ) or None,
        )

        # Generate unique session ID for this pipeline (needed by CostTracker)
        import uuid
        session_id = f"chain-{uuid.uuid4().hex[ :8 ]}"

        # Create cost tracker
        cost_tracker = CostTracker( session_id=session_id, budget_limit_usd=self.budget )

        try:
            # Run the research
            report = await run_research(
                query        = self.query,
                config       = config,
                cost_tracker = cost_tracker,
                user_email   = self.user_email,
                no_confirm   = self.no_confirm,
                debug        = self.debug,
                verbose      = self.verbose
            )

            if report is None:
                return { "cancelled": True }

            # Generate abstract
            abstract = await generate_abstract_for_cli(
                report       = report,
                config       = config,
                cost_tracker = cost_tracker,
                debug        = self.debug
            )

            # Save report with frontmatter
            report_path = save_report_with_frontmatter(
                report          = report,
                query           = self.query,
                abstract        = abstract,
                semantic_topic  = semantic_topic,
                session_id      = session_id,
                cost_tracker    = cost_tracker,
                config          = config,
                output_dir      = output_dir,
                user_email      = self.user_email,
                storage_backend = storage_backend,
                gcs_bucket      = gcs_bucket,
                debug           = self.debug
            )

            # Get cost summary
            summary = cost_tracker.get_summary()

            return {
                "report_path" : report_path,
                "abstract"    : abstract,
                "cost"        : summary.total_cost_usd,
                "artifacts"   : {
                    "report"          : report,
                    "session_name"    : session_name,
                    "semantic_topic"  : semantic_topic,
                    "tokens_used"     : summary.total_input_tokens + summary.total_output_tokens,
                    "duration_seconds": summary.duration_seconds,
                },
                "cancelled"   : False,
            }

        except BudgetExceededError as e:
            raise Exception( f"Deep Research budget exceeded: ${e.current_cost:.2f} of ${e.budget_limit:.2f}" )

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

        # Import Podcast Generator components
        from cosa.agents.podcast_generator.orchestrator import PodcastOrchestratorAgent
        from cosa.agents.podcast_generator.config import PodcastConfig
        import cosa.utils.util as cu

        # Validate research document exists
        if not os.path.exists( research_path ):
            raise Exception( f"Research document not found: {research_path}" )

        if self.debug:
            print( f"[PG] Research document: {research_path}" )
            print( f"[PG] Target languages: {self.target_languages}" )
            if self.max_segments:
                print( f"[PG] Max segments: {self.max_segments}" )

        # Create config
        config = PodcastConfig()

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

        return {
            "audio_path"  : audio_path,
            "script_path" : script_path,
            "cost"        : cost,
            "artifacts"   : {
                "podcast_id"   : agent.podcast_id,
                "title"        : script.title if script else None,
                "segment_count": script.get_segment_count() if script else 0,
                "duration_min" : script.estimated_duration_minutes if script else 0,
            },
            "cancelled"   : False,
        }

    def _finalize_result( self ) -> ChainedResult:
        """Finalize and return the result with timing info."""
        self.result.completed_at = datetime.now().isoformat()
        if self._start_time:
            self.result.duration_seconds = time.time() - self._start_time
        self.result.total_cost = self.result.dr_cost + self.result.pg_cost
        return self.result

    async def _notify( self, message: str, priority: str = "medium", **kwargs ) -> None:
        """
        Send a notification using the appropriate modality.

        Uses Deep Research voice_io (which is already configured).
        """
        from cosa.agents.deep_research import voice_io

        await voice_io.notify( message, priority=priority, **kwargs )

    def get_state( self ) -> PipelineState:
        """Get current pipeline state."""
        return self.result.state


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
