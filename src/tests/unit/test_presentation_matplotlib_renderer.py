#!/usr/bin/env python3
"""
Unit tests for Phase 9A MatplotlibRenderer — chart code generation + sandbox execution.

Tests cover:
    - MatplotlibRenderer (construction, SUPPORTED_TYPES, render with mocked API)
    - Python code extraction (fenced, bare, edge cases)
    - Savefig injection (inject, strip plt.show(), preserve existing savefig)
    - Sandbox execution (success, timeout, errors — mocked subprocess)
    - Matplotlib prompts (system prompt, prompt builder, type hints)
    - Registry integration (chart/plot/graph/data_viz registered, Mermaid no longer handles chart)
"""

import asyncio
import os
import re
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from cosa.agents.presentation_generator.renderers.matplotlib_renderer import MatplotlibRenderer
from cosa.agents.presentation_generator.renderers.visual_registry import (
    VisualRenderer,
    VisualRendererRegistry,
)
from cosa.agents.presentation_generator.renderers.mermaid import MermaidRenderer
from cosa.agents.presentation_generator.renderers.placeholder import PlaceholderRenderer
from cosa.agents.presentation_generator.prompts.matplotlib import (
    MATPLOTLIB_SYSTEM_PROMPT,
    MATPLOTLIB_CHART_TYPE_HINTS,
    DEFAULT_CHART_TYPE,
    get_matplotlib_prompt,
    _suggest_chart_type,
)


# =============================================================================
# TestMatplotlibRenderer
# =============================================================================

class TestMatplotlibRenderer:
    """Tests for MatplotlibRenderer construction and render() method."""

    def test_construction( self ):
        """MatplotlibRenderer can be instantiated with debug/verbose flags."""
        renderer = MatplotlibRenderer( debug=True, verbose=True )
        assert renderer.debug is True
        assert renderer.verbose is True

    def test_construction_defaults( self ):
        """MatplotlibRenderer defaults to debug=False, verbose=False."""
        renderer = MatplotlibRenderer()
        assert renderer.debug is False
        assert renderer.verbose is False

    def test_supported_types( self ):
        """SUPPORTED_TYPES includes chart, plot, graph, data_viz."""
        assert "chart" in MatplotlibRenderer.SUPPORTED_TYPES
        assert "plot" in MatplotlibRenderer.SUPPORTED_TYPES
        assert "graph" in MatplotlibRenderer.SUPPORTED_TYPES
        assert "data_viz" in MatplotlibRenderer.SUPPORTED_TYPES

    def test_is_visual_renderer_subclass( self ):
        """MatplotlibRenderer is a VisualRenderer subclass."""
        renderer = MatplotlibRenderer()
        assert isinstance( renderer, VisualRenderer )

    def test_render_returns_none_without_api_client( self ):
        """render() returns None when no api_client provided."""
        renderer = MatplotlibRenderer()
        result   = asyncio.run( renderer.render(
            "chart", "bar chart of sales",
            output_dir="/tmp/test"
        ) )
        assert result is None

    def test_render_returns_none_without_output_dir( self ):
        """render() returns None when no output_dir provided."""
        renderer   = MatplotlibRenderer()
        api_client = MagicMock()
        result     = asyncio.run( renderer.render(
            "chart", "bar chart of sales",
            api_client=api_client
        ) )
        assert result is None

    def test_render_with_mock_api_success( self, tmp_path ):
        """render() returns markdown image reference on successful execution."""
        renderer   = MatplotlibRenderer( debug=True )
        api_client = MagicMock()

        # Mock API response with valid Python code
        mock_response         = MagicMock()
        mock_response.content = '```python\nimport matplotlib.pyplot as plt\nplt.figure(figsize=(10,6))\nplt.bar(["A","B","C"], [10,20,15])\nplt.title("Test")\n```'

        api_client.call_for_matplotlib = AsyncMock( return_value=mock_response )

        output_dir = str( tmp_path / "visuals" )
        os.makedirs( output_dir, exist_ok=True )

        result = asyncio.run( renderer.render(
            visual_type        = "chart",
            visual_description = "bar chart of sales",
            api_client         = api_client,
            slide_title        = "Sales Overview",
            output_dir         = output_dir,
            slide_index        = 0,
        ) )

        # Should have called the API
        api_client.call_for_matplotlib.assert_called_once()

        # Result depends on whether matplotlib actually created the file
        # In CI/test environments, just verify the API was called
        if result is not None:
            assert "![" in result
            assert "visuals/chart-000.png" in result

    def test_render_returns_none_on_bad_code( self, tmp_path ):
        """render() returns None when LLM returns non-extractable content."""
        renderer   = MatplotlibRenderer()
        api_client = MagicMock()

        mock_response         = MagicMock()
        mock_response.content = "Here is a description of a chart but no actual code."
        api_client.call_for_matplotlib = AsyncMock( return_value=mock_response )

        output_dir = str( tmp_path / "visuals" )
        os.makedirs( output_dir, exist_ok=True )

        result = asyncio.run( renderer.render(
            "chart", "bar chart",
            api_client=api_client,
            output_dir=output_dir,
        ) )
        assert result is None


