#!/usr/bin/env python3
"""
Unit tests for Presentation Generator Agent — Phases 1-2.

Tests cover:
    - PresentationGeneratorJob construction, class constants, properties
    - PresentationConfig defaults and from_config() loading
    - State models: OrchestratorState, ArcPosition, NarrativeSection,
      PresenterNotes, SlideModel, PresentationModel
    - create_initial_state factory function
    - PresentationOrchestratorAgent construction, state machine, cancellation
"""

import os
import pytest

from cosa.agents.presentation_generator.job import PresentationGeneratorJob
from cosa.agents.presentation_generator.config import PresentationConfig
from cosa.agents.presentation_generator.orchestrator import PresentationOrchestratorAgent
from cosa.agents.presentation_generator.state import (
    OrchestratorState,
    ArcPosition,
    NarrativeSection,
    PresenterNotes,
    SlideModel,
    PresentationModel,
    create_initial_state,
)


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def sample_job():
    """Create a sample PresentationGeneratorJob for testing."""
    return PresentationGeneratorJob(
        source_path             = "/io/deep-research/test@test.com/test-article.md",
        user_id                 = "user123",
        user_email              = "test@test.com",
        session_id              = "wise-penguin",
        target_duration_minutes = 15,
        audience                = "general",
        theme                   = "default",
        dry_run                 = True,
        debug                   = False,
        verbose                 = False
    )


@pytest.fixture
def default_config():
    """Create a default PresentationConfig."""
    return PresentationConfig()


@pytest.fixture
def sample_slide():
    """Create a sample SlideModel."""
    return SlideModel(
        number             = 5,
        arc_position       = "body",
        type               = "key_point",
        title              = "Three-Layer Cache Eliminates Cold Starts",
        visual_type        = "diagram",
        visual_description = "Flowchart: L1->L2->L3",
        content_bullets    = [ "L1: 80% hit rate", "L2: Redis", "L3: S3" ],
        presenter_notes    = PresenterNotes(
            transition     = "So we've seen the problem...",
            talking_points = [ "Explain the three cache layers", "Emphasize L1 hit rate" ],
            timing_seconds = 75,
            emphasis       = "Pause on the 80% L1 hit rate"
        )
    )


# =============================================================================
# Job Tests
# =============================================================================

class TestPresentationGeneratorJob:
    """Tests for PresentationGeneratorJob class."""

    def test_class_constants( self ):
        """JOB_TYPE and JOB_PREFIX are correct."""
        assert PresentationGeneratorJob.JOB_TYPE == "presentation"
        assert PresentationGeneratorJob.JOB_PREFIX == "pr"

    def test_job_construction( self, sample_job ):
        """Job instantiation sets all attributes correctly."""
        assert sample_job.source_path == "/io/deep-research/test@test.com/test-article.md"
        assert sample_job.user_id == "user123"
        assert sample_job.user_email == "test@test.com"
        assert sample_job.session_id == "wise-penguin"
        assert sample_job.target_duration_minutes == 15
        assert sample_job.audience == "general"
        assert sample_job.theme == "default"
        assert sample_job.dry_run is True

    def test_id_hash_prefix( self, sample_job ):
        """Job id_hash starts with 'pr-'."""
        assert sample_job.id_hash.startswith( "pr-" )

    def test_status_initial( self, sample_job ):
        """Job starts in 'pending' status."""
        assert sample_job.status == "pending"

    def test_last_question_asked( self, sample_job ):
        """last_question_asked returns [Presentation] + filename."""
        lqa = sample_job.last_question_asked
        assert "[Presentation]" in lqa
        assert "test-article.md" in lqa

    def test_is_cacheable( self, sample_job ):
        """Presentations are never cacheable."""
        assert sample_job.is_cacheable is False

    def test_results_initially_none( self, sample_job ):
        """Result attributes are None before execution."""
        assert sample_job.yaml_path is None
        assert sample_job.marp_path is None
        assert sample_job.cost_summary is None

    def test_optional_params_default_none( self ):
        """Optional params default to None when not provided."""
        job = PresentationGeneratorJob(
            source_path = "/test.md",
            user_id     = "u1",
            user_email  = "u@t.com",
            session_id  = "s1"
        )
        assert job.target_duration_minutes is None
        assert job.audience is None
        assert job.theme is None
        assert job.dry_run is False


