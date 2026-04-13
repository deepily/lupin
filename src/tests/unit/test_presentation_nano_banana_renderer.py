#!/usr/bin/env python3
"""
Unit tests for Phase 10A NanoBananaRenderer — Gemini image generation.

Tests cover:
    - GeminiImageClient (construction, lazy init, cost tracking, budget limit)
    - NanoBananaRenderer (construction, SUPPORTED_TYPES, render with mocked client)
    - Image generation prompts (style modifiers, prompt builder, no-text directive)
    - Renderer integration (mock generate_image success/failure, cost tracking)
    - Registry integration (all 4 types registered, no overlap)
    - Error handling (API exception, RAI filter)
"""

import asyncio
import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from cosa.agents.presentation_generator.renderers.nano_banana import NanoBananaRenderer
from cosa.agents.presentation_generator.renderers.visual_registry import (
    VisualRenderer,
    VisualRendererRegistry,
)
from cosa.agents.presentation_generator.renderers.placeholder import PlaceholderRenderer
from cosa.agents.presentation_generator.gemini_client import (
    GeminiImageClient,
    COST_PER_IMAGE_1K,
)
from cosa.agents.presentation_generator.prompts.image_gen import (
    IMAGE_STYLE_MODIFIERS,
    NO_TEXT_TYPES,
    DEFAULT_STYLE_MODIFIER,
    get_image_prompt,
)


# =============================================================================
# TestGeminiImageClient
# =============================================================================

class TestGeminiImageClient:
    """Tests for the shared Gemini image generation client."""

    def test_construction_defaults( self ):
        """GeminiImageClient initializes with correct defaults."""
        client = GeminiImageClient()
        assert client.model == "imagen-4.0-generate-001"
        assert client.aspect_ratio == "16:9"
        assert client.budget_limit == 1.00
        assert client.cost_total == 0.0
        assert client.images_generated == 0
        assert client._client is None

    def test_construction_custom( self ):
        """GeminiImageClient accepts custom parameters."""
        client = GeminiImageClient(
            model="custom-model", aspect_ratio="1:1",
            budget_limit=5.0, debug=True
        )
        assert client.model == "custom-model"
        assert client.aspect_ratio == "1:1"
        assert client.budget_limit == 5.0

    def test_lazy_init_not_triggered( self ):
        """Client not initialized until _get_client() called."""
        client = GeminiImageClient()
        assert client._client is None

    def test_cost_tracking( self ):
        """_track_cost() accumulates cost correctly."""
        client = GeminiImageClient()
        assert client.cost_total == 0.0
        client._track_cost()
        assert client.cost_total == COST_PER_IMAGE_1K
        client._track_cost()
        assert client.cost_total == COST_PER_IMAGE_1K * 2

    def test_budget_limit_blocks_generation( self ):
        """generate_image() returns False when budget exceeded."""
        client = GeminiImageClient( budget_limit=0.05 )
        # Manually set cost over budget
        client.cost_total = 0.10
        result = asyncio.run( client.generate_image( "test prompt", "/tmp/test.png" ) )
        assert result is False


# =============================================================================
# TestNanoBananaRenderer
# =============================================================================

class TestNanoBananaRenderer:
    """Tests for NanoBananaRenderer construction and render() method."""

    def test_construction( self ):
        """NanoBananaRenderer can be instantiated."""
        renderer = NanoBananaRenderer( debug=True, verbose=True )
        assert renderer.debug is True
        assert renderer.verbose is True
        assert renderer.gemini_client is None

    def test_supported_types( self ):
        """SUPPORTED_TYPES includes all 4 image types."""
        assert "hero_image" in NanoBananaRenderer.SUPPORTED_TYPES
        assert "infographic" in NanoBananaRenderer.SUPPORTED_TYPES
        assert "title_background" in NanoBananaRenderer.SUPPORTED_TYPES
        assert "icon" in NanoBananaRenderer.SUPPORTED_TYPES

    def test_is_visual_renderer_subclass( self ):
        """NanoBananaRenderer is a VisualRenderer subclass."""
        renderer = NanoBananaRenderer()
        assert isinstance( renderer, VisualRenderer )

    def test_render_returns_none_without_client( self ):
        """render() returns None when no gemini_client provided."""
        renderer = NanoBananaRenderer()
        result   = asyncio.run( renderer.render(
            "hero_image", "A sunset over mountains",
            output_dir="/tmp/test"
        ) )
        assert result is None

    def test_render_returns_none_without_output_dir( self ):
        """render() returns None when no output_dir provided."""
        renderer = NanoBananaRenderer( gemini_client=MagicMock() )
        result   = asyncio.run( renderer.render(
            "hero_image", "A sunset over mountains"
        ) )
        assert result is None


