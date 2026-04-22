#!/usr/bin/env python3
"""
Unit tests for D2Renderer — Phase 9B Visual Rendering.

Tests cover:
    - D2Renderer construction and configuration
    - D2 code extraction from various response formats
    - D2 CLI execution (mocked subprocess)
    - Full render integration (mocked API + CLI)
    - D2 prompt module (system prompt, builder, pattern hints)
    - Registry integration (dispatch for flowchart_d2/architecture)
"""

import asyncio
import os
import re
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from cosa.agents.presentation_generator.renderers.d2_renderer import D2Renderer
from cosa.agents.presentation_generator.renderers.visual_registry import (
    VisualRendererRegistry,
)
from cosa.agents.presentation_generator.renderers.placeholder import PlaceholderRenderer
from cosa.agents.presentation_generator.prompts.d2 import (
    D2_SYSTEM_PROMPT,
    D2_DIAGRAM_PATTERN_HINTS,
    DEFAULT_D2_PATTERN,
    get_d2_prompt,
    _suggest_d2_pattern,
)


# =============================================================================
# TestD2Renderer
# =============================================================================

class TestD2Renderer:
    """Tests for D2Renderer construction and configuration."""

    def test_construction_defaults( self ):
        """D2Renderer initializes with default values."""
        renderer = D2Renderer()
        assert renderer.debug is False
        assert renderer.verbose is False
        assert renderer.d2_theme == 0
        assert renderer._d2_available is None

    def test_construction_with_params( self ):
        """D2Renderer accepts debug, verbose, d2_theme."""
        renderer = D2Renderer( debug=True, verbose=True, d2_theme=100 )
        assert renderer.debug is True
        assert renderer.verbose is True
        assert renderer.d2_theme == 100

    def test_supported_types( self ):
        """D2Renderer handles flowchart_d2 and architecture."""
        assert "flowchart_d2" in D2Renderer.SUPPORTED_TYPES
        assert "architecture" in D2Renderer.SUPPORTED_TYPES
        assert len( D2Renderer.SUPPORTED_TYPES ) == 2

    @patch( "shutil.which", return_value="/usr/local/bin/d2" )
    def test_d2_available_cached( self, mock_which ):
        """CLI check is cached after first call."""
        renderer = D2Renderer()
        assert renderer._check_d2_available() is True
        assert renderer._check_d2_available() is True
        # shutil.which should only be called once (cached)
        mock_which.assert_called_once_with( "d2" )


# =============================================================================
# TestD2CodeExtraction
# =============================================================================

class TestD2CodeExtraction:
    """Tests for _extract_d2_code static method."""

    def test_fenced_d2_block( self ):
        """Extract code from ```d2 ... ``` block."""
        content = 'Here is the diagram:\n```d2\na -> b -> c\nb -> d\n```'
        result  = D2Renderer._extract_d2_code( content )
        assert result is not None
        assert "a -> b -> c" in result
        assert "b -> d" in result
        assert "```" not in result

    def test_bare_fenced_block( self ):
        """Extract code from ``` ... ``` block without d2 label."""
        content = 'Diagram:\n```\nserver -> database: query\ndatabase -> server: result\n```'
        result  = D2Renderer._extract_d2_code( content )
        assert result is not None
        assert "server -> database" in result

    def test_markdown_wrapped( self ):
        """Extract code from response with surrounding markdown text."""
        content = (
            "Here is the architecture diagram:\n\n"
            "```d2\n"
            "api_gateway -> auth_service\n"
            "api_gateway -> user_service\n"
            "auth_service -> database\n"
            "```\n\n"
            "This shows the main service connections."
        )
        result = D2Renderer._extract_d2_code( content )
        assert result is not None
        assert "api_gateway -> auth_service" in result
        assert "This shows" not in result

    def test_bare_d2_with_arrows( self ):
        """Extract bare D2 code containing arrow patterns."""
        content = "api_gateway -> auth_service -> database"
        result  = D2Renderer._extract_d2_code( content )
        assert result is not None
        assert "api_gateway" in result

    def test_empty_and_none( self ):
        """Returns None for empty or None content."""
        assert D2Renderer._extract_d2_code( "" ) is None
        assert D2Renderer._extract_d2_code( None ) is None

    def test_no_d2_found( self ):
        """Returns None when no D2 syntax is present."""
        result = D2Renderer._extract_d2_code( "Just some regular text about architecture." )
        assert result is None


