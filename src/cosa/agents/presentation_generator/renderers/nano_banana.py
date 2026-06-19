#!/usr/bin/env python3
"""
Nano Banana Renderer — Gemini API image generation for slides.

Calls Google's Imagen 3 (Nano Banana 2) model via the GeminiImageClient
to generate hero images, infographics, title backgrounds, and icons
for presentation slides. Returns markdown image references.

This is the first paid renderer — cost tracked via GeminiImageClient.
"""

import os
import logging
from typing import Optional

from .visual_registry import VisualRenderer

logger = logging.getLogger( __name__ )


class NanoBananaRenderer( VisualRenderer ):
    """
    Gemini API-backed renderer for presentation slide images.

    Generates images via Imagen 3 (Nano Banana 2) from natural-language
    descriptions. Saves PNGs to the visuals/ directory and returns
    Marp-compatible markdown image references.

    Requires:
        - gemini_client is a GeminiImageClient instance (passed via constructor)
        - output_dir is a writable directory path (passed via kwargs)

    Ensures:
        - Returns markdown image reference on success
        - Returns None on any failure (caller falls back to placeholder)
        - Cost tracked via gemini_client
    """
    SUPPORTED_TYPES = [ "hero_image", "infographic", "title_background", "icon", "before_after", "icon_only" ]

    def __init__( self, gemini_client=None, debug: bool = False, verbose: bool = False ):
        """
        Initialize NanoBananaRenderer.

        Requires:
            - gemini_client is a GeminiImageClient instance (or None for dry-run)

        Ensures:
            - Renderer is ready to call render()
        """
        self.gemini_client = gemini_client
        self.debug         = debug
        self.verbose       = verbose

    async def render( self, visual_type: str, visual_description: str, **kwargs ) -> Optional[ str ]:
        """
        Generate a slide image from natural-language description via Gemini API.

        Requires:
            - visual_type is one of SUPPORTED_TYPES
            - visual_description is a non-empty string
            - kwargs[ "output_dir" ] is a writable directory path

        Ensures:
            - Returns markdown image reference on success
            - Returns None on failure (non-fatal)

        kwargs:
            slide_title: str (optional, for prompt context and alt text)
            output_dir: str (required, directory for PNG output)
            slide_index: int (optional, for filename numbering, default 0)

        Returns:
            str: Markdown image reference, or None on failure
        """
        slide_title = kwargs.get( "slide_title", "" )
        output_dir  = kwargs.get( "output_dir" )
        slide_index = kwargs.get( "slide_index", 0 )

        if self.gemini_client is None:
            logger.warning( "NanoBananaRenderer: No gemini_client provided" )
            return None

        if output_dir is None:
            logger.warning( "NanoBananaRenderer: No output_dir provided" )
            return None

        try:
            from ..prompts.image_gen import get_image_prompt

            # Build Imagen prompt
            prompt = get_image_prompt(
                visual_type        = visual_type,
                visual_description = visual_description,
                slide_title        = slide_title,
            )

            if self.debug: print( f"[NanoBananaRenderer] Prompt ({len( prompt )} chars): {prompt[ :100 ]}..." )

            # Generate image
            output_filename = f"image-{slide_index:03d}.png"
            output_path     = os.path.join( output_dir, output_filename )

            success = await self.gemini_client.generate_image( prompt, output_path )

            if not success:
                logger.warning( f"NanoBananaRenderer: Image generation failed for: {slide_title[ :40 ]}" )
                return None

            # Verify output file exists
            if not os.path.exists( output_path ):
                logger.warning( f"NanoBananaRenderer: Output file not created: {output_path}" )
                return None

            if self.debug:
                file_size = os.path.getsize( output_path )
                print( f"[NanoBananaRenderer] Generated {file_size:,} bytes: {output_filename} for: {slide_title[ :40 ]}" )

            # Return relative path for Marp
            rel_path = os.path.join( "visuals", output_filename )
            alt_text = slide_title or visual_description[ :60 ]
            return f"![{alt_text}]({rel_path})"

        except Exception as e:
            logger.error( f"NanoBananaRenderer failed: {e}" )
            if self.debug: print( f"[NanoBananaRenderer] Exception: {e}" )
            return None


# =============================================================================
# Smoke Test
# =============================================================================

def quick_smoke_test():
    """Quick smoke test for NanoBananaRenderer (no live API calls)."""

    print( "=" * 60 )
    print( "NanoBananaRenderer Smoke Test" )
    print( "=" * 60 )

    try:
        import asyncio

        # Test 1: SUPPORTED_TYPES
        print( "\nTest 1: Supported types..." )
        assert "hero_image" in NanoBananaRenderer.SUPPORTED_TYPES
        assert "infographic" in NanoBananaRenderer.SUPPORTED_TYPES
        assert "title_background" in NanoBananaRenderer.SUPPORTED_TYPES
        assert "icon" in NanoBananaRenderer.SUPPORTED_TYPES
        print( "  PASS" )

        # Test 2: Construction
        print( "\nTest 2: Construction..." )
        renderer = NanoBananaRenderer( debug=True )
        assert renderer.gemini_client is None
        assert renderer.debug is True
        print( "  PASS" )

        # Test 3: Render without client returns None
        print( "\nTest 3: No client → None..." )
        renderer = NanoBananaRenderer()
        result   = asyncio.run( renderer.render( "hero_image", "A sunset" ) )
        assert result is None
        print( "  PASS" )

        # Test 4: Render without output_dir returns None
        print( "\nTest 4: No output_dir → None..." )
        from unittest.mock import MagicMock
        renderer = NanoBananaRenderer( gemini_client=MagicMock() )
        result   = asyncio.run( renderer.render( "hero_image", "A sunset" ) )
        assert result is None
        print( "  PASS" )

        print( f"\n{'=' * 60}" )
        print( "All NanoBananaRenderer smoke tests passed" )
        print( f"{'=' * 60}" )

    except Exception as e:
        print( f"\nSmoke test FAILED: {e}" )
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    quick_smoke_test()