# =============================================================================
# TestImagePrompt
# =============================================================================

class TestImagePrompt:
    """Tests for image generation prompt builder."""

    def test_style_modifiers_exist_for_all_types( self ):
        """All NanoBananaRenderer SUPPORTED_TYPES have style modifiers."""
        for visual_type in NanoBananaRenderer.SUPPORTED_TYPES:
            assert visual_type in IMAGE_STYLE_MODIFIERS, f"Missing modifier for: {visual_type}"

    def test_hero_image_prompt( self ):
        """Hero image prompt includes photorealistic style."""
        prompt = get_image_prompt( "hero_image", "A futuristic city", "The Future" )
        assert "photorealistic" in prompt
        assert "futuristic city" in prompt
        assert "The Future" in prompt

    def test_infographic_prompt( self ):
        """Infographic prompt includes flat design style."""
        prompt = get_image_prompt( "infographic", "Revenue breakdown", "Revenue" )
        assert "flat design" in prompt
        assert "Revenue breakdown" in prompt

    def test_title_background_prompt( self ):
        """Title background prompt includes abstract style."""
        prompt = get_image_prompt( "title_background", "Technology theme", "Welcome" )
        assert "abstract" in prompt or "gradient" in prompt

    def test_icon_prompt( self ):
        """Icon prompt includes flat icon style."""
        prompt = get_image_prompt( "icon", "A gear symbol", "Settings" )
        assert "flat icon" in prompt

    def test_no_text_directive_for_non_infographic( self ):
        """Non-infographic types include 'no text' directive."""
        for visual_type in NO_TEXT_TYPES:
            prompt = get_image_prompt( visual_type, "Test description" )
            assert "Do not include any text" in prompt, f"Missing no-text for: {visual_type}"

    def test_infographic_allows_text( self ):
        """Infographic type does NOT include 'no text' directive."""
        prompt = get_image_prompt( "infographic", "Data visualization" )
        assert "Do not include any text" not in prompt

    def test_slide_title_included( self ):
        """Slide title is included in prompt when provided."""
        prompt = get_image_prompt( "hero_image", "Description", "My Slide Title" )
        assert "My Slide Title" in prompt

    def test_16_9_composition_hint( self ):
        """All prompts include 16:9 composition hint."""
        prompt = get_image_prompt( "hero_image", "Test" )
        assert "16:9" in prompt

    def test_empty_description( self ):
        """Prompt builder handles empty description gracefully."""
        prompt = get_image_prompt( "icon", "" )
        assert "flat icon" in prompt
        assert "16:9" in prompt


# =============================================================================
# TestRendererIntegration
# =============================================================================