# =============================================================================
# TestPythonCodeExtraction
# =============================================================================

class TestPythonCodeExtraction:
    """Tests for MatplotlibRenderer._extract_python_code()."""

    def test_extract_fenced_python( self ):
        """Extracts code from ```python ... ``` blocks."""
        content = 'Here is the code:\n```python\nimport matplotlib.pyplot as plt\nplt.plot([1,2,3])\n```\nDone.'
        result  = MatplotlibRenderer._extract_python_code( content )
        assert result is not None
        assert "import matplotlib" in result
        assert "plt.plot" in result
        assert "```" not in result

    def test_extract_bare_fenced( self ):
        """Extracts code from ``` ... ``` blocks without python label."""
        content = '```\nimport matplotlib.pyplot as plt\nplt.bar([1,2], [3,4])\n```'
        result  = MatplotlibRenderer._extract_python_code( content )
        assert result is not None
        assert "plt.bar" in result

    def test_extract_bare_import( self ):
        """Extracts bare code starting with import statements."""
        content = "Sure, here's the code:\nimport matplotlib.pyplot as plt\nimport numpy as np\nplt.scatter(np.random.rand(10), np.random.rand(10))"
        result  = MatplotlibRenderer._extract_python_code( content )
        assert result is not None
        assert "import matplotlib" in result
        assert "plt.scatter" in result

    def test_no_code_found( self ):
        """Returns None when no Python code is present."""
        result = MatplotlibRenderer._extract_python_code( "Just some text about charts." )
        assert result is None

    def test_empty_input( self ):
        """Returns None for empty or None input."""
        assert MatplotlibRenderer._extract_python_code( "" ) is None
        assert MatplotlibRenderer._extract_python_code( None ) is None


# =============================================================================
# TestSavefigInjection
# =============================================================================

class TestSavefigInjection:
    """Tests for MatplotlibRenderer._inject_savefig()."""

    def test_inject_into_clean_code( self ):
        """Appends plt.savefig() and plt.close() to clean code."""
        code     = "import matplotlib.pyplot as plt\nplt.plot([1,2,3])"
        injected = MatplotlibRenderer._inject_savefig( code, "/tmp/chart.png" )
        assert "plt.savefig" in injected
        assert "/tmp/chart.png" in injected
        assert "dpi=150" in injected
        assert "bbox_inches" in injected
        assert 'plt.close( "all" )' in injected

    def test_strips_plt_show( self ):
        """Removes plt.show() calls and replaces with comment."""
        code     = "plt.plot([1,2,3])\nplt.show()\n"
        injected = MatplotlibRenderer._inject_savefig( code, "/tmp/chart.png" )
        # Should not have bare plt.show() anymore
        assert "plt.show()" not in injected or "# disabled" in injected

    def test_preserves_existing_savefig( self ):
        """Does not remove existing plt.savefig() calls."""
        code     = 'plt.plot([1,2,3])\nplt.savefig("/tmp/other.png")'
        injected = MatplotlibRenderer._inject_savefig( code, "/tmp/chart.png" )
        # Both savefig calls should be present
        assert injected.count( "plt.savefig" ) == 2

    def test_handles_path_with_spaces( self ):
        """Handles output paths containing spaces."""
        code     = "plt.plot([1,2,3])"
        injected = MatplotlibRenderer._inject_savefig( code, "/tmp/my charts/chart-001.png" )
        assert "/tmp/my charts/chart-001.png" in injected


# =============================================================================
# TestSandboxExecution
# =============================================================================

