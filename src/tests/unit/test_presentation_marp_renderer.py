#!/usr/bin/env python3
"""
Unit tests for MarpTextRenderer — Phase 6 Marp Text Rendering.

Tests cover:
    - Marp frontmatter generation (theme, paginate, header, footer, CSS)
    - Slide type rendering (title, content, section_divider, conclusion)
    - Presenter notes formatting (HTML comment blocks, field omission)
    - Visual placeholders for Phase 7
    - Full render pipeline (slide count, separator count, structure)
    - Theme loading (file-based + fallback defaults)
    - Edge cases (empty presentation, None fields, unknown slide types)
"""

import os
import pytest
import tempfile

from cosa.agents.presentation_generator.renderers.marp_text_renderer import (
    MarpTextRenderer,
    DEFAULT_THEME_CONFIG,
)
from cosa.agents.presentation_generator.state import (
    PresentationModel,
    SlideModel,
    PresenterNotes,
)


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def default_theme():
    """Default theme config dict."""
    return DEFAULT_THEME_CONFIG


@pytest.fixture
def sample_presentation():
    """Full PresentationModel with diverse slide types."""
    return PresentationModel(
        title            = "Three-Layer Caching at Scale",
        speaker          = "Jane Doe",
        date             = "2026-03-28",
        duration_minutes = 15,
        source_document  = "caching-article.md",
        total_slides     = 5,
        slides           = [
            SlideModel(
                number       = 1,
                arc_position = "opening",
                type         = "title",
                title        = "Three-Layer Caching at Scale",
                subtitle     = "How We Achieved 3x Latency Improvement",
                presenter_notes = PresenterNotes(
                    talking_points = [ "Welcome and introduce yourself" ],
                    timing_seconds = 30,
                ),
            ),
            SlideModel(
                number             = 2,
                arc_position       = "body",
                type               = "content",
                title              = "The Problem: Cold Start Latency",
                content_bullets    = [
                    "Cache misses cause 2s+ response times",
                    "Users abandon after 3s of waiting",
                ],
                presenter_notes    = PresenterNotes(
                    transition     = "Let's start with the problem we faced.",
                    talking_points = [ "Describe the latency issue" ],
                    timing_seconds = 60,
                ),
            ),
            SlideModel(
                number       = 3,
                arc_position = "body",
                type         = "section_divider",
                title        = "Our Solution",
                presenter_notes = PresenterNotes(
                    transition     = "Now for the solution.",
                    timing_seconds = 15,
                ),
            ),
            SlideModel(
                number             = 4,
                arc_position       = "body",
                type               = "key_point",
                title              = "Three-Layer Cache Eliminates Cold Starts",
                visual_type        = "diagram",
                visual_description = "Flowchart: L1 -> L2 -> L3 with hit rates",
                content_bullets    = [
                    "L1: In-process cache -- 80% hit rate",
                    "L2: Redis cluster -- 15% hit rate",
                    "L3: S3 with CloudFront -- 5% hit rate",
                ],
                presenter_notes    = PresenterNotes(
                    transition     = "Here's what we built.",
                    talking_points = [
                        "Walk through the three layers",
                        "Emphasize the 80% L1 hit rate",
                    ],
                    timing_seconds = 75,
                    emphasis       = "The 80% L1 hit rate — pause here",
                ),
            ),
            SlideModel(
                number          = 5,
                arc_position    = "closing",
                type            = "conclusion",
                title           = "Key Takeaways",
                content_bullets = [
                    "Three-layer caching eliminates cold starts",
                    "L1 is the biggest win (80% hit rate)",
                    "Zero code changes for adopters",
                ],
                presenter_notes = PresenterNotes(
                    transition     = "Let me wrap up.",
                    talking_points = [ "Recap the three main points" ],
                    timing_seconds = 45,
                ),
            ),
        ],
    )


@pytest.fixture
def title_slide():
    """A single title slide."""
    return SlideModel(
        number       = 1,
        arc_position = "opening",
        type         = "title",
        title        = "Test Title",
        subtitle     = "Test Subtitle",
        presenter_notes = PresenterNotes(
            talking_points = [ "Intro point" ],
            timing_seconds = 30,
        ),
    )


