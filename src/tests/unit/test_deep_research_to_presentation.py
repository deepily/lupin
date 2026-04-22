"""
Unit tests for Deep Research to Presentation chained pipeline.

Tests state models, job construction, factory routing, and registry entry.
"""

import pytest
from unittest.mock import patch, MagicMock

from cosa.rest.job_state import JobState


# =============================================================================
# PipelineState Tests
# =============================================================================

class TestPipelineState:
    """Tests for PipelineState enum."""

    def test_state_enum_values( self ):
        """All states have expected string values."""
        from cosa.agents.deep_research_to_presentation.state import PipelineState

        assert PipelineState.INITIALIZED.value              == "initialized"
        assert PipelineState.RUNNING_DEEP_RESEARCH.value    == "running_deep_research"
        assert PipelineState.DEEP_RESEARCH_DONE.value       == "deep_research_done"
        assert PipelineState.RUNNING_PRESENTATION_GEN.value == "running_presentation_gen"
        assert PipelineState.PRESENTATION_GEN_DONE.value    == "presentation_gen_done"
        assert PipelineState.COMPLETED.value                == "completed"
        assert PipelineState.FAILED.value                   == "failed"
        assert PipelineState.CANCELLED.value                == "cancelled"

    def test_state_initial_value( self ):
        """INITIALIZED is the default starting state."""
        from cosa.agents.deep_research_to_presentation.state import PipelineState, ChainedResult

        result = ChainedResult()
        assert result.state == PipelineState.INITIALIZED

    def test_state_count( self ):
        """There are exactly 8 pipeline states."""
        from cosa.agents.deep_research_to_presentation.state import PipelineState

        assert len( PipelineState ) == 8


# =============================================================================
# ChainedResult Tests
# =============================================================================

class TestChainedResult:
    """Tests for ChainedResult dataclass."""

    def test_default_construction( self ):
        """All fields have expected defaults."""
        from cosa.agents.deep_research_to_presentation.state import ChainedResult, PipelineState

        result = ChainedResult()
        assert result.research_path     is None
        assert result.research_abstract is None
        assert result.yaml_path         is None
        assert result.marp_path         is None
        assert result.total_cost        == 0.0
        assert result.dr_cost           == 0.0
        assert result.pg_cost           == 0.0
        assert result.duration_seconds  == 0.0
        assert result.started_at        is None
        assert result.completed_at      is None
        assert result.state             == PipelineState.INITIALIZED
        assert result.error             is None
        assert result.dr_artifacts      == {}
        assert result.pg_artifacts      == {}

    def test_success_detection( self ):
        """is_success() for COMPLETED state with no error."""
        from cosa.agents.deep_research_to_presentation.state import ChainedResult, PipelineState

        result = ChainedResult(
            state         = PipelineState.COMPLETED,
            research_path = "/report.md",
            yaml_path     = "/presentation.yaml",
            marp_path     = "/presentation.md",
        )
        assert result.is_success() is True
        assert result.is_partial() is False

    def test_success_false_with_error( self ):
        """is_success() returns False when error is set even if COMPLETED."""
        from cosa.agents.deep_research_to_presentation.state import ChainedResult, PipelineState

        result = ChainedResult(
            state = PipelineState.COMPLETED,
            error = "Something went wrong",
        )
        assert result.is_success() is False

    def test_partial_detection( self ):
        """is_partial() for DR done, PG failed."""
        from cosa.agents.deep_research_to_presentation.state import ChainedResult, PipelineState

        result = ChainedResult(
            research_path = "/report.md",
            state         = PipelineState.DEEP_RESEARCH_DONE,
            error         = "Presentation generation failed",
        )
        assert result.is_partial() is True
        assert result.is_success() is False

    def test_partial_with_failed_state( self ):
        """is_partial() also detects FAILED state with research but no YAML."""
        from cosa.agents.deep_research_to_presentation.state import ChainedResult, PipelineState

        result = ChainedResult(
            research_path = "/report.md",
            state         = PipelineState.FAILED,
            error         = "PG crashed",
        )
        assert result.is_partial() is True

    def test_failed_detection( self ):
        """Neither success nor partial when no research_path."""
        from cosa.agents.deep_research_to_presentation.state import ChainedResult, PipelineState

        result = ChainedResult(
            state = PipelineState.FAILED,
            error = "API key not found",
        )
        assert result.is_success() is False
        assert result.is_partial() is False

    def test_summary_success( self ):
        """get_summary() for complete pipeline."""
        from cosa.agents.deep_research_to_presentation.state import ChainedResult, PipelineState

        result = ChainedResult(
            research_path    = "/io/report.md",
            yaml_path        = "/io/presentation.yaml",
            marp_path        = "/io/presentation.md",
            total_cost       = 2.50,
            dr_cost          = 1.75,
            pg_cost          = 0.75,
            duration_seconds = 180.5,
            state            = PipelineState.COMPLETED,
        )
        summary = result.get_summary()
        assert "completed successfully" in summary
        assert "report.md" in summary
        assert "presentation.yaml" in summary
        assert "presentation.md" in summary
        assert "$2.5000" in summary

    def test_summary_partial( self ):
        """get_summary() mentions partial when DR done, PG failed."""
        from cosa.agents.deep_research_to_presentation.state import ChainedResult, PipelineState

        result = ChainedResult(
            research_path = "/report.md",
            state         = PipelineState.DEEP_RESEARCH_DONE,
            error         = "PG error",
            dr_cost       = 1.00,
        )
        summary = result.get_summary()
        assert "partially completed" in summary
        assert "PG error" in summary

    def test_summary_failed( self ):
        """get_summary() mentions error on failure."""
        from cosa.agents.deep_research_to_presentation.state import ChainedResult, PipelineState

        result = ChainedResult(
            state = PipelineState.FAILED,
            error = "API key not found",
        )
        summary = result.get_summary()
        assert "failed" in summary.lower()
        assert "API key" in summary


