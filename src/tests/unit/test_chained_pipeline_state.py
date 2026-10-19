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