# =============================================================================
# Config Tests
# =============================================================================

class TestPresentationConfig:
    """Tests for PresentationConfig dataclass."""

    def test_defaults( self, default_config ):
        """Default config values are correct."""
        assert default_config.content_model == "claude-opus-4-20250514"
        assert default_config.target_duration_minutes == 15
        assert default_config.slides_per_minute == 1.0
        assert default_config.title_style == "assertion"
        assert default_config.max_revisions == 3
        assert default_config.default_theme == "default"
        assert default_config.audience == "general"

    def test_get_output_path_yaml( self, default_config ):
        """get_output_path generates correct YAML path."""
        path = default_config.get_output_path( "test-user", "Three Layer Caching" )
        assert "presentations/test-user" in path
        assert "three-layer-caching" in path
        assert path.endswith( ".yaml" )

    def test_get_output_path_md( self, default_config ):
        """get_output_path generates correct Marp markdown path."""
        path = default_config.get_output_path( "test-user", "My Topic", file_type="md" )
        assert path.endswith( ".md" )

    def test_get_output_path_sanitizes_topic( self, default_config ):
        """get_output_path sanitizes special characters from topic."""
        path = default_config.get_output_path( "user", "Hello World! @#$%^&*()" )
        basename = os.path.basename( path )
        assert "@" not in basename
        assert "#" not in basename
        assert "!" not in basename

    def test_from_config( self ):
        """from_config loads from ConfigurationManager."""
        from cosa.config.configuration_manager import ConfigurationManager
        config_mgr = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )
        config = PresentationConfig.from_config( config_mgr )
        assert config.content_model == "claude-opus-4-20250514"
        assert config.target_duration_minutes == 15
        assert config.slides_per_minute == 1.0
        assert config.title_style == "assertion"
        assert config.max_revisions == 3
        assert config.audience == "general"


# =============================================================================
# OrchestratorState Tests
# =============================================================================

class TestOrchestratorState:
    """Tests for OrchestratorState enum."""

    def test_all_states_exist( self ):
        """All 12 expected states exist."""
        expected = [
            "initialized", "ingesting", "analyzing", "outlining",
            "elaborating", "serializing", "rendering_text",
            "rendering_visuals", "delivering", "completed", "failed", "cancelled"
        ]
        actual = [ s.value for s in OrchestratorState ]
        assert sorted( actual ) == sorted( expected )

    def test_state_count( self ):
        """Exactly 12 states defined."""
        assert len( OrchestratorState ) == 12

    def test_string_comparison( self ):
        """States compare correctly as strings."""
        assert OrchestratorState.INITIALIZED == "initialized"
        assert OrchestratorState.COMPLETED == "completed"


# =============================================================================
# ArcPosition Tests
# =============================================================================

class TestArcPosition:
    """Tests for ArcPosition enum."""

    def test_all_positions_exist( self ):
        """All 6 arc positions exist."""
        expected = [ "setup", "argument", "evidence", "transition", "conclusion", "cta" ]
        actual = [ p.value for p in ArcPosition ]
        assert sorted( actual ) == sorted( expected )

    def test_position_count( self ):
        """Exactly 6 arc positions defined."""
        assert len( ArcPosition ) == 6


# =============================================================================
# NarrativeSection Tests
# =============================================================================

class TestNarrativeSection:
    """Tests for NarrativeSection Pydantic model."""

    def test_construction( self ):
        """NarrativeSection constructs with all fields."""
        section = NarrativeSection(
            heading      = "Background",
            content      = "Current tools miss 40% of edge cases.",
            arc_position = ArcPosition.SETUP,
            proposed_slides = 2
        )
        assert section.heading == "Background"
        assert section.content == "Current tools miss 40% of edge cases."
        assert section.arc_position == ArcPosition.SETUP
        assert section.proposed_slides == 2

    def test_default_proposed_slides( self ):
        """proposed_slides defaults to 1."""
        section = NarrativeSection(
            heading      = "Test",
            content      = "Content",
            arc_position = ArcPosition.ARGUMENT
        )
        assert section.proposed_slides == 1


# =============================================================================
# PresenterNotes Tests
# =============================================================================

