#!/usr/bin/env python3
"""
Matplotlib Chart Generation Prompts for Presentation Generator.

System prompt and prompt builder for generating valid, self-contained
Python plotting code from natural-language chart descriptions. Used by
MatplotlibRenderer during Phase 7 (Visual Rendering).

Pattern: Same 3-part structure as visual.py (Mermaid prompts)
  - Chart type hint constants
  - System prompt constant
  - Prompt builder function
"""


# =============================================================================
# Chart Type Hints
# =============================================================================

MATPLOTLIB_CHART_TYPE_HINTS = {
    "bar"          : "bar chart",
    "column"       : "bar chart",
    "comparison"   : "bar chart",
    "rank"         : "bar chart",
    "line"         : "line chart",
    "trend"        : "line chart",
    "time series"  : "line chart",
    "growth"       : "line chart",
    "over time"    : "line chart",
    "scatter"      : "scatter plot",
    "correlation"  : "scatter plot",
    "relationship" : "scatter plot",
    "pie"          : "pie chart",
    "proportion"   : "pie chart",
    "share"        : "pie chart",
    "percentage"   : "pie chart",
    "distribution" : "histogram",
    "histogram"    : "histogram",
    "frequency"    : "histogram",
    "heatmap"      : "heatmap",
    "matrix"       : "heatmap",
    "area"         : "stacked area chart",
    "stacked"      : "stacked area chart",
    "box"          : "box plot",
    "boxplot"      : "box plot",
    "spread"       : "box plot",
    "radar"        : "radar chart",
    "spider"       : "radar chart",
}

DEFAULT_CHART_TYPE = "bar chart"


# =============================================================================
# System Prompt
# =============================================================================

MATPLOTLIB_SYSTEM_PROMPT = """You are a Python data visualization expert generating charts for presentation slides.

RULES:
1. Output ONLY valid Python code inside a ```python code block
2. Do NOT include any explanation, commentary, or text before or after the code block
3. Always import matplotlib.pyplot as plt at the top of the code
4. You may import seaborn as sns for styling (e.g., sns.set_theme(style='whitegrid'))
5. You may import numpy as np if needed for data generation
6. Do NOT call plt.show() — the chart will be saved to a file automatically
7. Do NOT call plt.savefig() — it will be injected automatically
8. Generate realistic, representative sample data when specific data is not provided
9. Keep charts clean and readable:
   - Maximum 6 data series per chart
   - Use clear, descriptive axis labels and a concise title
   - Use legible font sizes (title: 14pt, labels: 12pt, ticks: 10pt)
   - Include a legend when multiple series are present
10. Use a clean visual style — prefer seaborn whitegrid or default matplotlib style
11. Set figure size to (10, 6) for standard charts, (8, 8) for pie/radar charts

FORMATTING:
- Use descriptive variable names
- Add comments only for non-obvious data choices
- Colors should be accessible (avoid red/green only palettes)

OUTPUT FORMAT:
```python
import matplotlib.pyplot as plt
import seaborn as sns
# ... your plotting code here
```"""


# =============================================================================
# Prompt Builder
# =============================================================================

def get_matplotlib_prompt( visual_type: str, visual_description: str, slide_title: str = "" ) -> str:
    """
    Build user message for Matplotlib chart code generation.

    Requires:
        - visual_type is a string (e.g., "chart", "plot", "graph", "data_viz")
        - visual_description is a non-empty string

    Ensures:
        - Returns a prompt string with context and chart type hint

    Returns:
        str: User message for Claude API
    """
    suggested_type = _suggest_chart_type( visual_description )

    parts = []

    if slide_title:
        parts.append( f"Slide title: {slide_title}" )

    parts.append( f"Visual type: {visual_type}" )
    parts.append( f"Suggested chart type: {suggested_type}" )
    parts.append( f"\nDescription:\n{visual_description}" )
    parts.append( "\nGenerate Python code using matplotlib to create this chart. Output ONLY the python code block." )

    return "\n".join( parts )


def _suggest_chart_type( description: str ) -> str:
    """
    Suggest a chart type based on keywords in the description.

    Requires:
        - description is a string (may be empty or None)

    Ensures:
        - Returns a human-readable chart type string

    Returns:
        str: Chart type suggestion (e.g., "bar chart", "line chart")
    """
    if not description:
        return DEFAULT_CHART_TYPE

    description_lower = description.lower()

    for keyword, chart_type in MATPLOTLIB_CHART_TYPE_HINTS.items():
        if keyword in description_lower:
            return chart_type

    return DEFAULT_CHART_TYPE


# =============================================================================
# Smoke Test
# =============================================================================

def quick_smoke_test():
    """Quick smoke test for matplotlib prompts."""

    print( "=" * 60 )
    print( "Matplotlib Prompts Smoke Test" )
    print( "=" * 60 )

    try:
        # Test 1: System prompt exists and has key content
        print( "\nTest 1: System prompt..." )
        assert "matplotlib" in MATPLOTLIB_SYSTEM_PROMPT.lower()
        assert "```python" in MATPLOTLIB_SYSTEM_PROMPT
        assert "plt.show()" in MATPLOTLIB_SYSTEM_PROMPT
        assert "seaborn" in MATPLOTLIB_SYSTEM_PROMPT.lower()
        print( "  PASS" )

        # Test 2: Prompt builder
        print( "\nTest 2: Prompt builder..." )
        prompt = get_matplotlib_prompt(
            visual_type        = "chart",
            visual_description = "Bar chart comparing Q1 vs Q2 revenue across regions",
            slide_title        = "Revenue Comparison",
        )
        assert "Revenue Comparison" in prompt
        assert "bar chart" in prompt.lower()
        assert "chart" in prompt
        print( "  PASS" )

        # Test 3: Chart type hints
        print( "\nTest 3: Chart type suggestion..." )
        assert _suggest_chart_type( "line chart showing growth over time" ) == "line chart"
        assert _suggest_chart_type( "pie chart of market share" ) == "pie chart"
        assert _suggest_chart_type( "scatter plot showing correlation" ) == "scatter plot"
        assert _suggest_chart_type( "heatmap of values" ) == "heatmap"
        assert _suggest_chart_type( "something unknown" ) == DEFAULT_CHART_TYPE
        print( "  PASS" )

        # Test 4: Empty description
        print( "\nTest 4: Empty description..." )
        assert _suggest_chart_type( "" ) == DEFAULT_CHART_TYPE
        assert _suggest_chart_type( None ) == DEFAULT_CHART_TYPE
        print( "  PASS" )

        print( f"\n{'=' * 60}" )
        print( "All matplotlib prompt smoke tests passed" )
        print( f"{'=' * 60}" )

    except Exception as e:
        print( f"\nSmoke test FAILED: {e}" )
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    quick_smoke_test()
