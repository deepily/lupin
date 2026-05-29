#!/usr/bin/env python3
"""
Image Generation Prompts for Presentation Generator.

Prompt builder for generating effective Imagen 3 (Nano Banana 2) prompts
from slide visual descriptions. Used by NanoBananaRenderer during
Phase 7 (Visual Rendering).

Unlike LLM prompts (which have system + user messages), Imagen uses a
single prompt string. This module constructs that string by combining
the visual description with style modifiers and composition hints.

Pattern: Same 3-part structure as visual.py and matplotlib.py
  - Style modifier constants
  - Context string
  - Prompt builder function
"""


# =============================================================================
# Style Modifiers by Visual Type
# =============================================================================

IMAGE_STYLE_MODIFIERS = {
    "hero_image"       : "photorealistic, cinematic lighting, professional, high quality, detailed",
    "infographic"      : "flat design, vector style, clean labels, infographic layout, data visualization",
    "title_background" : "abstract, soft gradients, no text overlay, professional background, subtle texture",
    "icon"             : "flat icon, single color, minimal, centered, clean edges, simple shapes",
    "before_after"     : "split-screen comparison, clean layout, labeled sections, professional diagram style",
    "icon_only"        : "single large centered icon, minimal background, clean and simple, presentation slide",
}

DEFAULT_STYLE_MODIFIER = "professional, high quality, clean composition"


# =============================================================================
# Context Prefix
# =============================================================================

IMAGE_CONTEXT_PREFIX = "Professional presentation slide visual."


# =============================================================================
# Visual Types That Should NOT Contain Text
# =============================================================================

NO_TEXT_TYPES = { "hero_image", "title_background", "icon" }


# =============================================================================
# Prompt Builder
# =============================================================================

def get_image_prompt( visual_type: str, visual_description: str, slide_title: str = "" ) -> str:
    """
    Build an Imagen prompt from visual type, description, and slide context.

    Requires:
        - visual_type is a string (e.g., "hero_image", "infographic")
        - visual_description is a non-empty string

    Ensures:
        - Returns a single prompt string suitable for Imagen 3 API
        - Includes style modifier for the visual type
        - Includes "no text" directive for non-infographic types
        - Includes slide title context when available

    Returns:
        str: Imagen prompt string
    """
    style = IMAGE_STYLE_MODIFIERS.get( visual_type, DEFAULT_STYLE_MODIFIER )

    parts = [ IMAGE_CONTEXT_PREFIX ]

    # Add slide title context
    if slide_title:
        parts.append( f"For a slide titled \"{slide_title}\"." )

    # Add the user's visual description
    if visual_description:
        parts.append( visual_description )

    # Add style modifier
    parts.append( f"Style: {style}." )

    # Add no-text directive for types that shouldn't contain text
    if visual_type in NO_TEXT_TYPES:
        parts.append( "Do not include any text, words, letters, or numbers in the image." )

    # Composition hint for slide aspect ratio
    parts.append( "Composed for 16:9 widescreen slide format." )

    return " ".join( parts )


# =============================================================================
# Smoke Test
# =============================================================================

def quick_smoke_test():
    """Quick smoke test for image generation prompts."""

    print( "=" * 60 )
    print( "Image Gen Prompts Smoke Test" )
    print( "=" * 60 )

    try:
        # Test 1: Style modifiers exist for all types
        print( "\nTest 1: Style modifiers..." )
        for visual_type in [ "hero_image", "infographic", "title_background", "icon" ]:
            assert visual_type in IMAGE_STYLE_MODIFIERS, f"Missing: {visual_type}"
        print( "  PASS" )

        # Test 2: Prompt builder — hero_image
        print( "\nTest 2: Hero image prompt..." )
        prompt = get_image_prompt(
            visual_type        = "hero_image",
            visual_description = "A futuristic city skyline at sunset",
            slide_title        = "The Future of Urban Planning",
        )
        assert "futuristic city" in prompt
        assert "Urban Planning" in prompt
        assert "photorealistic" in prompt
        assert "no text" in prompt.lower() or "Do not include any text" in prompt
        assert "16:9" in prompt
        print( "  PASS" )

        # Test 3: Infographic prompt (should NOT have no-text directive)
        print( "\nTest 3: Infographic prompt..." )
        prompt = get_image_prompt(
            visual_type        = "infographic",
            visual_description = "Breakdown of revenue by region",
            slide_title        = "Revenue Distribution",
        )
        assert "flat design" in prompt
        assert "Do not include any text" not in prompt
        print( "  PASS" )

        # Test 4: Empty description
        print( "\nTest 4: Empty description..." )
        prompt = get_image_prompt(
            visual_type        = "icon",
            visual_description = "",
        )
        assert "flat icon" in prompt
        assert "16:9" in prompt
        print( "  PASS" )

        print( f"\n{'=' * 60}" )
        print( "All image gen prompt smoke tests passed" )
        print( f"{'=' * 60}" )

    except Exception as e:
        print( f"\nSmoke test FAILED: {e}" )
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    quick_smoke_test()
