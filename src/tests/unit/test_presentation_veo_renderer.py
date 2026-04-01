#!/usr/bin/env python3
"""
Unit tests for VeoRenderer — Phase 10B Visual Rendering.

Tests cover:
    - VeoRenderer construction and configuration
    - Video generation via mocked GeminiImageClient
    - Frame extraction via mocked ffmpeg subprocess
    - Dual HTML output (video tag + img fallback)
    - Video generation prompt module
    - GeminiImageClient video cost tracking and budget
    - Registry integration (dispatch for title_video/flow_animation/process_video)
"""

import asyncio
import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from cosa.agents.presentation_generator.renderers.veo_renderer import VeoRenderer
from cosa.agents.presentation_generator.renderers.visual_registry import (
    VisualRendererRegistry,
)
from cosa.agents.presentation_generator.renderers.placeholder import PlaceholderRenderer
from cosa.agents.presentation_generator.gemini_client import (
    GeminiImageClient,
    COST_PER_VIDEO_SECOND,
)
from cosa.agents.presentation_generator.prompts.video_gen import (
    VIDEO_DURATION_MAP,
    VIDEO_STYLE_MODIFIERS,
    VIDEO_SYSTEM_RULES,
    DEFAULT_VIDEO_DURATION,
    get_video_prompt,
    get_video_duration,
)


# =============================================================================
# TestVeoRenderer
# =============================================================================

class TestVeoRenderer:
    """Tests for VeoRenderer construction and configuration."""

    def test_construction_defaults( self ):
        """VeoRenderer initializes with default values."""
        renderer = VeoRenderer()
        assert renderer.gemini_client is None
        assert renderer.max_videos == 5
        assert renderer.debug is False
        assert renderer._ffmpeg_available is None
        assert renderer._videos_rendered == 0

    def test_construction_with_params( self ):
        """VeoRenderer accepts gemini_client, max_videos, debug."""
        mock_client = MagicMock()
        renderer    = VeoRenderer( gemini_client=mock_client, max_videos=3, debug=True )
        assert renderer.gemini_client is mock_client
        assert renderer.max_videos == 3
        assert renderer.debug is True

    def test_supported_types( self ):
        """VeoRenderer handles title_video, flow_animation, process_video."""
        assert "title_video" in VeoRenderer.SUPPORTED_TYPES
        assert "flow_animation" in VeoRenderer.SUPPORTED_TYPES
        assert "process_video" in VeoRenderer.SUPPORTED_TYPES
        assert len( VeoRenderer.SUPPORTED_TYPES ) == 3

    @patch( "shutil.which", return_value="/usr/bin/ffmpeg" )
    def test_ffmpeg_available_cached( self, mock_which ):
        """ffmpeg check is cached after first call."""
        renderer = VeoRenderer()
        assert renderer._check_ffmpeg_available() is True
        assert renderer._check_ffmpeg_available() is True
        mock_which.assert_called_once_with( "ffmpeg" )


# =============================================================================
# TestVideoGeneration
# =============================================================================

class TestVideoGeneration:
    """Tests for video generation via mocked GeminiImageClient."""

    def test_generate_video_success( self, tmp_path ):
        """Successful video generation creates MP4 and returns HTML."""
        renderer = VeoRenderer( debug=True )
        renderer._ffmpeg_available = False  # Skip frame extraction

        output_dir = str( tmp_path / "visuals" )

        # Mock gemini client
        mock_client                = MagicMock()
        mock_client.generate_video = AsyncMock( return_value=True )
        renderer.gemini_client     = mock_client

        # Create fake video file to simulate output
        os.makedirs( output_dir, exist_ok=True )
        video_path = os.path.join( output_dir, "video-002.mp4" )
        with open( video_path, "wb" ) as f:
            f.write( b"fake-mp4-data" )

        result = asyncio.run( renderer.render(
            visual_type        = "title_video",
            visual_description = "Abstract tech landscape",
            slide_title        = "Welcome",
            output_dir         = output_dir,
            slide_index        = 2,
        ) )

        assert result is not None
        assert "<video" in result
        assert "visuals/video-002.mp4" in result
        assert renderer._videos_rendered == 1
        mock_client.generate_video.assert_awaited_once()

    def test_generate_video_api_failure( self, tmp_path ):
        """Returns None when gemini_client.generate_video returns False."""
        renderer = VeoRenderer()

        mock_client                = MagicMock()
        mock_client.generate_video = AsyncMock( return_value=False )
        renderer.gemini_client     = mock_client

        result = asyncio.run( renderer.render(
            "title_video", "test",
            output_dir=str( tmp_path ), slide_index=0
        ) )
        assert result is None

    def test_max_videos_exceeded( self, tmp_path ):
        """Returns None when per-deck video limit reached."""
        renderer = VeoRenderer( gemini_client=MagicMock(), max_videos=2 )
        renderer._videos_rendered = 2  # Already at limit

        result = asyncio.run( renderer.render(
            "title_video", "test",
            output_dir=str( tmp_path )
        ) )
        assert result is None

    def test_render_missing_client( self ):
        """Returns None when gemini_client is not provided."""
        renderer = VeoRenderer()
        result   = asyncio.run( renderer.render( "title_video", "test", output_dir="/tmp" ) )
        assert result is None

    def test_render_missing_output_dir( self ):
        """Returns None when output_dir is not provided."""
        renderer = VeoRenderer( gemini_client=MagicMock() )
        result   = asyncio.run( renderer.render( "title_video", "test" ) )
        assert result is None