class TestRendererIntegration:
    """Tests for render() with mocked GeminiImageClient."""

    def test_render_success( self, tmp_path ):
        """render() returns markdown image reference on success."""
        # Create a mock client that "generates" an image
        mock_client = MagicMock()

        output_dir = str( tmp_path / "visuals" )
        os.makedirs( output_dir, exist_ok=True )

        async def mock_generate( prompt, output_path, **kwargs ):
            # Create a fake PNG file
            with open( output_path, "wb" ) as f:
                f.write( b"\x89PNG\r\n\x1a\n" + b"\x00" * 100 )
            return True

        mock_client.generate_image = mock_generate

        renderer = NanoBananaRenderer( gemini_client=mock_client )
        result   = asyncio.run( renderer.render(
            visual_type        = "hero_image",
            visual_description = "A sunset over mountains",
            slide_title        = "Beautiful Sunset",
            output_dir         = output_dir,
            slide_index        = 2,
        ) )

        assert result is not None
        assert "![" in result
        assert "visuals/image-002.png" in result

    def test_render_failure( self, tmp_path ):
        """render() returns None when generate_image returns False."""
        mock_client = MagicMock()

        async def mock_generate( prompt, output_path, **kwargs ):
            return False

        mock_client.generate_image = mock_generate

        output_dir = str( tmp_path / "visuals" )
        os.makedirs( output_dir, exist_ok=True )

        renderer = NanoBananaRenderer( gemini_client=mock_client )
        result   = asyncio.run( renderer.render(
            "hero_image", "A sunset",
            output_dir=output_dir,
        ) )
        assert result is None

    def test_cost_tracking_via_client( self ):
        """Cost is tracked on the shared GeminiImageClient."""
        client = GeminiImageClient()
        assert client.cost_total == 0.0
        client._track_cost()
        client._track_cost()
        client._track_cost()
        assert client.images_generated == 0  # _track_cost doesn't increment this
        assert abs( client.cost_total - COST_PER_IMAGE_1K * 3 ) < 0.001


# =============================================================================
# TestRegistryIntegration
# =============================================================================

class TestRegistryIntegration:
    """Tests for NanoBananaRenderer integration with VisualRendererRegistry."""

    def test_registered_for_all_image_types( self ):
        """NanoBananaRenderer handles all 4 image types in registry."""
        fallback = PlaceholderRenderer()
        registry = VisualRendererRegistry( fallback=fallback )

        renderer = NanoBananaRenderer()
        registry.register( renderer )

        for visual_type in [ "hero_image", "infographic", "title_background", "icon" ]:
            assert registry.get( visual_type ) is renderer, \
                f"Expected NanoBananaRenderer for '{visual_type}'"

    def test_no_overlap_with_other_renderers( self ):
        """NanoBananaRenderer types don't overlap with Mermaid or Matplotlib."""
        from cosa.agents.presentation_generator.renderers.mermaid import MermaidRenderer
        from cosa.agents.presentation_generator.renderers.matplotlib_renderer import MatplotlibRenderer

        nano_types       = set( NanoBananaRenderer.SUPPORTED_TYPES )
        mermaid_types    = set( MermaidRenderer.SUPPORTED_TYPES )
        matplotlib_types = set( MatplotlibRenderer.SUPPORTED_TYPES )

        assert len( nano_types & mermaid_types ) == 0, f"Overlap with Mermaid: {nano_types & mermaid_types}"
        assert len( nano_types & matplotlib_types ) == 0, f"Overlap with Matplotlib: {nano_types & matplotlib_types}"


# =============================================================================
# TestErrorHandling
# =============================================================================

class TestErrorHandling:
    """Tests for error handling in render()."""

    def test_api_exception_returns_none( self, tmp_path ):
        """render() returns None when gemini_client raises an exception."""
        mock_client = MagicMock()

        async def mock_generate( prompt, output_path, **kwargs ):
            raise RuntimeError( "API connection error" )

        mock_client.generate_image = mock_generate

        output_dir = str( tmp_path / "visuals" )
        os.makedirs( output_dir, exist_ok=True )

        renderer = NanoBananaRenderer( gemini_client=mock_client )
        result   = asyncio.run( renderer.render(
            "hero_image", "A sunset",
            output_dir=output_dir,
        ) )
        assert result is None

    def test_missing_output_file_returns_none( self, tmp_path ):
        """render() returns None when generate_image returns True but file doesn't exist."""
        mock_client = MagicMock()

        async def mock_generate( prompt, output_path, **kwargs ):
            # Return True but don't actually create the file
            return True

        mock_client.generate_image = mock_generate

        output_dir = str( tmp_path / "visuals" )
        os.makedirs( output_dir, exist_ok=True )

        renderer = NanoBananaRenderer( gemini_client=mock_client )
        result   = asyncio.run( renderer.render(
            "hero_image", "A sunset",
            output_dir=output_dir,
        ) )
        assert result is None