# =============================================================================
# Job Construction Tests
# =============================================================================

class TestJobConstruction:
    """Tests for DeepResearchToPresentationJob construction."""

    def test_job_type_and_prefix( self ):
        """JOB_TYPE and JOB_PREFIX are correct."""
        from cosa.agents.deep_research_to_presentation.job import DeepResearchToPresentationJob

        assert DeepResearchToPresentationJob.JOB_TYPE   == "research_to_presentation"
        assert DeepResearchToPresentationJob.JOB_PREFIX  == "rx"

    def test_job_id_format( self ):
        """Job ID starts with rx-."""
        from cosa.agents.deep_research_to_presentation.job import DeepResearchToPresentationJob

        job = DeepResearchToPresentationJob(
            query      = "test query",
            user_id    = "user123",
            user_email = "test@test.com",
            session_id = "session456",
        )
        assert job.id_hash.startswith( "rx-" )

    def test_job_construction_defaults( self ):
        """Default values are correct."""
        from cosa.agents.deep_research_to_presentation.job import DeepResearchToPresentationJob

        job = DeepResearchToPresentationJob(
            query      = "test query",
            user_id    = "user123",
            user_email = "test@test.com",
            session_id = "session456",
        )
        assert job.query                   == "test query"
        assert job.user_email              == "test@test.com"
        assert job.budget                  is None
        assert job.target_duration_minutes is None
        assert job.theme                   is None
        assert job.dry_run                 is False
        assert job.audience                is None
        assert job.audience_context        is None
        assert job.state                   == JobState.PENDING
        assert job.research_path           is None
        assert job.yaml_path               is None
        assert job.marp_path               is None
        assert job.cost_summary            is None

    def test_job_construction_with_args( self ):
        """All args stored correctly."""
        from cosa.agents.deep_research_to_presentation.job import DeepResearchToPresentationJob

        job = DeepResearchToPresentationJob(
            query                   = "quantum computing",
            user_id                 = "user123",
            user_email              = "test@test.com",
            session_id              = "session456",
            budget                  = 5.00,
            target_duration_minutes = 20,
            theme                   = "dark",
            dry_run                 = True,
            audience                = "expert",
            audience_context        = "AI researchers",
        )
        assert job.query                   == "quantum computing"
        assert job.budget                  == 5.00
        assert job.target_duration_minutes == 20
        assert job.theme                   == "dark"
        assert job.dry_run                 is True
        assert job.audience                == "expert"
        assert job.audience_context        == "AI researchers"

    def test_last_question_asked_format( self ):
        """Display string has correct format."""
        from cosa.agents.deep_research_to_presentation.job import DeepResearchToPresentationJob

        job = DeepResearchToPresentationJob(
            query      = "quantum computing trends",
            user_id    = "user123",
            user_email = "test@test.com",
            session_id = "session456",
        )
        lqa = job.last_question_asked
        assert "[Research→Presentation]" in lqa
        assert "quantum computing trends" in lqa

    def test_is_cacheable( self ):
        """Chained jobs are not cacheable."""
        from cosa.agents.deep_research_to_presentation.job import DeepResearchToPresentationJob

        job = DeepResearchToPresentationJob(
            query      = "test",
            user_id    = "user123",
            user_email = "test@test.com",
            session_id = "session456",
        )
        assert job.is_cacheable is False


