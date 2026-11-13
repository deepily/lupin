"""
Unit tests for the partial-run predicate shared by the chained Deep Research results.

Twin refactor slice chained-pipeline-state: the podcast and presentation ChainedResult classes
carried one is_partial each, differing only in the artifact field they tested.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional

import pytest

from cosa.agents.chained_pipeline_state import ChainedResultMixin
from cosa.agents.deep_research_to_podcast.state import ChainedResult as PodcastResult, PipelineState as PodcastState
from cosa.agents.deep_research_to_presentation.state import ChainedResult as PresentationResult, PipelineState as PresentationState


class _State( Enum ):
    HALF = 1
    OTHER = 2


@dataclass
class _Result( ChainedResultMixin ):
    PARTIAL_STATES   = ( _State.HALF, )
    PRIMARY_ARTIFACT = "output"

    state        : _State = _State.HALF
    research_path: Optional[ str ] = "r.md"
    output       : Optional[ str ] = None


class TestMixin:

    def test_true_when_state_listed_research_set_and_artifact_missing( self ):
        assert _Result().is_partial() is True

    @pytest.mark.parametrize( "change", [
        { "state": _State.OTHER },
        { "research_path": None },
        { "output": "out.bin" },
    ] )
    def test_each_condition_alone_turns_it_false( self, change ):
        assert _Result( **change ).is_partial() is False

    def test_the_named_field_is_the_one_tested( self ):
        """A different field set does not stop a partial result."""
        r = _Result()
        r.other_field = "set"
        assert r.is_partial() is True


class TestBothResultClasses:

    @pytest.mark.parametrize( "cls, states, artifact", [
        ( PodcastResult,      PodcastState,      "audio_path" ),
        ( PresentationResult, PresentationState, "yaml_path" ),
    ] )
    def test_partial_states_and_artifact_field( self, cls, states, artifact ):
        assert cls.PARTIAL_STATES   == ( states.DEEP_RESEARCH_DONE, states.FAILED )
        assert cls.PRIMARY_ARTIFACT == artifact
        for state in states:
            expected = state in ( states.DEEP_RESEARCH_DONE, states.FAILED )
            assert cls( state = state, research_path = "r.md" ).is_partial() is expected
        assert cls( state = states.FAILED, research_path = "r.md", **{ artifact: "x" } ).is_partial() is False
        assert cls( state = states.FAILED ).is_partial() is False

    def test_the_podcast_result_ignores_the_presentation_artifact( self ):
        assert PodcastResult( state = PodcastState.FAILED, research_path = "r.md", script_path = "s.md" ).is_partial() is True

    def test_the_presentation_result_ignores_the_podcast_fields( self ):
        assert PresentationResult( state = PresentationState.FAILED, research_path = "r.md", marp_path = "m.md" ).is_partial() is True

    def test_dataclass_fields_are_unchanged_by_the_new_class_attributes( self ):
        import dataclasses
        assert "PARTIAL_STATES" not in { f.name for f in dataclasses.fields( PodcastResult ) }
        assert "PRIMARY_ARTIFACT" not in { f.name for f in dataclasses.fields( PresentationResult ) }


def test_the_shared_init_keeps_every_option_and_starts_an_empty_result_of_its_own_class():
    from cosa.agents.deep_research_to_podcast.agent import DeepResearchToPodcastAgent
    from cosa.agents.deep_research_to_presentation.agent import DeepResearchToPresentationAgent
    for agent_class, result_class in ( ( DeepResearchToPodcastAgent, PodcastResult ), ( DeepResearchToPresentationAgent, PresentationResult ) ):
        bare = agent_class( query="q", user_email="a@x.com" )
        assert bare.source_document == [ ]
        assert type( bare.result ) is result_class
        assert bare._start_time is None
        full = agent_class( "q", "a@x.com", budget=2.5, lead_model="m", no_confirm=True, audience="expert",
                            audience_context="ctx", source_document=[ "/d.md" ], cli_mode=True, debug=False, verbose=True )
        assert ( full.budget, full.lead_model, full.no_confirm, full.audience ) == ( 2.5, "m", True, "expert" )
        assert ( full.audience_context, full.source_document, full.cli_mode, full.verbose ) == ( "ctx", [ "/d.md" ], True, True )


def test_run_async_announces_the_second_stage_by_its_own_label():
    import asyncio
    from unittest.mock import patch, AsyncMock
    from cosa.agents.deep_research_to_podcast.agent import DeepResearchToPodcastAgent
    from cosa.agents.deep_research_to_presentation.agent import DeepResearchToPresentationAgent
    for agent_class, label in ( ( DeepResearchToPodcastAgent, "Podcast Generation" ), ( DeepResearchToPresentationAgent, "Presentation Generation" ) ):
        agent = agent_class( query="q", user_email="a@x.com", cli_mode=True )
        notified = [ ]
        async def _notify( message, priority="medium", **kwargs ): notified.append( message )
        agent._notify = _notify
        with patch.object( agent_class, "_set_modality" ), \
             patch.object( agent_class, "_run_deep_research", AsyncMock( return_value={ "cancelled": True } ) ):
            asyncio.run( agent.run_async() )
        assert notified == [ "Starting Deep Research pipeline..." ]
        agent = agent_class( query="q", user_email="a@x.com", cli_mode=True )
        notified.clear()
        agent._notify = _notify
        dr = { "report_path": "/io/r.md", "abstract": "a", "cost": 0.5, "artifacts": { "tokens_used": 10, "duration_seconds": 1 }, "cancelled": False }
        with patch.object( agent_class, "_set_modality" ), \
             patch.object( agent_class, "_run_deep_research", AsyncMock( return_value=dr ) ), \
             patch.object( agent_class, "_run_second_stage", AsyncMock( return_value={ "cancelled": True } ) ):
            result = asyncio.run( agent.run_async() )
        assert f"Starting {label}..." in notified
        assert result.error == f"{label} was cancelled by user"


# =============================================================================
# The research leg reads its model ids from the INI, with no default in code
# =============================================================================

def _research_leg_patches( seen, cost, gister ):
    from unittest.mock import AsyncMock, patch

    async def _capture( **kw ):
        seen.append( kw[ "config" ] )
        return "# Report"

    return ( patch( "cosa.agents.deep_research.cli.run_research", _capture ),
             patch( "cosa.agents.deep_research.cli.generate_abstract_for_cli", AsyncMock( return_value="abs" ) ),
             patch( "cosa.agents.deep_research.cli.save_report_with_frontmatter", return_value="/io/r.md" ),
             patch( "cosa.agents.deep_research.cost_tracker.CostTracker", cost ),
             patch( "cosa.memory.gister.Gister", gister ) )


def _research_leg_doubles():
    from types import SimpleNamespace
    from unittest.mock import MagicMock
    gister = MagicMock()
    gister.return_value.get_gist.return_value = "a name"
    cost = MagicMock()
    cost.return_value.get_summary.return_value = SimpleNamespace( total_cost_usd=0.5, total_input_tokens=10, total_output_tokens=5, duration_seconds=2.0 )
    return cost, gister


@pytest.mark.asyncio
async def test_the_research_leg_takes_both_model_ids_from_the_ini():
    from contextlib import ExitStack
    from cosa.agents.deep_research_to_podcast.agent import DeepResearchToPodcastAgent
    seen = []
    cost, gister = _research_leg_doubles()
    with ExitStack() as stack:
        for patched in _research_leg_patches( seen, cost, gister ): stack.enter_context( patched )
        await DeepResearchToPodcastAgent( query="q", user_email="u@x.com", no_confirm=True )._run_deep_research()
    assert ( seen[ 0 ].lead_model, seen[ 0 ].subagent_model ) == ( "claude-opus-5", "claude-sonnet-4-6" )


@pytest.mark.asyncio
async def test_the_research_leg_refuses_a_missing_subagent_model_key():
    from contextlib import ExitStack
    from unittest.mock import patch
    from cosa.agents.deep_research_to_podcast.agent import DeepResearchToPodcastAgent
    from cosa.config.configuration_manager import ConfigurationManager, MissingConfigKeyError
    real = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )

    class _NoSubagent:
        """The real manager, except that one model key is absent."""
        def __getattr__( self, name ): return getattr( real, name )
        def get_required( self, key, **kw ):
            if key == "deep research subagent model": raise MissingConfigKeyError( key, "block", "ini" )
            return real.get_required( key, **kw )

    seen = []
    cost, gister = _research_leg_doubles()
    with ExitStack() as stack:
        for patched in _research_leg_patches( seen, cost, gister ): stack.enter_context( patched )
        stack.enter_context( patch( "cosa.config.configuration_manager.ConfigurationManager", lambda **kw: _NoSubagent() ) )
        with pytest.raises( MissingConfigKeyError, match="deep research subagent model" ):
            await DeepResearchToPodcastAgent( query="q", user_email="u@x.com", no_confirm=True )._run_deep_research()
    assert seen == []
