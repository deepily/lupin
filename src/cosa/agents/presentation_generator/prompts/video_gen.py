#!/usr/bin/env python3
"""
Video Generation Prompts for Presentation Generator.

Prompt builder for generating short-form video via Google Veo 2/3
from natural-language visual descriptions. Used by VeoRenderer
during Phase 7 (Visual Rendering).

Pattern: Same structure as image_gen.py
  - Duration map
  - Style modifier dict
  - System rules constant
  - Prompt builder function
"""


# =============================================================================
# Duration Map (seconds per visual type)
# =============================================================================

VIDEO_DURATION_MAP = {
    "title_video"    : 5,   # Ambient loop — short and seamless
    "flow_animation" : 6,   # Step-by-step process — moderate
    "process_video"  : 8,   # Educational walkthrough — needs time
}

DEFAULT_VIDEO_DURATION = 8


# =============================================================================
# Style Modifiers (per visual type)
# =============================================================================

VIDEO_STYLE_MODIFIERS = {
    "title_video"    : "Slow cinematic pan, abstract environment, soft ambient lighting, "
                       "no text, no people, no logos, seamless loop potential",
    "flow_animation" : "Smooth data flow animation, clean white or dark background, "
                       "stages appearing sequentially with clear transitions, diagram style",
    "process_video"  : "Step-by-step educational visualization, technical diagram style, "
                       "smooth transitions between phases, labeled stages, professional",
}

DEFAULT_STYLE_MODIFIER = "Professional visualization, clean background, smooth motion"


# =============================================================================
# System Rules (appended to all video prompts)
# =============================================================================

VIDEO_SYSTEM_RULES = "1080p, high quality, smooth motion, no text overlays, no watermarks, no UI elements"


# =============================================================================
# Prompt Builder
# =============================================================================

def get_video_prompt( visual_type: str, visual_description: str, slide_title: str = "" ) -> str:
    """
    Build a video generation prompt for Veo.

    Requires:
        - visual_type is one of: title_video, flow_animation, process_video
        - visual_description is a non-empty string

    Ensures:
        - Returns a prompt string combining style modifiers, description, and rules
        - Suitable for Veo text-to-video generation

    Returns:
        str: Video generation prompt
    """
    style = VIDEO_STYLE_MODIFIERS.get( visual_type, DEFAULT_STYLE_MODIFIER )

    parts = []

    if slide_title:
        parts.append( f"For a presentation slide titled '{slide_title}':" )

    parts.append( style )
    parts.append( visual_description )
    parts.append( VIDEO_SYSTEM_RULES )

    return ". ".join( parts )


def get_video_duration( visual_type: str ) -> int:
    """
    Get recommended video duration for a visual type.

    Requires:
        - visual_type is a string

    Ensures:
        - Returns duration in seconds (5-8)
        - Returns DEFAULT_VIDEO_DURATION for unknown types

    Returns:
        int: Duration in seconds
    """
    return VIDEO_DURATION_MAP.get( visual_type, DEFAULT_VIDEO_DURATION )


# =============================================================================
# Smoke Test
# =============================================================================

def quick_smoke_test():
    """Quick smoke test for video generation prompts."""

    print( "=" * 60 )
    print( "Video Gen Prompts Smoke Test" )
    print( "=" * 60 )

    try:
        # Test 1: Duration map
        print( "\nTest 1: Duration map..." )
        assert get_video_duration( "title_video" ) == 5
        assert get_video_duration( "flow_animation" ) == 6
        assert get_video_duration( "process_video" ) == 8
        assert get_video_duration( "unknown" ) == DEFAULT_VIDEO_DURATION
        print( "  PASS" )

        # Test 2: Prompt builder
        print( "\nTest 2: Prompt builder..." )
        prompt = get_video_prompt(
            visual_type        = "title_video",
            visual_description = "Abstract technology landscape with flowing data streams",
            slide_title        = "The Future of AI",
        )
        assert "The Future of AI" in prompt
        assert "cinematic" in prompt.lower()
        assert "1080p" in prompt
        assert "no text" in prompt.lower()
        print( "  PASS" )

        # Test 3: Style modifiers exist for all types
        print( "\nTest 3: Style modifiers..." )
        for vtype in VIDEO_DURATION_MAP:
            assert vtype in VIDEO_STYLE_MODIFIERS, f"Missing style for {vtype}"
        print( "  PASS" )

        # Test 4: System rules
        print( "\nTest 4: System rules..." )
        assert "1080p" in VIDEO_SYSTEM_RULES
        assert "watermark" in VIDEO_SYSTEM_RULES.lower()
        print( "  PASS" )

        # Test 5: Prompt without slide title
        print( "\nTest 5: Prompt without title..." )
        prompt = get_video_prompt( "flow_animation", "Data flowing through pipeline stages" )
        assert "pipeline" in prompt.lower()
        assert "smooth" in prompt.lower()
        print( "  PASS" )

        print( f"\n{'=' * 60}" )
        print( "All video gen prompt smoke tests passed" )
        print( f"{'=' * 60}" )

    except Exception as e:
        print( f"\nSmoke test FAILED: {e}" )
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    quick_smoke_test()
