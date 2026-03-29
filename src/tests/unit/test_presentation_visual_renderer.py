#!/usr/bin/env python3
"""
Unit tests for Phase 7 Visual Rendering — Mermaid + Registry.

Tests cover:
    - VisualRenderer ABC (cannot instantiate, subclass protocol)
    - PlaceholderRenderer (output format, None handling, always succeeds)
    - VisualRendererRegistry (dispatch, fallback, registration)
    - MermaidRenderer._extract_mermaid (fenced, bare, edge cases)
    - MermaidRenderer.render (mocked API, error handling)
    - Mermaid prompts (system prompt, prompt builder, type hints)
    - Orchestrator integration (placeholder regex, registry building)
"""

import asyncio
import re
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from cosa.agents.presentation_generator.renderers.visual_registry import (
    VisualRenderer,
    VisualRendererRegistry,
)
from cosa.agents.presentation_generator.renderers.placeholder import PlaceholderRenderer
from cosa.agents.presentation_generator.renderers.mermaid import MermaidRenderer
from cosa.agents.presentation_generator.prompts.visual import (
    MERMAID_SYSTEM_PROMPT,
    MERMAID_DIAGRAM_TYPE_HINTS,
    DEFAULT_DIAGRAM_TYPE,
    get_mermaid_prompt,
    _suggest_diagram_type,
)


# =============================================================================
# TestVisualRendererABC
# =============================================================================

class TestVisualRendererABC:
    """Tests for the abstract base class protocol."""

    def test_abc_cannot_instantiate( self ):
        """VisualRenderer cannot be instantiated directly."""
        with pytest.raises( TypeError ):
            VisualRenderer()

    def test_abc_subclass_must_implement_render( self ):
        """Subclass without render() raises TypeError."""
        class IncompleteRenderer( VisualRenderer ):
            SUPPORTED_TYPES = [ "test" ]

        with pytest.raises( TypeError ):
            IncompleteRenderer()

    def test_abc_subclass_with_render( self ):
        """Subclass with render() can be instantiated."""
        class CompleteRenderer( VisualRenderer ):
            SUPPORTED_TYPES = [ "test" ]
            async def render( self, visual_type, visual_description, **kwargs ):
                return "rendered"

        renderer = CompleteRenderer()
        assert renderer.SUPPORTED_TYPES == [ "test" ]


# =============================================================================
# TestPlaceholderRenderer
# =============================================================================

class TestPlaceholderRenderer:
    """Tests for the fallback placeholder renderer."""

    def test_placeholder_output_format( self ):
        renderer = PlaceholderRenderer()
        result   = asyncio.run( renderer.render( "screenshot", "Dashboard with metrics" ) )
        assert result == '> **[TODO: screenshot]** Dashboard with metrics'

    def test_placeholder_supported_types( self ):
        assert "screenshot" in PlaceholderRenderer.SUPPORTED_TYPES
        assert "icon_only" in PlaceholderRenderer.SUPPORTED_TYPES
        assert "before_after" in PlaceholderRenderer.SUPPORTED_TYPES

    def test_placeholder_none_description( self ):
        renderer = PlaceholderRenderer()
        result   = asyncio.run( renderer.render( "icon_only", None ) )
        assert "(no description provided)" in result

    def test_placeholder_empty_description( self ):
        renderer = PlaceholderRenderer()
        result   = asyncio.run( renderer.render( "icon_only", "" ) )
        assert "(no description provided)" in result

    def test_placeholder_never_returns_none( self ):
        renderer = PlaceholderRenderer()
        result   = asyncio.run( renderer.render( "unknown_type", "anything" ) )
        assert result is not None
        assert isinstance( result, str )

    def test_placeholder_unknown_type_works( self ):
        """PlaceholderRenderer works with any visual_type, not just SUPPORTED_TYPES."""
        renderer = PlaceholderRenderer()
        result   = asyncio.run( renderer.render( "hologram", "3D projection" ) )
        assert "hologram" in result
        assert "3D projection" in result


# =============================================================================
# TestVisualRendererRegistry
# =============================================================================

