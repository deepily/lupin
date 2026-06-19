#!/usr/bin/env python3
"""
Unit tests for renderers/veo_renderer.py

Gemini Veo-backed video renderer with ffmpeg frame extraction. Boundaries
mocked: gemini_client.generate_video (AsyncMock), shutil.which (ffmpeg),
subprocess.run (frame extraction), os.makedirs/exists/getsize.
"""

import asyncio
import subprocess
from unittest.mock import MagicMock, AsyncMock, patch

import pytest

from cosa.agents.presentation_generator.renderers import veo_renderer as veomod
from cosa.agents.presentation_generator.renderers.veo_renderer import VeoRenderer


def _run( coro ):
    return asyncio.run( coro )


def _client( success=True ):
    c = MagicMock()
    c.generate_video = AsyncMock( return_value=success )
    return c


class TestCheckFfmpeg:
    def test_available_debug( self, capsys ):
        r = VeoRenderer( debug=True )
        with patch.object( veomod.shutil, "which", return_value="/usr/bin/ffmpeg" ):
            assert r._check_ffmpeg_available() is True
            assert r._check_ffmpeg_available() is True   # cached
        assert "ffmpeg found" in capsys.readouterr().out

    def test_available_no_debug_silent( self, capsys ):
        r = VeoRenderer( debug=False )
        with patch.object( veomod.shutil, "which", return_value="/usr/bin/ffmpeg" ):
            assert r._check_ffmpeg_available() is True
        assert "ffmpeg found" not in capsys.readouterr().out

    def test_not_available( self ):
        r = VeoRenderer()
        with patch.object( veomod.shutil, "which", return_value=None ):
            assert r._check_ffmpeg_available() is False


class TestExtractFrame:
    def _patch_run( self, returncode=0, stderr="", exc=None ):
        if exc:
            return patch.object( veomod.subprocess, "run", side_effect=exc )
        return patch.object( veomod.subprocess, "run", return_value=MagicMock( returncode=returncode, stderr=stderr ) )

    def test_success( self ):
        r = VeoRenderer()
        with self._patch_run( returncode=0 ), patch( "os.path.exists", return_value=True ):
            assert _run( r._extract_frame( "/v.mp4", "/f.png" ) ) is True

    def test_nonzero( self ):
        r = VeoRenderer()
        with self._patch_run( returncode=1, stderr="err" ):
            assert _run( r._extract_frame( "/v.mp4", "/f.png" ) ) is False

    def test_timeout( self ):
        r = VeoRenderer()
        with self._patch_run( exc=subprocess.TimeoutExpired( cmd="ffmpeg", timeout=15 ) ):
            assert _run( r._extract_frame( "/v.mp4", "/f.png" ) ) is False

    def test_generic_exception( self ):
        r = VeoRenderer()
        with self._patch_run( exc=OSError( "x" ) ):
            assert _run( r._extract_frame( "/v.mp4", "/f.png" ) ) is False


class TestRender:
    def test_no_client( self ):
        assert _run( VeoRenderer().render( "title_video", "x", output_dir="/o" ) ) is None

    def test_no_output_dir( self ):
        assert _run( VeoRenderer( gemini_client=_client() ).render( "title_video", "x" ) ) is None

    def test_max_videos_reached( self ):
        r = VeoRenderer( gemini_client=_client(), max_videos=1 )
        r._videos_rendered = 1
        assert _run( r.render( "title_video", "x", output_dir="/o" ) ) is None

    def test_generation_failure( self ):
        r = VeoRenderer( gemini_client=_client( success=False ) )
        with patch( "os.makedirs" ):
            assert _run( r.render( "title_video", "x", output_dir="/o" ) ) is None

    def test_video_not_created( self ):
        r = VeoRenderer( gemini_client=_client() )
        with patch( "os.makedirs" ), patch( "os.path.exists", return_value=False ):
            assert _run( r.render( "title_video", "x", output_dir="/o" ) ) is None

    def test_success_with_frame_debug( self, capsys ):
        r = VeoRenderer( gemini_client=_client(), debug=True )
        with patch( "os.makedirs" ), patch( "os.path.exists", return_value=True ), \
             patch( "os.path.getsize", return_value=5000 ), \
             patch.object( veomod.shutil, "which", return_value="/usr/bin/ffmpeg" ), \
             patch.object( VeoRenderer, "_extract_frame", new=AsyncMock( return_value=True ) ):
            out = _run( r.render( "title_video", "desc", output_dir="/o", slide_title="Intro", slide_index=1 ) )
        assert '<video src="visuals/video-001.mp4"' in out
        assert '<img src="visuals/video-001-frame.png"' in out
        assert 'alt="Intro"' in out
        assert r._videos_rendered == 1
        assert "[VeoRenderer] Video 1" in capsys.readouterr().out

    def test_success_no_frame_when_ffmpeg_missing( self ):
        r = VeoRenderer( gemini_client=_client() )
        with patch( "os.makedirs" ), patch( "os.path.exists", return_value=True ), \
             patch.object( veomod.shutil, "which", return_value=None ):
            out = _run( r.render( "flow_animation", "a long description for alt text", output_dir="/o" ) )
        assert "<video" in out
        assert "<img" not in out   # no frame → video-only HTML

    def test_exception_debug( self, capsys ):
        c = MagicMock()
        c.generate_video = AsyncMock( side_effect=RuntimeError( "veo down" ) )
        r = VeoRenderer( gemini_client=c, debug=True )
        with patch( "os.makedirs" ):
            assert _run( r.render( "title_video", "x", output_dir="/o" ) ) is None
        assert "[VeoRenderer] Exception" in capsys.readouterr().out

    def test_supported_types( self ):
        assert VeoRenderer.SUPPORTED_TYPES == [ "title_video", "flow_animation", "process_video" ]


if __name__ == "__main__":
    pytest.main( [ __file__, "-v" ] )