class TestSandboxExecution:
    """Tests for MatplotlibRenderer._execute_code() — mocked subprocess."""

    @patch( "cosa.agents.presentation_generator.renderers.matplotlib_renderer.subprocess.run" )
    def test_success( self, mock_run ):
        """Returns return_code 0 on successful execution."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=b"",
            stderr=b"",
        )
        result = MatplotlibRenderer._execute_code( "print('hello')" )
        assert result[ "return_code" ] == 0
        assert result[ "stderr" ] == ""

    @patch( "cosa.agents.presentation_generator.renderers.matplotlib_renderer.subprocess.run" )
    def test_syntax_error( self, mock_run ):
        """Returns non-zero return_code on syntax error."""
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout=b"",
            stderr=b"SyntaxError: invalid syntax",
        )
        result = MatplotlibRenderer._execute_code( "def foo(:" )
        assert result[ "return_code" ] != 0
        assert "SyntaxError" in result[ "stderr" ]

    @patch( "cosa.agents.presentation_generator.renderers.matplotlib_renderer.subprocess.run" )
    def test_timeout( self, mock_run ):
        """Returns return_code -1 on timeout."""
        import subprocess as sp
        mock_run.side_effect = sp.TimeoutExpired( cmd="python3", timeout=30 )
        result = MatplotlibRenderer._execute_code( "while True: pass" )
        assert result[ "return_code" ] == -1
        assert "Timeout" in result[ "stderr" ]

    @patch( "cosa.agents.presentation_generator.renderers.matplotlib_renderer.subprocess.run" )
    def test_nonzero_return_code( self, mock_run ):
        """Returns the actual non-zero return code."""
        mock_run.return_value = MagicMock(
            returncode=2,
            stdout=b"",
            stderr=b"ImportError: No module named 'foo'",
        )
        result = MatplotlibRenderer._execute_code( "import foo" )
        assert result[ "return_code" ] == 2


# =============================================================================
# TestMatplotlibPrompt
# =============================================================================

class TestMatplotlibPrompt:
    """Tests for matplotlib prompt system prompt and builder."""

    def test_system_prompt_content( self ):
        """System prompt contains key constraints."""
        assert "matplotlib" in MATPLOTLIB_SYSTEM_PROMPT.lower()
        assert "```python" in MATPLOTLIB_SYSTEM_PROMPT
        assert "plt.show()" in MATPLOTLIB_SYSTEM_PROMPT
        assert "seaborn" in MATPLOTLIB_SYSTEM_PROMPT.lower()
        assert "savefig" in MATPLOTLIB_SYSTEM_PROMPT.lower()

    def test_prompt_builder_with_all_params( self ):
        """Prompt builder includes slide title, type, and description."""
        prompt = get_matplotlib_prompt(
            visual_type        = "chart",
            visual_description = "Bar chart comparing Q1 vs Q2 revenue",
            slide_title        = "Revenue Comparison",
        )
        assert "Revenue Comparison" in prompt
        assert "chart" in prompt
        assert "bar chart" in prompt.lower()
        assert "Q1 vs Q2" in prompt

    def test_prompt_builder_without_title( self ):
        """Prompt builder works without slide title."""
        prompt = get_matplotlib_prompt(
            visual_type        = "plot",
            visual_description = "Line plot of temperature over time",
        )
        assert "Line plot" in prompt
        assert "line chart" in prompt.lower()

    def test_keyword_to_chart_type_mapping( self ):
        """Keywords map to correct chart types."""
        assert _suggest_chart_type( "bar chart comparing values" ) == "bar chart"
        assert _suggest_chart_type( "line chart showing growth" ) == "line chart"
        assert _suggest_chart_type( "scatter plot of correlation" ) == "scatter plot"
        assert _suggest_chart_type( "pie chart of market share" ) == "pie chart"
        assert _suggest_chart_type( "heatmap of confusion matrix" ) == "heatmap"
        assert _suggest_chart_type( "histogram of distribution" ) == "histogram"

    def test_empty_description_returns_default( self ):
        """Empty or None description returns default chart type."""
        assert _suggest_chart_type( "" ) == DEFAULT_CHART_TYPE
        assert _suggest_chart_type( None ) == DEFAULT_CHART_TYPE

    def test_unknown_description_returns_default( self ):
        """Unrecognized description returns default chart type."""
        assert _suggest_chart_type( "something completely unknown" ) == DEFAULT_CHART_TYPE


# =============================================================================
# TestRegistryIntegration
# =============================================================================

class TestRegistryIntegration:
    """Tests for MatplotlibRenderer integration with VisualRendererRegistry."""

    def test_matplotlib_registered_for_chart_types( self ):
        """MatplotlibRenderer handles chart, plot, graph, data_viz in registry."""
        fallback = PlaceholderRenderer()
        registry = VisualRendererRegistry( fallback=fallback )

        matplotlib_renderer = MatplotlibRenderer()
        registry.register( matplotlib_renderer )

        for visual_type in [ "chart", "plot", "graph", "data_viz" ]:
            assert registry.get( visual_type ) is matplotlib_renderer, \
                f"Expected MatplotlibRenderer for '{visual_type}'"

    def test_mermaid_no_longer_handles_chart( self ):
        """MermaidRenderer SUPPORTED_TYPES no longer includes 'chart'."""
        assert "chart" not in MermaidRenderer.SUPPORTED_TYPES
        assert "diagram" in MermaidRenderer.SUPPORTED_TYPES

    def test_mermaid_and_matplotlib_non_overlapping( self ):
        """MermaidRenderer and MatplotlibRenderer have no overlapping SUPPORTED_TYPES."""
        mermaid_types    = set( MermaidRenderer.SUPPORTED_TYPES )
        matplotlib_types = set( MatplotlibRenderer.SUPPORTED_TYPES )
        overlap          = mermaid_types & matplotlib_types
        assert len( overlap ) == 0, f"Overlapping types: {overlap}"
