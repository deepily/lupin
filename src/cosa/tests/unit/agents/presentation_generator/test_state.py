#!/usr/bin/env python3
"""
Unit tests for cosa.agents.presentation_generator.state

Pure Pydantic models + enums + YAML (de)serialization + create_initial_state.
No external boundaries — fully deterministic.
"""

import pytest

from cosa.agents.presentation_generator.state import (
    OrchestratorState,
    ArcPosition,
    NarrativeSection,
    SlideOutline,
    PresenterNotes,
    SlideModel,
    PresentationModel,
    create_initial_state,
)


class TestEnums:
    def test_orchestrator_state_values( self ):
        assert OrchestratorState.INITIALIZED == "initialized"
        assert OrchestratorState.COMPLETED   == "completed"
        assert OrchestratorState.FAILED      == "failed"
        assert len( OrchestratorState ) == 12

    def test_arc_position_values( self ):
        assert ArcPosition.SETUP == "setup"
        assert ArcPosition.CTA   == "cta"
        assert len( ArcPosition ) == 6


class TestModels:
    def test_narrative_section( self ):
        s = NarrativeSection( heading="H", content="C", arc_position=ArcPosition.SETUP, proposed_slides=2 )
        assert s.arc_position == ArcPosition.SETUP
        assert s.proposed_slides == 2

    def test_narrative_section_default_slides( self ):
        s = NarrativeSection( heading="H", content="C", arc_position=ArcPosition.ARGUMENT )
        assert s.proposed_slides == 1

    def test_slide_outline_full_and_defaults( self ):
        full = SlideOutline( number=3, arc_position="body", type="key_point",
                             title="T", visual_type="diagram", source_hint="Section X" )
        assert full.visual_type == "diagram"
        assert full.source_hint == "Section X"
        minimal = SlideOutline( number=1, arc_position="opening", type="title", title="My Talk" )
        assert minimal.visual_type == "text_only"
        assert minimal.source_hint is None

    def test_presenter_notes_full_and_defaults( self ):
        n = PresenterNotes( transition="t", talking_points=[ "a", "b" ], timing_seconds=75, emphasis="e" )
        assert n.timing_seconds == 75
        assert len( n.talking_points ) == 2
        d = PresenterNotes()
        assert d.transition is None
        assert d.talking_points == []
        assert d.timing_seconds == 60
        assert d.emphasis is None

    def test_slide_model_full_and_defaults( self ):
        notes = PresenterNotes( timing_seconds=30 )
        slide = SlideModel( number=5, arc_position="body", type="key_point", title="T",
                            subtitle="sub", visual_type="diagram", visual_description="d",
                            content_bullets=[ "x" ], presenter_notes=notes )
        assert slide.subtitle == "sub"
        assert slide.presenter_notes.timing_seconds == 30
        minimal = SlideModel( number=1, arc_position="opening", type="title", title="My Talk" )
        assert minimal.visual_type == "text_only"
        assert minimal.visual_description is None
        assert minimal.content_bullets == []
        # default presenter_notes is a fresh PresenterNotes
        assert minimal.presenter_notes.timing_seconds == 60

    def test_presentation_model_defaults( self ):
        pres = PresentationModel( title="P" )
        assert pres.speaker == ""
        assert pres.duration_minutes == 15
        assert pres.total_slides == 0
        assert pres.slides == []
        assert pres.theme == "default"
        assert pres.theme_overrides == {}


class TestYaml:
    def _pres( self ):
        return PresentationModel(
            title            = "Test Talk",
            duration_minutes = 10,
            total_slides     = 1,
            slides           = [ SlideModel(
                number=1, arc_position="opening", type="title", title="Hello World",
                presenter_notes=PresenterNotes( talking_points=[ "Welcome" ], timing_seconds=30 ),
            ) ],
        )

    def test_to_yaml( self ):
        y = self._pres().to_yaml()
        assert "Test Talk" in y
        assert "Hello World" in y
        assert "talking_points" in y

    def test_from_yaml_round_trip( self ):
        y = self._pres().to_yaml()
        restored = PresentationModel.from_yaml( y )
        assert restored.title == "Test Talk"
        assert restored.total_slides == 1
        assert restored.slides[ 0 ].title == "Hello World"
        assert restored.slides[ 0 ].presenter_notes.timing_seconds == 30

    def test_from_yaml_non_dict_raises( self ):
        with pytest.raises( ValueError, match="Expected YAML dict" ):
            PresentationModel.from_yaml( "- just\n- a\n- list" )


class TestCreateInitialState:
    def test_keys_initialized( self ):
        state = create_initial_state( "/path/doc.md", "user123" )
        assert state[ "source_path" ] == "/path/doc.md"
        assert state[ "user_id" ] == "user123"
        assert state[ "revision_count" ] == 0
        assert state[ "outline_revision_count" ] == 0
        assert state[ "elaborate_revision_count" ] == 0
        assert state[ "yaml_path" ] is None
        assert state[ "visuals_rendered" ] == 0
        assert state[ "delivery_summary" ] is None


if __name__ == "__main__":
    pytest.main( [ __file__, "-v" ] )