class TestVisualRendererRegistry:
    """Tests for the type dispatch registry."""

    def test_registry_get_registered_type( self ):
        fallback = PlaceholderRenderer()
        registry = VisualRendererRegistry( fallback=fallback )
        mermaid  = MermaidRenderer()
        registry.register( mermaid )

        assert registry.get( "diagram" ) is mermaid
        assert registry.get( "chart" ) is mermaid

    def test_registry_get_unregistered_type( self ):
        fallback = PlaceholderRenderer()
        registry = VisualRendererRegistry( fallback=fallback )

        result = registry.get( "unknown_type" )
        assert isinstance( result, PlaceholderRenderer )

    def test_registry_register_multiple( self ):
        fallback = PlaceholderRenderer()
        registry = VisualRendererRegistry( fallback=fallback )
        mermaid  = MermaidRenderer()
        registry.register( mermaid )

        # MermaidRenderer registers both "diagram" and "chart"
        assert "diagram" in registry.registered_types
        assert "chart" in registry.registered_types

    def test_registry_registered_types_list( self ):
        fallback = PlaceholderRenderer()
        registry = VisualRendererRegistry( fallback=fallback )
        assert registry.registered_types == []

        mermaid = MermaidRenderer()
        registry.register( mermaid )
        assert len( registry.registered_types ) == 2

    def test_registry_fallback_is_never_none( self ):
        fallback = PlaceholderRenderer()
        registry = VisualRendererRegistry( fallback=fallback )

        result = registry.get( "totally_nonexistent_type" )
        assert result is not None

    def test_registry_placeholder_also_registered( self ):
        """PlaceholderRenderer can be both fallback AND registered for specific types."""
        fallback = PlaceholderRenderer()
        registry = VisualRendererRegistry( fallback=fallback )
        registry.register( fallback )

        assert registry.get( "screenshot" ) is fallback
        assert registry.get( "icon_only" ) is fallback


# =============================================================================
# TestMermaidExtraction
# =============================================================================

class TestMermaidExtraction:
    """Tests for MermaidRenderer._extract_mermaid static method."""

    def test_extract_fenced_mermaid( self ):
        content = "```mermaid\nflowchart TD\n    A[Start] --> B[End]\n```"
        result  = MermaidRenderer._extract_mermaid( content )
        assert result is not None
        assert "flowchart TD" in result
        assert "```" not in result

    def test_extract_bare_fenced( self ):
        content = "Here is the diagram:\n```\nsequenceDiagram\n    A->>B: Hello\n```"
        result  = MermaidRenderer._extract_mermaid( content )
        assert result is not None
        assert "sequenceDiagram" in result

    def test_extract_bare_flowchart( self ):
        content = "flowchart LR\n    A[Input] --> B[Process] --> C[Output]"
        result  = MermaidRenderer._extract_mermaid( content )
        assert result is not None
        assert "flowchart LR" in result

    def test_extract_bare_sequence( self ):
        content = "sequenceDiagram\n    Client->>Server: GET /api\n    Server-->>Client: 200 OK"
        result  = MermaidRenderer._extract_mermaid( content )
        assert result is not None
        assert "sequenceDiagram" in result

    def test_extract_bare_pie( self ):
        content = 'pie\n    title Distribution\n    "A" : 60\n    "B" : 40'
        result  = MermaidRenderer._extract_mermaid( content )
        assert result is not None
        assert "pie" in result

    def test_extract_no_mermaid( self ):
        result = MermaidRenderer._extract_mermaid( "Just some regular text without diagrams." )
        assert result is None

    def test_extract_empty_content( self ):
        assert MermaidRenderer._extract_mermaid( "" ) is None
        assert MermaidRenderer._extract_mermaid( None ) is None

    def test_extract_strips_whitespace( self ):
        content = "```mermaid\n\n  flowchart TD\n    A --> B\n\n```"
        result  = MermaidRenderer._extract_mermaid( content )
        assert result.startswith( "flowchart" )

    def test_extract_with_surrounding_text( self ):
        content = "Here's the diagram:\n\n```mermaid\ngraph TD\n    A --> B\n```\n\nThat's all."
        result  = MermaidRenderer._extract_mermaid( content )
        assert result is not None
        assert "graph TD" in result