# =============================================================================
# TestD2CLIExecution
# =============================================================================

class TestD2CLIExecution:
    """Tests for _render_d2 async method (mocked subprocess)."""

    def test_successful_render( self, tmp_path ):
        """Successful d2 CLI execution creates SVG file."""
        renderer    = D2Renderer()
        output_path = str( tmp_path / "test.svg" )

        mock_result             = MagicMock()
        mock_result.returncode  = 0
        mock_result.stderr      = ""

        with patch( "subprocess.run", return_value=mock_result ):
            # Create the file to simulate d2 output
            with open( output_path, "w" ) as f:
                f.write( "<svg></svg>" )

            result = asyncio.run( renderer._render_d2( "a -> b", output_path ) )

        assert result is True

    def test_d2_not_found( self ):
        """Returns None when d2 CLI is not installed."""
        renderer = D2Renderer()

        with patch( "shutil.which", return_value=None ):
            result = asyncio.run( renderer.render(
                "architecture", "test description",
                api_client=MagicMock(), output_dir="/tmp"
            ) )

        assert result is None

    def test_d2_syntax_error( self, tmp_path ):
        """Returns False when d2 reports a syntax error."""
        renderer    = D2Renderer()
        output_path = str( tmp_path / "test.svg" )

        mock_result             = MagicMock()
        mock_result.returncode  = 1
        mock_result.stderr      = "error: invalid syntax at line 3"

        with patch( "subprocess.run", return_value=mock_result ):
            result = asyncio.run( renderer._render_d2( "invalid { syntax", output_path ) )

        assert result is False

    def test_d2_timeout( self, tmp_path ):
        """Returns False when d2 CLI exceeds timeout."""
        import subprocess as sp
        renderer    = D2Renderer()
        output_path = str( tmp_path / "test.svg" )

        with patch( "subprocess.run", side_effect=sp.TimeoutExpired( "d2", 30 ) ):
            result = asyncio.run( renderer._render_d2( "a -> b", output_path ) )

        assert result is False

    def test_stderr_logged_on_failure( self, tmp_path, caplog ):
        """Stderr is logged when d2 CLI fails."""
        import logging
        renderer    = D2Renderer()
        output_path = str( tmp_path / "test.svg" )

        mock_result             = MagicMock()
        mock_result.returncode  = 1
        mock_result.stderr      = "error: unexpected token at line 5"

        with caplog.at_level( logging.WARNING ):
            with patch( "subprocess.run", return_value=mock_result ):
                asyncio.run( renderer._render_d2( "bad code", output_path ) )

        assert "D2 CLI failed" in caplog.text


# =============================================================================
# TestD2RenderIntegration
# =============================================================================

