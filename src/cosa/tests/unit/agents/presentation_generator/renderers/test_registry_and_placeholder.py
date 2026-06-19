#!/usr/bin/env python3
"""
Unit tests for renderers/visual_registry.py + renderers/placeholder.py

VisualRenderer ABC, VisualRendererRegistry dispatch, and the always-succeeds
PlaceholderRenderer. Pure in-memory — no external boundaries.
"""

import asyncio

import pytest

from cosa.agents.presentation_generator.renderers.visual_registry import (
    VisualRenderer,
    VisualRendererRegistry,
)
from cosa.agents.presentation_generator.renderers.placeholder import PlaceholderRenderer


def _run( coro ):
    return asyncio.run( coro )


class _Mock( VisualRenderer ):
    SUPPORTED_TYPES = [ "mock_type", "other_type" ]
    async def render( self, visual_type, visual_description, **kwargs ):
        return f"MOCK: {visual_description}"


class _Fallback( VisualRenderer ):
    SUPPORTED_TYPES = []
    async def render( self, visual_type, visual_description, **kwargs ):
        return f"FALLBACK: {visual_type}"


class TestVisualRendererABC:
    def test_cannot_instantiate_abstract( self ):
        with pytest.raises( TypeError ):
            VisualRenderer()

    def test_concrete_subclass_render( self ):
        assert _run( _Mock().render( "mock_type", "desc" ) ) == "MOCK: desc"


class TestRegistry:
    def test_register_and_get_debug( self, capsys ):
        reg = VisualRendererRegistry( fallback=_Fallback(), debug=True )
        mock = _Mock()
        reg.register( mock )
        out = capsys.readouterr().out
        assert "Registered: mock_type" in out
        assert reg.get( "mock_type" ) is mock
        assert reg.get( "other_type" ) is mock

    def test_get_fallback_debug_print( self, capsys ):
        fb = _Fallback()
        reg = VisualRendererRegistry( fallback=fb, debug=True )
        reg.register( _Mock() )
        capsys.readouterr()   # clear registration output
        assert reg.get( "unknown" ) is fb
        assert "Fallback for: unknown" in capsys.readouterr().out

    def test_get_fallback_no_debug_silent( self, capsys ):
        fb = _Fallback()
        reg = VisualRendererRegistry( fallback=fb, debug=False )
        reg.register( _Mock() )
        assert reg.get( "unknown" ) is fb
        assert capsys.readouterr().out == ""

    def test_registered_types( self ):
        reg = VisualRendererRegistry( fallback=_Fallback() )
        reg.register( _Mock() )
        assert reg.registered_types == [ "mock_type", "other_type" ]


class TestPlaceholderRenderer:
    def test_supported_types( self ):
        assert PlaceholderRenderer.SUPPORTED_TYPES == [ "screenshot" ]

    def test_render_with_description( self ):
        r = _run( PlaceholderRenderer().render( "screenshot", "UI dashboard" ) )
        assert r == "> **[TODO: screenshot]** UI dashboard"

    def test_render_none_description( self ):
        r = _run( PlaceholderRenderer().render( "icon_only", None ) )
        assert "(no description provided)" in r

    def test_render_empty_description_never_none( self ):
        r = _run( PlaceholderRenderer().render( "x", "" ) )
        assert r is not None
        assert "(no description provided)" in r


if __name__ == "__main__":
    pytest.main( [ __file__, "-v" ] )