class TestPresenterNotes:
    """Tests for PresenterNotes Pydantic model."""

    def test_defaults( self ):
        """Default PresenterNotes has sensible defaults."""
        notes = PresenterNotes()
        assert notes.transition is None
        assert notes.talking_points == []
        assert notes.timing_seconds == 60
        assert notes.emphasis is None

    def test_full_construction( self ):
        """PresenterNotes constructs with all fields."""
        notes = PresenterNotes(
            transition     = "Moving on...",
            talking_points = [ "Point 1", "Point 2", "Point 3" ],
            timing_seconds = 90,
            emphasis       = "Key takeaway"
        )
        assert notes.transition == "Moving on..."
        assert len( notes.talking_points ) == 3
        assert notes.timing_seconds == 90
        assert notes.emphasis == "Key takeaway"


# =============================================================================
# SlideModel Tests
# =============================================================================

class TestSlideModel:
    """Tests for SlideModel Pydantic model."""

    def test_full_construction( self, sample_slide ):
        """SlideModel constructs with all fields."""
        assert sample_slide.number == 5
        assert sample_slide.arc_position == "body"
        assert sample_slide.type == "key_point"
        assert sample_slide.title == "Three-Layer Cache Eliminates Cold Starts"
        assert sample_slide.visual_type == "diagram"
        assert len( sample_slide.content_bullets ) == 3
        assert sample_slide.presenter_notes.timing_seconds == 75

    def test_minimal_construction( self ):
        """SlideModel constructs with minimum required fields."""
        slide = SlideModel(
            number       = 1,
            arc_position = "opening",
            type         = "title",
            title        = "My Talk"
        )
        assert slide.visual_type == "text_only"
        assert slide.visual_description is None
        assert slide.content_bullets == []
        assert slide.presenter_notes.timing_seconds == 60

    def test_subtitle_optional( self ):
        """subtitle defaults to None."""
        slide = SlideModel( number=1, arc_position="opening", type="title", title="Test" )
        assert slide.subtitle is None


# =============================================================================
# PresentationModel Tests
# =============================================================================

class TestPresentationModel:
    """Tests for PresentationModel Pydantic model."""

    def test_construction_with_slides( self, sample_slide ):
        """PresentationModel constructs with a list of slides."""
        pres = PresentationModel(
            title            = "Test Presentation",
            duration_minutes = 15,
            total_slides     = 1,
            slides           = [ sample_slide ]
        )
        assert pres.title == "Test Presentation"
        assert pres.duration_minutes == 15
        assert len( pres.slides ) == 1
        assert pres.slides[ 0 ].title == "Three-Layer Cache Eliminates Cold Starts"

    def test_defaults( self ):
        """PresentationModel has sensible defaults."""
        pres = PresentationModel( title="Minimal" )
        assert pres.speaker == ""
        assert pres.date == ""
        assert pres.duration_minutes == 15
        assert pres.total_slides == 0
        assert pres.slides == []
        assert pres.theme == "default"
        assert pres.theme_overrides == {}

    def test_theme_overrides( self ):
        """PresentationModel accepts theme_overrides dict."""
        pres = PresentationModel(
            title           = "Branded",
            theme           = "deepily-brand",
            theme_overrides = { "colors": { "primary": "#FF0000" } }
        )
        assert pres.theme == "deepily-brand"
        assert pres.theme_overrides[ "colors" ][ "primary" ] == "#FF0000"


# =============================================================================
# create_initial_state Tests
# =============================================================================

class TestCreateInitialState:
    """Tests for create_initial_state factory function."""

    def test_initial_state( self ):
        """create_initial_state returns correct initial dict."""
        state = create_initial_state( "/path/to/doc.md", "user123" )
        assert state[ "source_path" ] == "/path/to/doc.md"
        assert state[ "user_id" ] == "user123"
        assert state[ "revision_count" ] == 0
        assert state[ "source_content" ] is None
        assert state[ "narrative_sections" ] is None
        assert state[ "slide_outline" ] is None
        assert state[ "elaborated_slides" ] is None
        assert state[ "presentation_model" ] is None
        assert state[ "yaml_path" ] is None
        assert state[ "marp_path" ] is None
        assert state[ "human_feedback" ] is None

    def test_all_keys_present( self ):
        """create_initial_state includes all expected keys."""
        state = create_initial_state( "/test", "u" )
        expected_keys = {
            "source_path", "source_content", "source_format", "raw_sections",
            "word_count", "narrative_sections",
            "slide_outline", "elaborated_slides", "presentation_model",
            "yaml_path", "marp_path", "revision_count", "human_feedback", "user_id"
        }
        assert set( state.keys() ) == expected_keys


