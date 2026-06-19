#!/usr/bin/env python3
"""
Mermaid Renderer — LLM-backed diagram code generation.

Calls Claude API with a natural-language visual description, extracts
the Mermaid syntax from the response, and returns it as a fenced code
block. Marp renders Mermaid natively — no mermaid-cli needed.

Handles both "diagram" and "chart" visual types since Mermaid supports
flowcharts, sequence diagrams, pie charts, gantt charts, etc.
"""

import re
import logging
from typing import Optional

from .visual_registry import VisualRenderer

logger = logging.getLogger( __name__ )


class MermaidRenderer( VisualRenderer ):
    """
    LLM-backed renderer that generates Mermaid diagram code.

    Calls Claude API with a visual description, extracts the Mermaid
    syntax from the response, and wraps it in a fenced code block.

    Requires:
        - api_client is a PresentationAPIClient instance (passed via kwargs)

    Ensures:
        - Returns a ```mermaid code block on success
        - Returns None on API error (caller falls back to placeholder)
    """
    SUPPORTED_TYPES = [ "diagram" ]

    def __init__( self, debug: bool = False, verbose: bool = False ):
        """
        Initialize MermaidRenderer.

        Requires:
            - debug and verbose are booleans

        Ensures:
            - Renderer is ready to call render()
        """
        self.debug   = debug
        self.verbose = verbose

    async def render( self, visual_type: str, visual_description: str, **kwargs ) -> Optional[ str ]:
        """
        Generate Mermaid code from natural-language description via Claude API.

        Requires:
            - visual_type is "diagram" or "chart"
            - visual_description is a non-empty string
            - kwargs[ "api_client" ] is a PresentationAPIClient instance

        Ensures:
            - Returns fenced ```mermaid code block on success
            - Returns None on failure (non-fatal)

        kwargs:
            api_client: PresentationAPIClient (required)
            slide_title: str (optional, for context)

        Returns:
            str: Fenced mermaid code block, or None on failure
        """
        api_client  = kwargs.get( "api_client" )
        slide_title = kwargs.get( "slide_title", "" )

        if api_client is None:
            logger.warning( "MermaidRenderer: No api_client provided" )
            return None

        try:
            from ..prompts.visual import MERMAID_SYSTEM_PROMPT, get_mermaid_prompt

            prompt = get_mermaid_prompt(
                visual_type        = visual_type,
                visual_description = visual_description,
                slide_title        = slide_title,
            )

            response = await api_client.call_for_mermaid(
                system_prompt = MERMAID_SYSTEM_PROMPT,
                user_message  = prompt,
            )

            mermaid_code = self._extract_mermaid( response.content )
            if mermaid_code:
                if self.debug: print( f"[MermaidRenderer] Generated {len( mermaid_code )} chars for: {slide_title[ :40 ]}" )
                return f"```mermaid\n{mermaid_code}\n```"
            else:
                logger.warning( f"MermaidRenderer: Could not extract Mermaid from response for: {slide_title[ :40 ]}" )
                return None

        except Exception as e:
            logger.error( f"MermaidRenderer failed: {e}" )
            return None

    @staticmethod
    def _extract_mermaid( response_content: str ) -> Optional[ str ]:
        """
        Extract Mermaid code from Claude's response.

        Handles:
            - Fenced ```mermaid ... ``` blocks
            - Fenced ``` ... ``` blocks (no mermaid label)
            - Bare code starting with known Mermaid directives

        Requires:
            - response_content is a string

        Ensures:
            - Returns raw Mermaid code (no fences) on success
            - Returns None if no Mermaid found

        Returns:
            str: Raw Mermaid code, or None
        """
        if not response_content:
            return None

        # Try fenced block first (with or without "mermaid" label)
        match = re.search( r"```(?:mermaid)?\s*\n(.*?)```", response_content, re.DOTALL )
        if match:
            return match.group( 1 ).strip()

        # Try bare Mermaid (starts with known directive)
        mermaid_starts = [
            "graph ", "flowchart ", "sequenceDiagram", "classDiagram",
            "stateDiagram", "erDiagram", "gantt", "pie\n", "pie ", "gitgraph",
            "mindmap", "timeline", "quadrantChart", "xychart",
        ]
        for start in mermaid_starts:
            if start in response_content:
                idx = response_content.index( start )
                return response_content[ idx: ].strip()

        return None


# =============================================================================
# Smoke Test
# =============================================================================

def quick_smoke_test():
    """Quick smoke test for MermaidRenderer extraction logic."""

    print( "=" * 60 )
    print( "MermaidRenderer Smoke Test" )
    print( "=" * 60 )

    try:
        # Test 1: Extract fenced mermaid
        print( "\nTest 1: Extract fenced mermaid..." )
        content = '```mermaid\nflowchart TD\n    A[Start] --> B[End]\n```'
        result  = MermaidRenderer._extract_mermaid( content )
        assert result is not None
        assert "flowchart TD" in result
        assert "```" not in result
        print( "  PASS" )

        # Test 2: Extract bare fenced
        print( "\nTest 2: Extract bare fenced..." )
        content = 'Here is the diagram:\n```\nsequenceDiagram\n    A->>B: Hello\n```'
        result  = MermaidRenderer._extract_mermaid( content )
        assert result is not None
        assert "sequenceDiagram" in result
        print( "  PASS" )

        # Test 3: Extract bare directive
        print( "\nTest 3: Extract bare directive..." )
        content = "pie\n    title Distribution\n    \"A\" : 60\n    \"B\" : 40"
        result  = MermaidRenderer._extract_mermaid( content )
        assert result is not None
        assert "pie" in result
        print( "  PASS" )

        # Test 4: No mermaid found
        print( "\nTest 4: No mermaid found..." )
        result = MermaidRenderer._extract_mermaid( "Just some regular text without diagrams." )
        assert result is None
        print( "  PASS" )

        # Test 5: Empty content
        print( "\nTest 5: Empty content..." )
        assert MermaidRenderer._extract_mermaid( "" ) is None
        assert MermaidRenderer._extract_mermaid( None ) is None
        print( "  PASS" )

        # Test 6: SUPPORTED_TYPES
        print( "\nTest 6: Supported types..." )
        assert "diagram" in MermaidRenderer.SUPPORTED_TYPES
        assert "chart" not in MermaidRenderer.SUPPORTED_TYPES  # chart moved to MatplotlibRenderer
        print( "  PASS" )

        print( f"\n{'=' * 60}" )
        print( "All MermaidRenderer smoke tests passed" )
        print( f"{'=' * 60}" )

    except Exception as e:
        print( f"\nSmoke test FAILED: {e}" )
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    quick_smoke_test()