# =============================================================================
# TestMermaidRendererMocked
# =============================================================================

class TestMermaidRendererMocked:
    """Tests for MermaidRenderer with mocked API client."""

    def test_render_returns_fenced_block( self ):
        """Successful render wraps output in ```mermaid ... ```."""
        renderer   = MermaidRenderer()
        api_client = AsyncMock()
        api_client.call_for_mermaid.return_value = MagicMock(
            content = "```mermaid\nflowchart TD\n    A --> B\n```"
        )

        result = asyncio.run( renderer.render(
            "diagram", "Flow from A to B",
            api_client=api_client, slide_title="Test"
        ) )

        assert result is not None
        assert result.startswith( "```mermaid" )
        assert result.endswith( "```" )
        assert "flowchart TD" in result

    def test_render_no_api_client_returns_none( self ):
        """Missing api_client → None."""
        renderer = MermaidRenderer()
        result   = asyncio.run( renderer.render( "diagram", "Some description" ) )
        assert result is None

    def test_render_api_error_returns_none( self ):
        """API exception → None (non-fatal)."""
        renderer   = MermaidRenderer()
        api_client = AsyncMock()
        api_client.call_for_mermaid.side_effect = Exception( "API error" )

        result = asyncio.run( renderer.render(
            "diagram", "Some description",
            api_client=api_client
        ) )
        assert result is None

    def test_render_no_mermaid_in_response_returns_none( self ):
        """Claude returns garbage → None."""
        renderer   = MermaidRenderer()
        api_client = AsyncMock()
        api_client.call_for_mermaid.return_value = MagicMock(
            content = "Sorry, I cannot generate that diagram."
        )

        result = asyncio.run( renderer.render(
            "diagram", "Some description",
            api_client=api_client
        ) )
        assert result is None

    def test_render_passes_slide_title( self ):
        """slide_title is forwarded to the prompt builder."""
        renderer   = MermaidRenderer()
        api_client = AsyncMock()
        api_client.call_for_mermaid.return_value = MagicMock(
            content = "```mermaid\nflowchart TD\n    A --> B\n```"
        )

        asyncio.run( renderer.render(
            "diagram", "Flow description",
            api_client=api_client, slide_title="Cache Architecture"
        ) )

        # Verify the prompt was called (api_client.call_for_mermaid was invoked)
        api_client.call_for_mermaid.assert_called_once()
        call_kwargs = api_client.call_for_mermaid.call_args
        assert "Cache Architecture" in call_kwargs.kwargs.get( "user_message", "" ) or \
               "Cache Architecture" in str( call_kwargs )


# =============================================================================
# TestMermaidPrompt
# =============================================================================

class TestMermaidPrompt:
    """Tests for Mermaid prompt templates."""

    def test_system_prompt_mentions_mermaid( self ):
        assert "Mermaid" in MERMAID_SYSTEM_PROMPT
        assert "```mermaid" in MERMAID_SYSTEM_PROMPT

    def test_system_prompt_mentions_diagram_types( self ):
        assert "flowchart" in MERMAID_SYSTEM_PROMPT
        assert "sequenceDiagram" in MERMAID_SYSTEM_PROMPT
        assert "pie" in MERMAID_SYSTEM_PROMPT

    def test_prompt_includes_description( self ):
        prompt = get_mermaid_prompt( "diagram", "Three cache layers in sequence" )
        assert "Three cache layers in sequence" in prompt

    def test_prompt_includes_slide_title( self ):
        prompt = get_mermaid_prompt( "diagram", "Cache layers", slide_title="Cache Architecture" )
        assert "Cache Architecture" in prompt

    def test_prompt_includes_visual_type( self ):
        prompt = get_mermaid_prompt( "chart", "Usage breakdown" )
        assert "chart" in prompt

    def test_prompt_includes_suggested_type( self ):
        prompt = get_mermaid_prompt( "diagram", "data flow pipeline" )
        # "flow" keyword matches first → flowchart TD
        assert "flowchart TD" in prompt

    def test_diagram_type_hints_coverage( self ):
        """Key mapping entries exist."""
        assert MERMAID_DIAGRAM_TYPE_HINTS[ "flow" ] == "flowchart TD"
        assert MERMAID_DIAGRAM_TYPE_HINTS[ "sequence" ] == "sequenceDiagram"
        assert MERMAID_DIAGRAM_TYPE_HINTS[ "pie" ] == "pie"
        assert MERMAID_DIAGRAM_TYPE_HINTS[ "gantt" ] == "gantt"

    def test_suggest_diagram_type_default( self ):
        assert _suggest_diagram_type( "something unknown" ) == DEFAULT_DIAGRAM_TYPE
        assert _suggest_diagram_type( "" ) == DEFAULT_DIAGRAM_TYPE
        assert _suggest_diagram_type( None ) == DEFAULT_DIAGRAM_TYPE

    def test_suggest_diagram_type_keywords( self ):
        assert _suggest_diagram_type( "sequence of API requests" ) == "sequenceDiagram"
        assert _suggest_diagram_type( "data flow pipeline" ) == "flowchart TD"  # "flow" matches first
        assert _suggest_diagram_type( "deployment pipeline" ) == "flowchart LR"  # "pipeline" without "flow"
        assert _suggest_diagram_type( "class hierarchy" ) == "classDiagram"
        assert _suggest_diagram_type( "state machine lifecycle" ) == "stateDiagram-v2"