# =============================================================================
# TestFrameExtraction
# =============================================================================

class TestFrameExtraction:
    """Tests for ffmpeg frame extraction (mocked subprocess)."""

    def test_frame_extraction_success( self, tmp_path ):
        """Successful ffmpeg extraction creates PNG frame."""
        renderer = VeoRenderer()

        video_path = str( tmp_path / "test.mp4" )
        frame_path = str( tmp_path / "test-frame.png" )

        mock_result            = MagicMock()
        mock_result.returncode = 0

        with patch( "subprocess.run", return_value=mock_result ):
            # Create frame file to simulate ffmpeg output
            with open( frame_path, "w" ) as f:
                f.write( "fake-png" )
            result = asyncio.run( renderer._extract_frame( video_path, frame_path ) )

        assert result is True

    @patch( "shutil.which", return_value=None )
    def test_ffmpeg_not_found( self, mock_which ):
        """Returns video-only HTML when ffmpeg not installed."""
        renderer = VeoRenderer()
        assert renderer._check_ffmpeg_available() is False

    def test_frame_extraction_timeout( self, tmp_path ):
        """Returns False when ffmpeg times out."""
        import subprocess as sp
        renderer   = VeoRenderer()
        video_path = str( tmp_path / "test.mp4" )
        frame_path = str( tmp_path / "test-frame.png" )

        with patch( "subprocess.run", side_effect=sp.TimeoutExpired( "ffmpeg", 15 ) ):
            result = asyncio.run( renderer._extract_frame( video_path, frame_path ) )

        assert result is False

    def test_frame_extraction_failure( self, tmp_path ):
        """Returns False when ffmpeg returns non-zero exit code."""
        renderer   = VeoRenderer()
        video_path = str( tmp_path / "test.mp4" )
        frame_path = str( tmp_path / "test-frame.png" )

        mock_result            = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr     = "Invalid data found"

        with patch( "subprocess.run", return_value=mock_result ):
            result = asyncio.run( renderer._extract_frame( video_path, frame_path ) )

        assert result is False


# =============================================================================
# TestDualOutput
# =============================================================================

class TestDualOutput:
    """Tests for dual-format HTML output."""

    def test_video_tag_with_frame( self, tmp_path ):
        """HTML includes video tag with img fallback when frame exists."""
        renderer = VeoRenderer( debug=True )
        renderer._ffmpeg_available = True

        output_dir = str( tmp_path / "visuals" )
        os.makedirs( output_dir, exist_ok=True )

        mock_client                = MagicMock()
        mock_client.generate_video = AsyncMock( return_value=True )
        renderer.gemini_client     = mock_client

        # Create fake video
        video_path = os.path.join( output_dir, "video-001.mp4" )
        with open( video_path, "wb" ) as f:
            f.write( b"fake-mp4" )

        # Mock ffmpeg to create frame
        mock_result            = MagicMock()
        mock_result.returncode = 0

        def fake_ffmpeg( *args, **kwargs ):
            frame_path = os.path.join( output_dir, "video-001-frame.png" )
            with open( frame_path, "w" ) as f:
                f.write( "fake-png" )
            return mock_result

        with patch( "subprocess.run", side_effect=fake_ffmpeg ):
            result = asyncio.run( renderer.render(
                "title_video", "Abstract landscape",
                slide_title="Welcome", output_dir=output_dir, slide_index=1
            ) )

        assert result is not None
        assert "<video" in result
        assert "<img" in result
        assert "video-001-frame.png" in result

    def test_video_tag_without_frame( self, tmp_path ):
        """HTML has video tag only when ffmpeg unavailable."""
        renderer = VeoRenderer()
        renderer._ffmpeg_available = False

        output_dir = str( tmp_path / "visuals" )
        os.makedirs( output_dir, exist_ok=True )

        mock_client                = MagicMock()
        mock_client.generate_video = AsyncMock( return_value=True )
        renderer.gemini_client     = mock_client

        # Create fake video
        video_path = os.path.join( output_dir, "video-000.mp4" )
        with open( video_path, "wb" ) as f:
            f.write( b"fake-mp4" )

        result = asyncio.run( renderer.render(
            "flow_animation", "Data pipeline stages",
            output_dir=output_dir, slide_index=0
        ) )

        assert result is not None
        assert "<video" in result
        assert "<img" not in result

    def test_alt_text_from_title( self, tmp_path ):
        """Alt text uses slide_title when provided."""
        renderer = VeoRenderer()
        renderer._ffmpeg_available = False

        output_dir = str( tmp_path / "visuals" )
        os.makedirs( output_dir, exist_ok=True )

        mock_client                = MagicMock()
        mock_client.generate_video = AsyncMock( return_value=True )
        renderer.gemini_client     = mock_client

        video_path = os.path.join( output_dir, "video-000.mp4" )
        with open( video_path, "wb" ) as f:
            f.write( b"fake" )

        result = asyncio.run( renderer.render(
            "title_video", "Abstract landscape",
            slide_title="My Presentation", output_dir=output_dir
        ) )

        # No img tag since no frame, but video tag should be present
        assert result is not None
        assert "<video" in result

    def test_autoplay_muted_loop_attributes( self, tmp_path ):
        """Video tag includes autoplay, muted, and loop attributes."""
        renderer = VeoRenderer()
        renderer._ffmpeg_available = False

        output_dir = str( tmp_path / "visuals" )
        os.makedirs( output_dir, exist_ok=True )

        mock_client                = MagicMock()
        mock_client.generate_video = AsyncMock( return_value=True )
        renderer.gemini_client     = mock_client

        video_path = os.path.join( output_dir, "video-000.mp4" )
        with open( video_path, "wb" ) as f:
            f.write( b"fake" )

        result = asyncio.run( renderer.render(
            "title_video", "test", output_dir=output_dir
        ) )

        assert "autoplay" in result
        assert "muted" in result
        assert "loop" in result