# =============================================================================
# Factory Routing Tests
# =============================================================================

class TestFactoryRouting:
    """Tests for factory creation of chained jobs."""

    def test_factory_creates_job( self ):
        """Factory returns DeepResearchToPresentationJob for correct command."""
        from cosa.rest.agentic_job_factory import create_agentic_job
        from cosa.agents.deep_research_to_presentation.job import DeepResearchToPresentationJob

        job = create_agentic_job(
            command    = "agent router go to research to presentation",
            args_dict  = { "query": "test topic" },
            user_id    = "user123",
            user_email = "test@test.com",
            session_id = "session456",
        )
        assert isinstance( job, DeepResearchToPresentationJob )

    def test_factory_passes_args( self ):
        """All args forwarded correctly through factory."""
        from cosa.rest.agentic_job_factory import create_agentic_job

        job = create_agentic_job(
            command    = "agent router go to research to presentation",
            args_dict  = {
                "query"                   : "quantum computing",
                "budget"                  : "5.00",
                "target_duration_minutes" : "20",
                "theme"                   : "dark",
                "dry_run"                 : "true",
                "audience"                : "expert",
                "audience_context"        : "AI researchers",
            },
            user_id    = "user123",
            user_email = "test@test.com",
            session_id = "session456",
        )
        assert job.query                   == "quantum computing"
        assert job.budget                  == 5.00
        assert job.target_duration_minutes == 20
        assert job.theme                   == "dark"
        assert job.dry_run                 is True
        assert job.audience                == "expert"
        assert job.audience_context        == "AI researchers"

    def test_factory_handles_defaults( self ):
        """Factory handles None/missing args gracefully."""
        from cosa.rest.agentic_job_factory import create_agentic_job

        job = create_agentic_job(
            command    = "agent router go to research to presentation",
            args_dict  = { "query": "test" },
            user_id    = "user123",
            user_email = "test@test.com",
            session_id = "session456",
        )
        assert job.budget                  is None
        assert job.target_duration_minutes is None
        assert job.theme                   is None
        assert job.dry_run                 is False


# =============================================================================
# Registry Entry Tests
# =============================================================================

