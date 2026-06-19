#!/usr/bin/env python3
"""
Unit tests for cosa.agents.presentation_generator.gemini_client

GeminiImageClient: image + video generation against google-genai. Boundaries
mocked: _get_client (returns a mock genai client), client.aio.* AsyncMocks,
asyncio.sleep, open / os.path. No real Gemini calls / disk / polling delays.
"""

import asyncio
from unittest.mock import MagicMock, AsyncMock, patch

import pytest

from cosa.agents.presentation_generator import gemini_client as gcmod
from cosa.agents.presentation_generator.gemini_client import (
    GeminiImageClient,
    COST_PER_IMAGE_1K,
    COST_PER_VIDEO_SECOND,
)


def _run( coro ):
    return asyncio.run( coro )


# ---------------------------------------------------------------------------
# construction / cost tracking
# ---------------------------------------------------------------------------
class TestBasics:
    def test_defaults( self ):
        c = GeminiImageClient()
        assert c.aspect_ratio == "16:9"
        assert c.budget_limit == 1.00
        assert c.cost_total == 0.0
        assert c._client is None

    def test_track_cost( self ):
        c = GeminiImageClient()
        c._track_cost()
        assert c.cost_total == COST_PER_IMAGE_1K

    def test_track_video_cost( self ):
        c = GeminiImageClient()
        c._track_video_cost( 8 )
        assert c.video_cost_total == 8 * COST_PER_VIDEO_SECOND
        assert c.videos_generated == 1


# ---------------------------------------------------------------------------
# _get_client
# ---------------------------------------------------------------------------
class TestGetClient:
    def test_initializes_and_caches_debug( self, capsys ):
        c = GeminiImageClient( debug=True )
        fake_client = MagicMock()
        with patch( "google.genai.Client", return_value=fake_client ) as Ctor, \
             patch( "cosa.utils.util.get_api_key", return_value="KEY" ):
            assert c._get_client() is fake_client
            assert c._get_client() is fake_client   # cached → ctor once
            Ctor.assert_called_once()
        assert "[GeminiImageClient] Initialized" in capsys.readouterr().out

    def test_missing_key_raises( self ):
        c = GeminiImageClient()
        with patch( "cosa.utils.util.get_api_key", return_value=None ):
            with pytest.raises( RuntimeError, match="Gemini API key not found" ):
                c._get_client()


# ---------------------------------------------------------------------------
# generate_image
# ---------------------------------------------------------------------------
def _img_client( gen_images ):
    client = MagicMock()
    resp = MagicMock()
    resp.generated_images = gen_images
    client.aio.models.generate_images = AsyncMock( return_value=resp )
    return client


class TestGenerateImage:
    def test_budget_reached( self ):
        c = GeminiImageClient( budget_limit=0.05 )
        c.cost_total = 0.05
        assert _run( c.generate_image( "p", "/o.png" ) ) is False

    def test_success_debug( self, capsys ):
        c = GeminiImageClient( debug=True )
        gen = MagicMock()
        gen.rai_filtered_reason = None
        gen.image = MagicMock()
        client = _img_client( [ gen ] )
        with patch.object( c, "_get_client", return_value=client ), \
             patch( "os.path.exists", return_value=True ), patch( "os.path.getsize", return_value=2048 ):
            assert _run( c.generate_image( "p", "/o.png" ) ) is True
        gen.image.save.assert_called_once_with( "/o.png" )
        assert c.images_generated == 1
        assert c.cost_total == COST_PER_IMAGE_1K
        assert "[GeminiImageClient] Image 1" in capsys.readouterr().out

    def test_success_no_debug( self ):
        c = GeminiImageClient( debug=False )
        gen = MagicMock()
        gen.rai_filtered_reason = None
        gen.image = MagicMock()
        with patch.object( c, "_get_client", return_value=_img_client( [ gen ] ) ):
            assert _run( c.generate_image( "p", "/o.png" ) ) is True
        assert c.images_generated == 1

    def test_no_images( self ):
        c = GeminiImageClient()
        with patch.object( c, "_get_client", return_value=_img_client( [] ) ):
            assert _run( c.generate_image( "p", "/o.png" ) ) is False

    def test_rai_filtered( self ):
        c = GeminiImageClient()
        gen = MagicMock()
        gen.rai_filtered_reason = "unsafe"
        with patch.object( c, "_get_client", return_value=_img_client( [ gen ] ) ):
            assert _run( c.generate_image( "p", "/o.png" ) ) is False

    def test_image_none( self ):
        c = GeminiImageClient()
        gen = MagicMock()
        gen.rai_filtered_reason = None
        gen.image = None
        with patch.object( c, "_get_client", return_value=_img_client( [ gen ] ) ):
            assert _run( c.generate_image( "p", "/o.png" ) ) is False

    def test_exception_debug( self, capsys ):
        c = GeminiImageClient( debug=True )
        with patch.object( c, "_get_client", side_effect=RuntimeError( "boom" ) ):
            assert _run( c.generate_image( "p", "/o.png" ) ) is False
        assert "[GeminiImageClient] Exception" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# generate_video