@pytest.fixture
def content_slide():
    """A single content slide with all fields."""
    return SlideModel(
        number          = 2,
        arc_position    = "body",
        type            = "content",
        title           = "Content Title",
        subtitle        = "Content Subtitle",
        content_bullets = [ "Bullet one", "Bullet two", "Bullet three" ],
        presenter_notes = PresenterNotes(
            transition     = "Moving on to the next point.",
            talking_points = [ "Explain bullet one", "Deep dive on bullet two" ],
            timing_seconds = 60,
            emphasis       = "Bullet two is the key insight",
        ),
    )


@pytest.fixture
def minimal_presentation():
    """Presentation with minimal fields — no speaker, no date."""
    return PresentationModel(
        title        = "Minimal Deck",
        total_slides = 1,
        slides       = [
            SlideModel(
                number       = 1,
                arc_position = "opening",
                type         = "title",
                title        = "Minimal Deck",
            ),
        ],
    )


# =============================================================================
# TestMarpFrontmatter
# =============================================================================

class TestMarpFrontmatter:
    """Tests for Marp YAML frontmatter generation."""

    def test_frontmatter_contains_marp_true( self, sample_presentation, default_theme ):
        output = MarpTextRenderer.render( sample_presentation, default_theme )
        assert "marp: true" in output

    def test_frontmatter_theme_directive( self, sample_presentation, default_theme ):
        output = MarpTextRenderer.render( sample_presentation, default_theme )
        assert "theme: default" in output

    def test_frontmatter_paginate_directive( self, sample_presentation, default_theme ):
        output = MarpTextRenderer.render( sample_presentation, default_theme )
        assert "paginate: true" in output

    def test_frontmatter_footer_interpolation( self, sample_presentation, default_theme ):
        output = MarpTextRenderer.render( sample_presentation, default_theme )
        assert 'footer: "Jane Doe | 2026-03-28"' in output

    def test_frontmatter_empty_class_omitted( self, sample_presentation, default_theme ):
        """Empty marp_class should not produce a class: line."""
        output = MarpTextRenderer.render( sample_presentation, default_theme )
        lines  = output.split( "\n" )
        # Find lines between the frontmatter --- delimiters
        class_lines = [ l for l in lines if l.startswith( "class:" ) ]
        assert len( class_lines ) == 0

    def test_frontmatter_nonempty_class_included( self, sample_presentation ):
        """Non-empty marp_class should produce a class: line."""
        theme = DEFAULT_THEME_CONFIG.copy()
        theme[ "theme" ] = dict( theme[ "theme" ] )
        theme[ "theme" ][ "marp_class" ] = "invert"
        output = MarpTextRenderer.render( sample_presentation, theme )
        assert "class: invert" in output

    def test_frontmatter_css_present( self, sample_presentation, default_theme ):
        output = MarpTextRenderer.render( sample_presentation, default_theme )
        assert "style: |" in output
        assert "font-family: Inter" in output
        assert "color: #2563EB" in output

    def test_frontmatter_empty_header_omitted( self, sample_presentation, default_theme ):
        """Empty header_template should not produce a header: line."""
        output = MarpTextRenderer.render( sample_presentation, default_theme )
        lines  = output.split( "\n" )
        header_lines = [ l for l in lines if l.strip().startswith( "header:" ) ]
        assert len( header_lines ) == 0


# =============================================================================
# TestSlideRendering
# =============================================================================