class TestRegistryEntry:
    """Tests for agent registry entry."""

    def test_registry_entry_exists( self ):
        """Entry exists in AGENTIC_AGENTS."""
        from cosa.agents.runtime_argument_expeditor.agent_registry import AGENTIC_AGENTS

        assert "agent router go to research to presentation" in AGENTIC_AGENTS

    def test_registry_required_keys( self ):
        """Entry has all required keys."""
        from cosa.agents.runtime_argument_expeditor.agent_registry import AGENTIC_AGENTS

        entry = AGENTIC_AGENTS[ "agent router go to research to presentation" ]
        assert entry[ "job_prefix" ]         == "rx"
        assert entry[ "display_name" ]       == "Research to Presentation"
        assert entry[ "required_user_args" ] == [ "query" ]
        assert "arg_mapping" in entry
        assert "fallback_questions" in entry
        assert "fallback_defaults" in entry

    def test_registry_arg_mapping( self ):
        """Arg mapping covers expected aliases."""
        from cosa.agents.runtime_argument_expeditor.agent_registry import AGENTIC_AGENTS

        mapping = AGENTIC_AGENTS[ "agent router go to research to presentation" ][ "arg_mapping" ]
        assert mapping[ "topic" ]    == "query"
        assert mapping[ "query" ]    == "query"
        assert mapping[ "question" ] == "query"
        assert mapping[ "budget" ]   == "budget"
        assert mapping[ "duration" ] == "target_duration_minutes"
        assert mapping[ "theme" ]    == "theme"

    def test_registry_agent_count( self ):
        """Total agent count is 10 after TFE Resume agent was added."""
        from cosa.agents.runtime_argument_expeditor.agent_registry import AGENTIC_AGENTS

        assert len( AGENTIC_AGENTS ) == 10

    def test_registry_no_special_handlers( self ):
        """Chained job has no special_handlers (query-driven, not file-driven)."""
        from cosa.agents.runtime_argument_expeditor.agent_registry import AGENTIC_AGENTS

        entry = AGENTIC_AGENTS[ "agent router go to research to presentation" ]
        # No special_handlers key, or empty if present
        handlers = entry.get( "special_handlers", {} )
        assert handlers == {}


# =============================================================================
# Agent Construction Tests
# =============================================================================

class TestAgentConstruction:
    """Tests for DeepResearchToPresentationAgent construction."""

    def test_agent_creation( self ):
        """Agent instantiates with correct attributes."""
        from cosa.agents.deep_research_to_presentation.agent import DeepResearchToPresentationAgent

        agent = DeepResearchToPresentationAgent(
            query      = "test topic",
            user_email = "test@test.com",
            budget     = 3.00,
            cli_mode   = True,
        )
        assert agent.query      == "test topic"
        assert agent.user_email == "test@test.com"
        assert agent.budget     == 3.00
        assert agent.cli_mode   is True

    def test_agent_defaults( self ):
        """Agent defaults are correct."""
        from cosa.agents.deep_research_to_presentation.agent import DeepResearchToPresentationAgent

        agent = DeepResearchToPresentationAgent(
            query      = "test",
            user_email = "test@test.com",
        )
        assert agent.budget                  is None
        assert agent.lead_model              is None
        assert agent.no_confirm              is False
        assert agent.audience                is None
        assert agent.audience_context        is None
        assert agent.target_duration_minutes is None
        assert agent.theme                   is None
        assert agent.cli_mode                is False
        assert agent.debug                   is False
        assert agent.verbose                 is False

    def test_agent_initial_state( self ):
        """Agent starts in INITIALIZED state."""
        from cosa.agents.deep_research_to_presentation.agent import DeepResearchToPresentationAgent
        from cosa.agents.deep_research_to_presentation.state import PipelineState

        agent = DeepResearchToPresentationAgent(
            query      = "test",
            user_email = "test@test.com",
        )
        assert agent.get_state() == PipelineState.INITIALIZED
        assert agent.result.is_success() is False

    def test_agent_async_methods( self ):
        """All expected async methods are coroutines."""
        import inspect
        from cosa.agents.deep_research_to_presentation.agent import DeepResearchToPresentationAgent

        agent = DeepResearchToPresentationAgent(
            query      = "test",
            user_email = "test@test.com",
        )
        assert inspect.iscoroutinefunction( agent.run_async )
        assert inspect.iscoroutinefunction( agent._run_deep_research )
        assert inspect.iscoroutinefunction( agent._run_presentation_generator )
        assert inspect.iscoroutinefunction( agent._notify )


# =============================================================================
# Package Import Tests
# =============================================================================

class TestPackageImports:
    """Tests for package-level imports."""

    def test_package_exports( self ):
        """Package exports the expected symbols."""
        from cosa.agents.deep_research_to_presentation import (
            DeepResearchToPresentationAgent,
            ChainedResult,
            PipelineState,
        )
        assert DeepResearchToPresentationAgent is not None
        assert ChainedResult is not None
        assert PipelineState is not None

    def test_package_version( self ):
        """Package has a version string."""
        import cosa.agents.deep_research_to_presentation as pkg
        assert hasattr( pkg, "__version__" )
        assert pkg.__version__ == "0.1.0"