# =============================================================================
# TestOrchestratorVisualIntegration
# =============================================================================

class TestOrchestratorVisualIntegration:
    """Tests for orchestrator Phase 7 integration."""

    def test_placeholder_regex_finds_visuals( self ):
        """The regex pattern matches <!-- VISUAL: type | desc --> comments."""
        pattern = re.compile( r"<!-- VISUAL: (\S+) \| (.+?) -->" )
        test_content = '<!-- VISUAL: diagram | Flowchart showing cache layers -->'
        match = pattern.search( test_content )
        assert match is not None
        assert match.group( 1 ) == "diagram"
        assert match.group( 2 ) == "Flowchart showing cache layers"

    def test_placeholder_regex_multiple_matches( self ):
        """Pattern finds all placeholders in a multi-slide document."""
        pattern = re.compile( r"<!-- VISUAL: (\S+) \| (.+?) -->" )
        content = (
            "# Slide 1\n<!-- VISUAL: diagram | Flow A to B -->\n"
            "---\n# Slide 2\n<!-- VISUAL: chart | Pie chart of usage -->\n"
            "---\n# Slide 3\nNo visual here\n"
        )
        matches = list( pattern.finditer( content ) )
        assert len( matches ) == 2
        assert matches[ 0 ].group( 1 ) == "diagram"
        assert matches[ 1 ].group( 1 ) == "chart"

    def test_placeholder_regex_skips_presenter_notes( self ):
        """Pattern does not match regular HTML comments (presenter notes)."""
        pattern = re.compile( r"<!-- VISUAL: (\S+) \| (.+?) -->" )
        content = "<!--\nTransition: Moving on.\nTalking points:\n- Point 1\n-->"
        matches = list( pattern.finditer( content ) )
        assert len( matches ) == 0

    def test_build_visual_registry_normal( self ):
        """Normal mode registers MermaidRenderer."""
        from cosa.agents.presentation_generator.orchestrator import PresentationOrchestratorAgent
        from cosa.agents.presentation_generator.config import PresentationConfig

        agent = PresentationOrchestratorAgent(
            source_path = "/test/doc.md",
            user_id     = "test@test.com",
            config      = PresentationConfig(),
            dry_run     = False,
        )
        registry = agent._build_visual_registry()
        assert "diagram" in registry.registered_types
        assert "chart" in registry.registered_types

    def test_build_visual_registry_dry_run( self ):
        """Dry run mode does NOT register MermaidRenderer (no API calls)."""
        from cosa.agents.presentation_generator.orchestrator import PresentationOrchestratorAgent
        from cosa.agents.presentation_generator.config import PresentationConfig

        agent = PresentationOrchestratorAgent(
            source_path = "/test/doc.md",
            user_id     = "test@test.com",
            config      = PresentationConfig(),
            dry_run     = True,
        )
        registry = agent._build_visual_registry()
        assert registry.registered_types == []