# =============================================================================
# PresentationOrchestratorAgent Tests
# =============================================================================

class TestPresentationOrchestratorAgent:
    """Tests for PresentationOrchestratorAgent class."""

    @pytest.fixture
    def agent( self ):
        """Create a sample orchestrator for testing."""
        return PresentationOrchestratorAgent(
            source_path = "/test/doc.md",
            user_id     = "test-user",
            debug       = False
        )

    def test_construction( self, agent ):
        """Orchestrator initializes with correct attributes."""
        assert agent.source_path == "/test/doc.md"
        assert agent.user_id == "test-user"
        assert agent.state == OrchestratorState.INITIALIZED
        assert agent.presentation_id.startswith( "pres-" )

    def test_initial_state( self, agent ):
        """Orchestrator starts in INITIALIZED state."""
        assert agent.state == OrchestratorState.INITIALIZED

    def test_default_config( self, agent ):
        """Orchestrator uses default PresentationConfig when none provided."""
        assert agent.config.target_duration_minutes == 15
        assert agent.config.slides_per_minute == 1.0
        assert agent.config.title_style == "assertion"

    def test_custom_config( self ):
        """Orchestrator accepts custom config."""
        config = PresentationConfig( target_duration_minutes=20, audience="expert" )
        agent = PresentationOrchestratorAgent(
            source_path = "/test.md",
            user_id     = "u1",
            config      = config
        )
        assert agent.config.target_duration_minutes == 20
        assert agent.config.audience == "expert"

    def test_get_state( self, agent ):
        """get_state returns expected dict structure."""
        state = agent.get_state()
        assert state[ "state" ] == "initialized"
        assert state[ "presentation_id" ].startswith( "pres-" )
        assert state[ "source_path" ] == "/test/doc.md"
        assert "metrics" in state
        assert "internal_state" in state

    def test_check_stop_default( self, agent ):
        """_check_stop returns False initially."""
        assert agent._check_stop() is False

    def test_request_stop( self, agent ):
        """request_stop sets the stop flag."""
        agent.request_stop()
        assert agent._check_stop() is True

    def test_presentation_state_initialized( self, agent ):
        """Internal state dict is properly initialized."""
        ps = agent._presentation_state
        assert ps[ "source_path" ] == "/test/doc.md"
        assert ps[ "user_id" ] == "test-user"
        assert ps[ "revision_count" ] == 0
        assert ps[ "source_content" ] is None

    def test_metrics_initialized( self, agent ):
        """Metrics dict starts with None timestamps."""
        assert agent.metrics[ "start_time" ] is None
        assert agent.metrics[ "end_time" ] is None
        assert agent.metrics[ "api_calls" ] == 0


# =============================================================================
# Runtime Argument Expeditor Integration Tests
# =============================================================================