# ---------------------------------------------------------------------------
def _video_op( done=True, error=None, generated_videos=None, rai_count=None ):
    op = MagicMock()
    op.done = done
    op.error = error
    op.result.generated_videos = generated_videos
    op.result.rai_media_filtered_count = rai_count
    return op


class TestGenerateVideo:
    def test_budget_reached( self ):
        c = GeminiImageClient( video_budget_limit=1.0 )
        assert _run( c.generate_video( "p", "/o.mp4", duration_seconds=8 ) ) is False

    def test_success_no_polling_debug( self, capsys ):
        c = GeminiImageClient( debug=True )
        gen = MagicMock()
        gen.video.video_bytes = b"\x00\x01"
        op = _video_op( done=True, error=None, generated_videos=[ gen ], rai_count=0 )
        client = MagicMock()
        client.aio.models.generate_videos = AsyncMock( return_value=op )
        m = MagicMock()
        with patch.object( c, "_get_client", return_value=client ), \
             patch( "builtins.open", m ), \
             patch( "os.path.exists", return_value=True ), patch( "os.path.getsize", return_value=4096 ):
            assert _run( c.generate_video( "p", "/o.mp4", duration_seconds=5 ) ) is True
        assert c.videos_generated == 1

    def test_polling_then_done( self ):
        c = GeminiImageClient()
        gen = MagicMock()
        gen.video.video_bytes = b"x"
        op1 = _video_op( done=False )
        op2 = _video_op( done=True, generated_videos=[ gen ], rai_count=0 )
        client = MagicMock()
        client.aio.models.generate_videos = AsyncMock( return_value=op1 )
        client.aio.operations.get = AsyncMock( return_value=op2 )
        with patch.object( c, "_get_client", return_value=client ), \
             patch.object( gcmod.asyncio, "sleep", new=AsyncMock() ), \
             patch( "builtins.open", MagicMock() ), patch( "os.path.exists", return_value=True ):
            assert _run( c.generate_video( "p", "/o.mp4", duration_seconds=1 ) ) is True

    def test_timeout( self ):
        c = GeminiImageClient()
        op = _video_op( done=False )
        client = MagicMock()
        client.aio.models.generate_videos = AsyncMock( return_value=op )
        client.aio.operations.get = AsyncMock( return_value=op )
        with patch.object( c, "_get_client", return_value=client ), \
             patch.object( gcmod.asyncio, "sleep", new=AsyncMock() ):
            assert _run( c.generate_video( "p", "/o.mp4", duration_seconds=1 ) ) is False

    def test_operation_error( self ):
        c = GeminiImageClient()
        op = _video_op( done=True, error="boom" )
        client = MagicMock()
        client.aio.models.generate_videos = AsyncMock( return_value=op )
        with patch.object( c, "_get_client", return_value=client ):
            assert _run( c.generate_video( "p", "/o.mp4", duration_seconds=1 ) ) is False

    def test_rai_filtered( self ):
        c = GeminiImageClient()
        gen = MagicMock()
        op = _video_op( done=True, generated_videos=[ gen ], rai_count=1 )
        client = MagicMock()
        client.aio.models.generate_videos = AsyncMock( return_value=op )
        with patch.object( c, "_get_client", return_value=client ):
            assert _run( c.generate_video( "p", "/o.mp4", duration_seconds=1 ) ) is False

    def test_no_video_bytes( self ):
        c = GeminiImageClient()
        gen = MagicMock()
        gen.video.video_bytes = None
        op = _video_op( done=True, generated_videos=[ gen ], rai_count=0 )
        client = MagicMock()
        client.aio.models.generate_videos = AsyncMock( return_value=op )
        with patch.object( c, "_get_client", return_value=client ):
            assert _run( c.generate_video( "p", "/o.mp4", duration_seconds=1 ) ) is False

    def test_no_generated_videos( self ):
        c = GeminiImageClient()
        op = _video_op( done=True, generated_videos=None, rai_count=0 )
        client = MagicMock()
        client.aio.models.generate_videos = AsyncMock( return_value=op )
        with patch.object( c, "_get_client", return_value=client ):
            assert _run( c.generate_video( "p", "/o.mp4", duration_seconds=1 ) ) is False

    def test_exception_debug( self, capsys ):
        c = GeminiImageClient( debug=True )
        with patch.object( c, "_get_client", side_effect=RuntimeError( "down" ) ):
            assert _run( c.generate_video( "p", "/o.mp4", duration_seconds=1 ) ) is False
        assert "[GeminiImageClient] Video exception" in capsys.readouterr().out


if __name__ == "__main__":
    pytest.main( [ __file__, "-v" ] )