class TestSlideRendering:
    """Tests for individual slide type rendering."""

    def test_title_slide_structure( self, sample_presentation, default_theme ):
        output = MarpTextRenderer.render( sample_presentation, default_theme )
        assert "# Three-Layer Caching at Scale" in output
        assert "## How We Achieved 3x Latency Improvement" in output
        assert "Jane Doe | 2026-03-28" in output

    def test_title_slide_lead_class( self, sample_presentation, default_theme ):
        output = MarpTextRenderer.render( sample_presentation, default_theme )
        assert "<!-- _class: lead -->" in output

    def test_title_slide_skip_pagination( self, sample_presentation, default_theme ):
        output = MarpTextRenderer.render( sample_presentation, default_theme )
        assert "<!-- _paginate: skip -->" in output

    def test_title_slide_no_subtitle( self, default_theme ):
        """Title slide with None subtitle should not render ## line."""
        pres = PresentationModel(
            title        = "No Sub",
            total_slides = 1,
            slides       = [ SlideModel(
                number       = 1,
                arc_position = "opening",
                type         = "title",
                title        = "No Sub",
                subtitle     = None,
            ) ],
        )
        output = MarpTextRenderer.render( pres, default_theme )
        assert "##" not in output

    def test_title_slide_no_speaker_no_date( self, default_theme ):
        """Title slide without speaker/date omits the speaker line."""
        pres = PresentationModel(
            title        = "Anonymous Deck",
            total_slides = 1,
            slides       = [ SlideModel(
                number       = 1,
                arc_position = "opening",
                type         = "title",
                title        = "Anonymous Deck",
            ) ],
        )
        output = MarpTextRenderer.render( pres, default_theme )
        # No " | " speaker/date line after title
        lines = output.split( "\n" )
        title_idx = next( i for i, l in enumerate( lines ) if l == "# Anonymous Deck" )
        # Next non-empty line after title should not be a speaker line
        remaining = [ l for l in lines[ title_idx + 1: ] if l.strip() and not l.startswith( "#" ) and not l.startswith( "<!--" ) ]
        for line in remaining:
            assert " | " not in line or "footer" in line.lower()

    def test_content_slide_bullets( self, sample_presentation, default_theme ):
        output = MarpTextRenderer.render( sample_presentation, default_theme )
        assert "- Cache misses cause 2s+ response times" in output
        assert "- Users abandon after 3s of waiting" in output

    def test_content_slide_with_subtitle( self, content_slide, default_theme ):
        pres = PresentationModel(
            title        = "Test",
            total_slides = 1,
            slides       = [ content_slide ],
        )
        output = MarpTextRenderer.render( pres, default_theme )
        assert "## Content Subtitle" in output

    def test_section_divider_centered( self, sample_presentation, default_theme ):
        """Section divider should have lead class and centered title."""
        output = MarpTextRenderer.render( sample_presentation, default_theme )
        # The section divider slide "Our Solution" should have lead class nearby
        lines  = output.split( "\n" )
        found  = False
        for i, line in enumerate( lines ):
            if line == "# Our Solution":
                # Check preceding lines for lead class
                preceding = "\n".join( lines[ max( 0, i - 5 ) : i ] )
                assert "<!-- _class: lead -->" in preceding
                found = True
                break
        assert found, "Section divider slide 'Our Solution' not found"

    def test_conclusion_slide_bullets( self, sample_presentation, default_theme ):
        output = MarpTextRenderer.render( sample_presentation, default_theme )
        assert "- Three-layer caching eliminates cold starts" in output
        assert "- Zero code changes for adopters" in output

    def test_unknown_type_fallback( self, default_theme ):
        """Unknown slide type should render as content-style."""
        pres = PresentationModel(
            title        = "Test",
            total_slides = 1,
            slides       = [ SlideModel(
                number          = 1,
                arc_position    = "body",
                type            = "totally_unknown_type",
                title           = "Unknown Slide",
                content_bullets = [ "This should still render" ],
            ) ],
        )
        output = MarpTextRenderer.render( pres, default_theme )
        assert "# Unknown Slide" in output
        assert "- This should still render" in output

    def test_empty_bullets_no_list( self, default_theme ):
        """Slide with empty content_bullets should render title only."""
        pres = PresentationModel(
            title        = "Test",
            total_slides = 1,
            slides       = [ SlideModel(
                number          = 1,
                arc_position    = "body",
                type            = "content",
                title           = "No Bullets",
                content_bullets = [],
            ) ],
        )
        output = MarpTextRenderer.render( pres, default_theme )
        assert "# No Bullets" in output
        # No bullet lines in this slide's section
        # (there may be bullet-like lines in CSS, so check after the frontmatter)
        after_frontmatter = output.split( "---" )[ -1 ]
        assert "- " not in after_frontmatter


# =============================================================================
# TestPresenterNotes
# =============================================================================

