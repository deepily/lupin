#!/usr/bin/env python3
"""
Unit tests for renderers/mermaid.py

LLM-backed Mermaid renderer. The only boundary is the injected api_client
(mocked AsyncMock) — no real Claude call. _extract_mermaid is pure regex.
"""

import asyncio
from unittest.mock import MagicMock, AsyncMock

import pytest

from cosa.agents.presentation_generator.renderers.mermaid import MermaidRenderer


def _run( coro ):
    return asyncio.run( coro )


def _client( content="```mermaid\nflowchart TD\n  A --> B\n```" ):
    client = MagicMock()
    resp = MagicMock()
    resp.content = content
    client.call_for_mermaid = AsyncMock( return_value=resp )
    return client


class TestExtractMermaid:
    def test_fenced_labelled( self ):
        out = MermaidRenderer._extract_mermaid( "```mermaid\nflowchart TD\n A-->B\n```" )
        assert "flowchart TD" in out and "```" not in out

    def test_fenced_bare( self ):
        out = MermaidRenderer._extract_mermaid( "intro\n```\nsequenceDiagram\n A->>B: hi\n```" )
        assert "sequenceDiagram" in out

    def test_bare_directive( self ):
        out = MermaidRenderer._extract_mermaid( "pie\n title D\n \"A\" : 60" )
        assert out.startswith( "pie" )

    def test_no_match( self ):
        assert MermaidRenderer._extract_mermaid( "plain text, no diagram" ) is None

    def test_empty_and_none( self ):
        assert MermaidRenderer._extract_mermaid( "" ) is None
        assert MermaidRenderer._extract_mermaid( None ) is None


class TestRender:
    def test_no_api_client_returns_none( self ):
        assert _run( MermaidRenderer().render( "diagram", "a flow" ) ) is None

    def test_success_debug( self, capsys ):
        r = MermaidRenderer( debug=True )
        out = _run( r.render( "diagram", "a flow", api_client=_client(), slide_title="My Slide" ) )
        assert out.startswith( "```mermaid\n" ) and out.endswith( "\n```" )
        assert "flowchart TD" in out
        assert "[MermaidRenderer] Generated" in capsys.readouterr().out

    def test_extract_returns_none( self ):
        # API responds with no extractable mermaid → render returns None
        r = MermaidRenderer()
        out = _run( r.render( "diagram", "x", api_client=_client( content="no diagram here" ) ) )
        assert out is None

    def test_api_exception_returns_none( self ):
        client = MagicMock()
        client.call_for_mermaid = AsyncMock( side_effect=RuntimeError( "api down" ) )
        assert _run( MermaidRenderer().render( "diagram", "x", api_client=client ) ) is None

    def test_supported_types( self ):
        assert MermaidRenderer.SUPPORTED_TYPES == [ "diagram" ]


if __name__ == "__main__":
    pytest.main( [ __file__, "-v" ] )
