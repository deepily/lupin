#!/usr/bin/env python3
"""
Placeholder Renderer — Fallback for unsupported visual types.

Emits visible TODO markers in the Marp Markdown so that unsupported
visual types (screenshot) are clearly marked for manual completion.
Always succeeds — never returns None.

Note (Session 248e740e, 2026-04-13): before_after and icon_only were moved
to NanoBananaRenderer (Imagen) since they can be adequately generated from
text prompts. Only screenshot remains here as it requires actual screen capture.
"""

from typing import Optional

from .visual_registry import VisualRenderer


class PlaceholderRenderer( VisualRenderer ):
    """
    Fallback renderer that emits visible TODO markers.

    Used for visual types without a real renderer (screenshot, icon_only, etc.)
    and as the default fallback in VisualRendererRegistry.

    Ensures:
        - Always returns a non-None string
        - Output is a Marp blockquote with bold type label
    """
    SUPPORTED_TYPES = [ "screenshot" ]

    async def render( self, visual_type: str, visual_description: str, **kwargs ) -> Optional[ str ]:
        """
        Generate a visible TODO placeholder.

        Requires:
            - visual_type is a non-empty string

        Ensures:
            - Returns a Marp blockquote string (never None)

        Returns:
            str: Blockquote with TODO marker
        """
        description = visual_description or "(no description provided)"
        return f"> **[TODO: {visual_type}]** {description}"


# =============================================================================
# Smoke Test
# =============================================================================

def quick_smoke_test():
    """Quick smoke test for PlaceholderRenderer."""
    import asyncio

    print( "=" * 60 )
    print( "PlaceholderRenderer Smoke Test" )
    print( "=" * 60 )

    try:
        renderer = PlaceholderRenderer()

        # Test 1: Normal output
        print( "\nTest 1: Normal output..." )
        result = asyncio.run( renderer.render( "screenshot", "UI dashboard with metrics" ) )
        assert result == '> **[TODO: screenshot]** UI dashboard with metrics'
        print( "  PASS" )

        # Test 2: None description
        print( "\nTest 2: None description..." )
        result = asyncio.run( renderer.render( "icon_only", None ) )
        assert "(no description provided)" in result
        print( "  PASS" )

        # Test 3: Never returns None
        print( "\nTest 3: Never returns None..." )
        result = asyncio.run( renderer.render( "unknown_type", "" ) )
        assert result is not None
        print( "  PASS" )

        print( f"\n{'=' * 60}" )
        print( "All PlaceholderRenderer smoke tests passed" )
        print( f"{'=' * 60}" )

    except Exception as e:
        print( f"\nSmoke test FAILED: {e}" )
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    quick_smoke_test()