class TestPresenterNotes:
    """Tests for presenter notes HTML comment rendering."""

    def test_notes_full_fields( self ):
        notes = PresenterNotes(
            transition     = "Moving to the next topic.",
            talking_points = [ "First point", "Second point" ],
            timing_seconds = 90,
            emphasis       = "Key takeaway here",
        )
        result = MarpTextRenderer._render_presenter_notes( notes )
        assert "<!--" in result
        assert "-->" in result
        assert "Transition: Moving to the next topic." in result
        assert "- First point" in result
        assert "- Second point" in result
        assert "Timing: 90s" in result
        assert "Emphasis: Key takeaway here" in result

    def test_notes_omits_none_transition( self ):
        notes = PresenterNotes(
            talking_points = [ "Only talking points" ],
            timing_seconds = 60,
        )
        result = MarpTextRenderer._render_presenter_notes( notes )
        assert "Transition:" not in result
        assert "Emphasis:" not in result
        assert "- Only talking points" in result
        assert "Timing: 60s" in result

    def test_notes_empty_talking_points( self ):
        notes = PresenterNotes(
            transition     = "Quick transition.",
            talking_points = [],
            timing_seconds = 15,
        )
        result = MarpTextRenderer._render_presenter_notes( notes )
        assert "Talking points:" not in result
        assert "Transition: Quick transition." in result

    def test_notes_timing_format( self ):
        notes = PresenterNotes( timing_seconds = 120 )
        result = MarpTextRenderer._render_presenter_notes( notes )
        assert "Timing: 120s" in result

    def test_notes_none_returns_empty( self ):
        result = MarpTextRenderer._render_presenter_notes( None )
        assert result == ""

    def test_notes_all_none_returns_empty( self ):
        """Notes with only default/empty values should return empty."""
        notes  = PresenterNotes( talking_points=[], timing_seconds=0 )
        result = MarpTextRenderer._render_presenter_notes( notes )
        assert result == ""


# =============================================================================
# TestVisualPlaceholders
# =============================================================================

class TestVisualPlaceholders:
    """Tests for Phase 7 visual placeholder comments."""

    def test_visual_placeholder_emitted( self, default_theme ):
        pres = PresentationModel(
            title        = "Test",
            total_slides = 1,
            slides       = [ SlideModel(
                number             = 1,
                arc_position       = "body",
                type               = "content",
                title              = "Diagram Slide",
                visual_type        = "diagram",
                visual_description = "Architecture flowchart showing three layers",
            ) ],
        )
        output = MarpTextRenderer.render( pres, default_theme )
        assert "<!-- VISUAL: diagram | Architecture flowchart showing three layers -->" in output

    def test_text_only_no_placeholder( self, default_theme ):
        pres = PresentationModel(
            title        = "Test",
            total_slides = 1,
            slides       = [ SlideModel(
                number       = 1,
                arc_position = "body",
                type         = "content",
                title        = "Text Only Slide",
                visual_type  = "text_only",
            ) ],
        )
        output = MarpTextRenderer.render( pres, default_theme )
        assert "<!-- VISUAL:" not in output

    def test_visual_placeholder_no_description( self, default_theme ):
        pres = PresentationModel(
            title        = "Test",
            total_slides = 1,
            slides       = [ SlideModel(
                number             = 1,
                arc_position       = "body",
                type               = "content",
                title              = "Chart Slide",
                visual_type        = "chart",
                visual_description = None,
            ) ],
        )
        output = MarpTextRenderer.render( pres, default_theme )
        assert "<!-- VISUAL: chart | (no description provided) -->" in output


# =============================================================================
# TestFullRender
# =============================================================================

class TestFullRender:
    """Tests for the complete render pipeline."""

    def test_slide_separator_count( self, sample_presentation, default_theme ):
        """Number of --- separator lines should be: 2 (frontmatter) + (N-1) slides."""
        output    = MarpTextRenderer.render( sample_presentation, default_theme )
        sep_lines = [ l for l in output.split( "\n" ) if l.strip() == "---" ]
        # 2 for frontmatter open/close + 4 separators between 5 slides
        expected  = 2 + ( len( sample_presentation.slides ) - 1 )
        assert len( sep_lines ) == expected, f"Expected {expected} ---, got {len( sep_lines )}"

    def test_round_trip_structure( self, sample_presentation, default_theme ):
        """Full render should produce valid structure with all slides."""
        output = MarpTextRenderer.render( sample_presentation, default_theme )

        # Starts with frontmatter
        assert output.startswith( "---\nmarp: true" )

        # Contains all slide titles
        for slide in sample_presentation.slides:
            assert f"# {slide.title}" in output

    def test_empty_presentation( self, default_theme ):
        """Empty presentation (0 slides) renders frontmatter only."""
        pres   = PresentationModel( title="Empty Deck", total_slides=0 )
        output = MarpTextRenderer.render( pres, default_theme )
        assert "marp: true" in output
        # Only the frontmatter --- delimiters
        sep_lines = [ l for l in output.split( "\n" ) if l.strip() == "---" ]
        assert len( sep_lines ) == 2

    def test_single_slide( self, default_theme ):
        """Single slide should have no extra separator after frontmatter."""
        pres = PresentationModel(
            title        = "One Slide",
            total_slides = 1,
            slides       = [ SlideModel(
                number       = 1,
                arc_position = "opening",
                type         = "title",
                title        = "One Slide",
            ) ],
        )
        output    = MarpTextRenderer.render( pres, default_theme )
        sep_lines = [ l for l in output.split( "\n" ) if l.strip() == "---" ]
        # 2 for frontmatter, 0 slide separators (only 1 slide)
        assert len( sep_lines ) == 2

    def test_output_ends_with_newline( self, sample_presentation, default_theme ):
        output = MarpTextRenderer.render( sample_presentation, default_theme )
        assert output.endswith( "\n" )

    def test_minimal_presentation_no_errors( self, minimal_presentation, default_theme ):
        """Minimal presentation with no speaker/date should render without errors."""
        output = MarpTextRenderer.render( minimal_presentation, default_theme )
        assert "marp: true" in output
        assert "# Minimal Deck" in output