class TestExpeditorIntegration:
    """Tests for Runtime Argument Expeditor integration."""

    def test_user_visible_args_protocol( self ):
        """--user-visible-args returns correct JSON list via CLI."""
        import subprocess
        import sys
        import json

        result = subprocess.run(
            [ sys.executable, "-m", "cosa.agents.presentation_generator", "--user-visible-args" ],
            capture_output = True,
            text           = True,
            timeout        = 10
        )
        assert result.returncode == 0
        args_list = json.loads( result.stdout.strip() )
        assert args_list == [ "source", "target_duration_minutes", "audience", "audience_context", "theme" ]

    def test_registry_entry_exists( self ):
        """Presentation generator is registered in AGENTIC_AGENTS."""
        from cosa.agents.runtime_argument_expeditor.agent_registry import AGENTIC_AGENTS

        entry = AGENTIC_AGENTS.get( "agent router go to presentation generator" )
        assert entry is not None
        assert entry[ "job_prefix" ] == "pr"
        assert entry[ "display_name" ] == "Presentation Generator"

    def test_registry_entry_required_keys( self ):
        """Registry entry has all required keys."""
        from cosa.agents.runtime_argument_expeditor.agent_registry import AGENTIC_AGENTS

        entry = AGENTIC_AGENTS[ "agent router go to presentation generator" ]
        required_keys = {
            "job_prefix", "cli_module", "job_class_path", "display_name",
            "required_user_args", "system_provided", "arg_mapping",
            "fallback_questions", "fallback_defaults"
        }
        assert required_keys.issubset( set( entry.keys() ) )

    def test_registry_required_user_args( self ):
        """Only 'source' is a required user arg."""
        from cosa.agents.runtime_argument_expeditor.agent_registry import AGENTIC_AGENTS

        entry = AGENTIC_AGENTS[ "agent router go to presentation generator" ]
        assert entry[ "required_user_args" ] == [ "source" ]

    def test_registry_special_handlers( self ):
        """Source arg uses fuzzy_file_match handler."""
        from cosa.agents.runtime_argument_expeditor.agent_registry import AGENTIC_AGENTS

        entry = AGENTIC_AGENTS[ "agent router go to presentation generator" ]
        assert "special_handlers" in entry
        assert entry[ "special_handlers" ][ "source" ] == "fuzzy_file_match"

    def test_registry_arg_mapping_aliases( self ):
        """Arg mapping includes common voice aliases for source."""
        from cosa.agents.runtime_argument_expeditor.agent_registry import AGENTIC_AGENTS

        mapping = AGENTIC_AGENTS[ "agent router go to presentation generator" ][ "arg_mapping" ]
        # All these voice aliases should map to "source"
        for alias in [ "source", "source_path", "document", "file", "doc" ]:
            assert mapping[ alias ] == "source", f"Alias '{alias}' should map to 'source'"

    def test_factory_creates_job_from_expeditor_args( self ):
        """Factory creates PresentationGeneratorJob from expeditor-style args_dict."""
        from cosa.rest.agentic_job_factory import create_agentic_job

        job = create_agentic_job(
            command    = "agent router go to presentation generator",
            args_dict  = {
                "source"                  : "/io/deep-research/test@test.com/test.md",
                "target_duration_minutes" : "20",
                "audience"                : "expert",
                "audience_context"        : "ML engineers familiar with transformers",
                "theme"                   : "default",
            },
            user_id    = "user123",
            user_email = "test@test.com",
            session_id = "wise-penguin"
        )
        assert job is not None
        assert isinstance( job, PresentationGeneratorJob )
        assert job.source_path == "/io/deep-research/test@test.com/test.md"
        assert job.target_duration_minutes == 20
        assert job.audience == "expert"
        assert job.audience_context == "ML engineers familiar with transformers"
        assert job.theme == "default"

    def test_factory_handles_semantic_none_values( self ):
        """Factory treats 'default' and 'none' as None for optional int args."""
        from cosa.rest.agentic_job_factory import create_agentic_job

        job = create_agentic_job(
            command    = "agent router go to presentation generator",
            args_dict  = {
                "source"                  : "/test.md",
                "target_duration_minutes" : "default",
                "audience_context"        : "none",
            },
            user_id    = "u1",
            user_email = "u@e.com",
            session_id = "s1"
        )
        assert job is not None
        assert job.target_duration_minutes is None  # "default" → None

    def test_job_accepts_audience_context( self ):
        """PresentationGeneratorJob constructor accepts audience_context."""
        job = PresentationGeneratorJob(
            source_path      = "/test.md",
            user_id          = "u1",
            user_email       = "u@e.com",
            session_id       = "s1",
            audience_context = "Data scientists with Python experience"
        )
        assert job.audience_context == "Data scientists with Python experience"

    def test_job_audience_context_default_none( self ):
        """audience_context defaults to None when not provided."""
        job = PresentationGeneratorJob(
            source_path = "/test.md",
            user_id     = "u1",
            user_email  = "u@e.com",
            session_id  = "s1"
        )
        assert job.audience_context is None


# =============================================================================
# Content Ingestion Tests (Phase 1: Ingest)
# =============================================================================