# =============================================================================
# TestVideoPrompts
# =============================================================================

class TestVideoPrompts:
    """Tests for the video generation prompt module."""

    def test_prompt_builder_title_video( self ):
        """Prompt for title_video includes cinematic style."""
        prompt = get_video_prompt( "title_video", "Technology landscape", "Welcome" )
        assert "Welcome" in prompt
        assert "cinematic" in prompt.lower()
        assert "1080p" in prompt

    def test_duration_map_values( self ):
        """Duration map has correct values for each type."""
        assert get_video_duration( "title_video" ) == 5
        assert get_video_duration( "flow_animation" ) == 6
        assert get_video_duration( "process_video" ) == 8
        assert get_video_duration( "unknown" ) == DEFAULT_VIDEO_DURATION

    def test_style_modifiers_exist( self ):
        """Every type in duration map has a style modifier."""
        for vtype in VIDEO_DURATION_MAP:
            assert vtype in VIDEO_STYLE_MODIFIERS, f"Missing style for {vtype}"

    def test_system_rules_content( self ):
        """System rules include quality and safety constraints."""
        assert "1080p" in VIDEO_SYSTEM_RULES
        assert "watermark" in VIDEO_SYSTEM_RULES.lower()
        assert "text overlay" in VIDEO_SYSTEM_RULES.lower()


# =============================================================================
# TestGeminiClientVideo
# =============================================================================

class TestGeminiClientVideo:
    """Tests for GeminiImageClient video generation support."""

    def test_video_model_stored( self ):
        """Constructor stores video_model parameter."""
        client = GeminiImageClient( video_model="veo-3.0-generate-001" )
        assert client.video_model == "veo-3.0-generate-001"

    def test_video_cost_tracking( self ):
        """_track_video_cost increments counters correctly."""
        client = GeminiImageClient()
        assert client.video_cost_total == 0.0
        assert client.videos_generated == 0

        client._track_video_cost( 5 )
        assert client.video_cost_total == 5 * COST_PER_VIDEO_SECOND
        assert client.videos_generated == 1

        client._track_video_cost( 8 )
        assert client.video_cost_total == ( 5 + 8 ) * COST_PER_VIDEO_SECOND
        assert client.videos_generated == 2

    def test_video_budget_enforcement( self ):
        """generate_video returns False when budget exceeded."""
        client = GeminiImageClient( video_budget_limit=1.00 )
        # Simulate prior spend that exceeds budget for an 8s video ($1.60)
        client.video_cost_total = 0.50  # $0.50 spent

        # 8s * $0.20 = $1.60 > $1.00 remaining budget ($0.50 + $1.60 > $1.00)
        result = asyncio.run( client.generate_video( "test prompt", "/tmp/test.mp4", 8 ) )
        assert result is False


# =============================================================================
# TestRegistryIntegration
# =============================================================================

class TestRegistryIntegration:
    """Tests for VeoRenderer registration in VisualRendererRegistry."""

    def test_veo_registered_for_supported_types( self ):
        """VeoRenderer registers for all 3 video types."""
        fallback = PlaceholderRenderer()
        registry = VisualRendererRegistry( fallback=fallback )

        veo = VeoRenderer()
        registry.register( veo )

        assert registry.get( "title_video" ) is veo
        assert registry.get( "flow_animation" ) is veo
        assert registry.get( "process_video" ) is veo

    def test_unknown_type_falls_back( self ):
        """Unknown types still fall back to PlaceholderRenderer."""
        fallback = PlaceholderRenderer()
        registry = VisualRendererRegistry( fallback=fallback )

        veo = VeoRenderer()
        registry.register( veo )

        assert registry.get( "unknown_type" ) is fallback