# =============================================================================
# TestCSSGeneration
# =============================================================================

class TestCSSGeneration:
    """Tests for CSS style block generation."""

    def test_css_contains_primary_color( self ):
        css = MarpTextRenderer._generate_css( DEFAULT_THEME_CONFIG )
        assert "#2563EB" in css

    def test_css_contains_body_font( self ):
        css = MarpTextRenderer._generate_css( DEFAULT_THEME_CONFIG )
        assert "Inter, sans-serif" in css

    def test_css_contains_code_font( self ):
        css = MarpTextRenderer._generate_css( DEFAULT_THEME_CONFIG )
        assert "JetBrains Mono, monospace" in css

    def test_css_contains_accent_color( self ):
        css = MarpTextRenderer._generate_css( DEFAULT_THEME_CONFIG )
        assert "#F59E0B" in css


# =============================================================================
# TestThemeLoading
# =============================================================================

class TestThemeLoading:
    """Tests for orchestrator theme loading (static method)."""

    def test_load_existing_theme( self ):
        """Loading the default theme file should return valid config."""
        from cosa.agents.presentation_generator.orchestrator import PresentationOrchestratorAgent

        config = PresentationOrchestratorAgent._load_theme_config(
            "/src/cosa/agents/presentation_generator/templates/themes/",
            "default"
        )
        assert "theme" in config
        assert config[ "theme" ][ "name" ] == "default"
        assert "colors" in config[ "theme" ]
        assert "fonts" in config[ "theme" ]

    def test_missing_theme_fallback( self ):
        """Missing theme file should return fallback default config."""
        from cosa.agents.presentation_generator.orchestrator import PresentationOrchestratorAgent

        config = PresentationOrchestratorAgent._load_theme_config(
            "/src/cosa/agents/presentation_generator/templates/themes/",
            "nonexistent_theme_xyz"
        )
        assert "theme" in config
        assert config[ "theme" ][ "marp_theme" ] == "default"

    def test_theme_config_has_expected_keys( self ):
        """Loaded theme should have all expected nested keys."""
        from cosa.agents.presentation_generator.orchestrator import PresentationOrchestratorAgent

        config = PresentationOrchestratorAgent._load_theme_config(
            "/src/cosa/agents/presentation_generator/templates/themes/",
            "default"
        )
        theme = config[ "theme" ]
        assert "colors" in theme
        assert "fonts" in theme
        assert "layout" in theme
        assert "primary" in theme[ "colors" ]
        assert "heading" in theme[ "fonts" ]
        assert "paginate" in theme[ "layout" ]


# =============================================================================
# TestTemplateInterpolation
# =============================================================================

class TestTemplateInterpolation:
    """Tests for header/footer template variable substitution."""

    def test_interpolate_speaker_and_date( self, sample_presentation ):
        result = MarpTextRenderer._interpolate_template(
            "{speaker} | {date}", sample_presentation
        )
        assert result == "Jane Doe | 2026-03-28"

    def test_interpolate_title( self, sample_presentation ):
        result = MarpTextRenderer._interpolate_template(
            "{title}", sample_presentation
        )
        assert result == "Three-Layer Caching at Scale"

    def test_interpolate_empty_template( self, sample_presentation ):
        result = MarpTextRenderer._interpolate_template( "", sample_presentation )
        assert result == ""

    def test_interpolate_empty_fields( self, minimal_presentation ):
        result = MarpTextRenderer._interpolate_template(
            "{speaker} | {date}", minimal_presentation
        )
        assert result == "|"