class TestMarkdownParsing:
    """Tests for _parse_markdown_sections() and related helpers."""

    def test_parse_markdown_with_headings( self ):
        """Markdown with ## headings splits into sections."""
        content = """# Title

Intro paragraph.

## Section One

Content of section one.

## Section Two

Content of section two.

### Sub-Section

Sub-section content.
"""
        sections = PresentationOrchestratorAgent._parse_markdown_sections( content )
        # Should have: Title (H1), Section One (H2), Section Two (H2), Sub-Section (H3)
        assert len( sections ) == 4
        assert sections[ 0 ][ 0 ] == "Title"
        assert sections[ 0 ][ 2 ] == 1  # H1
        assert sections[ 1 ][ 0 ] == "Section One"
        assert sections[ 1 ][ 2 ] == 2  # H2
        assert "Content of section one" in sections[ 1 ][ 1 ]
        assert sections[ 3 ][ 0 ] == "Sub-Section"
        assert sections[ 3 ][ 2 ] == 3  # H3

    def test_parse_markdown_no_headings( self ):
        """Markdown without headings returns single untitled section."""
        content = "Just some plain text without any headings.\n\nAnother paragraph."
        sections = PresentationOrchestratorAgent._parse_markdown_sections( content )
        assert len( sections ) == 1
        assert sections[ 0 ][ 0 ] == "(untitled)"
        assert "plain text" in sections[ 0 ][ 1 ]

    def test_parse_markdown_with_frontmatter( self ):
        """YAML frontmatter at start of file is stripped."""
        content = """---
title: My Document
date: 2026-03-24
---

## Real Content

The actual document content.
"""
        sections = PresentationOrchestratorAgent._parse_markdown_sections( content )
        assert len( sections ) == 1
        assert sections[ 0 ][ 0 ] == "Real Content"
        assert "actual document content" in sections[ 0 ][ 1 ]

    def test_parse_markdown_preamble_before_first_heading( self ):
        """Content before the first heading becomes a preamble section."""
        content = """This is a preamble paragraph.

## First Heading

Heading content.
"""
        sections = PresentationOrchestratorAgent._parse_markdown_sections( content )
        assert len( sections ) == 2
        assert sections[ 0 ][ 0 ] == "(preamble)"
        assert "preamble paragraph" in sections[ 0 ][ 1 ]
        assert sections[ 1 ][ 0 ] == "First Heading"

    def test_parse_markdown_empty_sections( self ):
        """Empty body between headings produces empty string."""
        content = """## Heading A

## Heading B

Content B.
"""
        sections = PresentationOrchestratorAgent._parse_markdown_sections( content )
        assert len( sections ) == 2
        assert sections[ 0 ][ 0 ] == "Heading A"
        assert sections[ 0 ][ 1 ] == ""  # Empty body
        assert sections[ 1 ][ 0 ] == "Heading B"
        assert "Content B" in sections[ 1 ][ 1 ]


class TestPlaintextParsing:
    """Tests for _parse_plaintext_sections()."""

    def test_parse_plaintext_paragraphs( self ):
        """Plain text splits into sections by double newlines."""
        content = "First paragraph.\n\nSecond paragraph.\n\nThird paragraph."
        sections = PresentationOrchestratorAgent._parse_plaintext_sections( content )
        assert len( sections ) == 3
        assert sections[ 0 ][ 0 ] == "Section 1"
        assert sections[ 0 ][ 1 ] == "First paragraph."
        assert sections[ 2 ][ 0 ] == "Section 3"

    def test_parse_plaintext_single_block( self ):
        """Single block without double newlines returns one section."""
        content = "Just one continuous block of text."
        sections = PresentationOrchestratorAgent._parse_plaintext_sections( content )
        assert len( sections ) == 1

    def test_parse_plaintext_empty( self ):
        """Empty content returns single empty section."""
        sections = PresentationOrchestratorAgent._parse_plaintext_sections( "" )
        assert len( sections ) == 1
        assert sections[ 0 ][ 0 ] == "(empty)"


class TestFormatDetection:
    """Tests for _detect_format()."""

    def test_detects_markdown( self ):
        """Content with multiple markdown indicators detected as markdown."""
        content = "# Title\n\nSome text with **bold** and a [link](http://example.com).\n\n- Bullet item"
        assert PresentationOrchestratorAgent._detect_format( content ) == "markdown"

    def test_detects_plaintext( self ):
        """Content without markdown indicators detected as plaintext."""
        content = "This is just a normal paragraph.\n\nAnother paragraph without special formatting."
        assert PresentationOrchestratorAgent._detect_format( content ) == "plaintext"

    def test_single_indicator_not_enough( self ):
        """Single markdown indicator alone isn't enough (need >= 2)."""
        content = "# Just a heading\n\nBut nothing else special about this text."
        assert PresentationOrchestratorAgent._detect_format( content ) == "plaintext"
