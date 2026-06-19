#!/usr/bin/env python3
"""
Unit tests for renderers/nano_banana.py

Gemini Imagen-backed image renderer. Boundary is the injected gemini_client
(generate_image, AsyncMock) + os.path.exists/getsize. No real API / disk.
"""

import asyncio
from unittest.mock import MagicMock, AsyncMock, patch

import pytest

from cosa.agents.presentation_generator.renderers.nano_banana import NanoBananaRenderer


def _run( coro ):
    return asyncio.run( coro )


def _client( success=True ):
    c = MagicMock()
    c.generate_image = AsyncMock( return_value=success )
    return c


class TestRender:
    def test_no_client( self ):
        assert _run( NanoBananaRenderer().render( "hero_image", "x", output_dir="/o" ) ) is None

    def test_no_output_dir( self ):
        assert _run( NanoBananaRenderer( gemini_client=_client() ).render( "hero_image", "x" ) ) is None

    def test_generation_failure( self ):
        r = NanoBananaRenderer( gemini_client=_client( success=False ) )
        assert _run( r.render( "hero_image", "x", output_dir="/o" ) ) is None

    def test_file_not_created( self ):
        r = NanoBananaRenderer( gemini_client=_client() )
        with patch( "os.path.exists", return_value=False ):
            assert _run( r.render( "hero_image", "x", output_dir="/o" ) ) is None

    def test_success_with_title_debug( self, capsys ):
        r = NanoBananaRenderer( gemini_client=_client(), debug=True )
        with patch( "os.path.exists", return_value=True ), patch( "os.path.getsize", return_value=9999 ):
            out = _run( r.render( "hero_image", "sunset", output_dir="/o", slide_title="Cover", slide_index=3 ) )
        assert out == "![Cover](visuals/image-003.png)"
        printed = capsys.readouterr().out
        assert "[NanoBananaRenderer] Prompt" in printed
        assert "[NanoBananaRenderer] Generated" in printed

    def test_success_alt_from_description( self ):
        r = NanoBananaRenderer( gemini_client=_client() )
        with patch( "os.path.exists", return_value=True ):
            out = _run( r.render( "icon", "a small gear icon", output_dir="/o" ) )
        assert out.startswith( "![a small gear icon]" )

    def test_exception_debug( self, capsys ):
        c = MagicMock()
        c.generate_image = AsyncMock( side_effect=RuntimeError( "gemini down" ) )
        r = NanoBananaRenderer( gemini_client=c, debug=True )
        assert _run( r.render( "hero_image", "x", output_dir="/o" ) ) is None
        assert "[NanoBananaRenderer] Exception" in capsys.readouterr().out

    def test_supported_types( self ):
        assert "hero_image" in NanoBananaRenderer.SUPPORTED_TYPES
        assert "icon_only" in NanoBananaRenderer.SUPPORTED_TYPES


if __name__ == "__main__":
    pytest.main( [ __file__, "-v" ] )