class TestD2RenderIntegration:
    """Tests for full render() flow with mocked API and CLI."""

    def test_full_render_success( self, tmp_path ):
        """Full render: mock API → extract → mock CLI → markdown ref."""
        renderer = D2Renderer( debug=True )
        renderer._d2_available = True  # Skip CLI check

        output_dir = str( tmp_path / "visuals" )

        # Mock API client
        mock_response         = MagicMock()
        mock_response.content = '```d2\napi -> service -> db\n```'
        mock_api              = AsyncMock()
        mock_api.call_for_d2  = AsyncMock( return_value=mock_response )

        # Mock subprocess (d2 CLI) — create the file to simulate output
        mock_result            = MagicMock()
        mock_result.returncode = 0
        mock_result.stderr     = ""

        def fake_subprocess_run( *args, **kwargs ):
            # Simulate d2 writing the SVG
            out_path = args[ 0 ][ -1 ] if args else kwargs.get( "args", [] )[ -1 ]
            os.makedirs( os.path.dirname( out_path ), exist_ok=True )
            with open( out_path, "w" ) as f:
                f.write( "<svg>diagram</svg>" )
            return mock_result

        with patch( "subprocess.run", side_effect=fake_subprocess_run ):
            result = asyncio.run( renderer.render(
                visual_type        = "architecture",
                visual_description = "API gateway with auth and database",
                api_client         = mock_api,
                slide_title        = "System Architecture",
                output_dir         = output_dir,
                slide_index        = 3,
            ) )

        assert result is not None
        assert "![System Architecture]" in result
        assert "visuals/diagram-003.svg" in result
        mock_api.call_for_d2.assert_awaited_once()

    def test_render_missing_api_client( self ):
        """Returns None when api_client is not provided."""
        renderer = D2Renderer()
        renderer._d2_available = True

        result = asyncio.run( renderer.render(
            "architecture", "test",
            output_dir="/tmp"
        ) )
        assert result is None

    def test_render_missing_output_dir( self ):
        """Returns None when output_dir is not provided."""
        renderer = D2Renderer()
        renderer._d2_available = True

        result = asyncio.run( renderer.render(
            "flowchart_d2", "test",
            api_client=MagicMock()
        ) )
        assert result is None

    def test_render_d2_unavailable( self ):
        """Returns None when d2 CLI is not installed."""
        renderer = D2Renderer()
        renderer._d2_available = False

        result = asyncio.run( renderer.render(
            "architecture", "test",
            api_client=MagicMock(), output_dir="/tmp"
        ) )
        assert result is None


# =============================================================================
# TestD2Prompts
# =============================================================================

class TestD2Prompts:
    """Tests for the D2 prompt module."""

    def test_system_prompt_contains_d2_rules( self ):
        """System prompt mentions D2, containers, and output format."""
        assert "D2" in D2_SYSTEM_PROMPT
        assert "```d2" in D2_SYSTEM_PROMPT
        assert "container" in D2_SYSTEM_PROMPT.lower()
        assert "->" in D2_SYSTEM_PROMPT

    def test_prompt_builder_output( self ):
        """Prompt builder includes slide title, visual type, and description."""
        prompt = get_d2_prompt(
            visual_type        = "architecture",
            visual_description = "Microservice architecture with API gateway, auth service, and database",
            slide_title        = "System Architecture",
        )
        assert "System Architecture" in prompt
        assert "architecture" in prompt
        assert "Microservice" in prompt
        assert "containers with nested components" in prompt

    def test_pattern_suggestion_keywords( self ):
        """Pattern hints map keywords to D2 patterns."""
        assert "sequence" in _suggest_d2_pattern( "sequence of API calls" )
        assert "containers" in _suggest_d2_pattern( "microservice architecture" )
        assert "left-to-right" in _suggest_d2_pattern( "data pipeline stages" )
        assert "tree" in _suggest_d2_pattern( "class hierarchy overview" )

    def test_pattern_suggestion_default( self ):
        """Unknown descriptions get default pattern."""
        assert _suggest_d2_pattern( "something unknown" ) == DEFAULT_D2_PATTERN
        assert _suggest_d2_pattern( "" ) == DEFAULT_D2_PATTERN
        assert _suggest_d2_pattern( None ) == DEFAULT_D2_PATTERN


# =============================================================================
# TestD2RegistryIntegration
# =============================================================================

class TestD2RegistryIntegration:
    """Tests for D2Renderer registration in VisualRendererRegistry."""

    def test_d2_registered_for_supported_types( self ):
        """D2Renderer registers for flowchart_d2 and architecture."""
        fallback = PlaceholderRenderer()
        registry = VisualRendererRegistry( fallback=fallback )

        d2 = D2Renderer()
        registry.register( d2 )

        assert registry.get( "flowchart_d2" ) is d2
        assert registry.get( "architecture" ) is d2

    def test_unknown_type_falls_back( self ):
        """Unknown types still fall back to PlaceholderRenderer."""
        fallback = PlaceholderRenderer()
        registry = VisualRendererRegistry( fallback=fallback )

        d2 = D2Renderer()
        registry.register( d2 )

        assert registry.get( "unknown_type" ) is fallback
