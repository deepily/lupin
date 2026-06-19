#!/usr/bin/env python3
"""
Veo Renderer — Gemini Veo video generation for presentation slides.

Generates short-form MP4 videos via Google Veo 2/3 API from natural-language
visual descriptions. Extracts a static PNG frame via ffmpeg for PDF/PPTX
fallback. Returns dual-format HTML with video tag + img fallback.

Handles "title_video", "flow_animation", and "process_video" visual types.

This is a file-producing renderer: it writes MP4 + PNG files to an output
directory and returns HTML video tags, unlike MermaidRenderer which returns
inline code blocks.
"""

import os
import shutil
import asyncio
import logging
import subprocess
from typing import ClassVar, List, Optional

from .visual_registry import VisualRenderer

logger = logging.getLogger( __name__ )


class VeoRenderer( VisualRenderer ):
    """
    Gemini Veo-backed renderer for presentation slide videos.

    Generates videos via Veo 2/3 from natural-language descriptions.
    Saves MP4 to visuals/ directory, extracts a still frame via ffmpeg,
    and returns HTML with video tag + img fallback.

    Requires:
        - gemini_client is a GeminiImageClient instance with generate_video()
        - output_dir is a writable directory path (passed via kwargs)

    Ensures:
        - Returns HTML video block on success
        - Returns None on any failure (caller falls back to placeholder)
        - Video count and cost tracked via gemini_client
    """
    SUPPORTED_TYPES: ClassVar[ List[ str ] ] = [ "title_video", "flow_animation", "process_video" ]

    def __init__( self, gemini_client=None, max_videos: int = 5, debug: bool = False, verbose: bool = False ):
        """
        Initialize VeoRenderer.

        Requires:
            - gemini_client is a GeminiImageClient instance (or None for dry-run)
            - max_videos is a positive integer (per-deck budget)

        Ensures:
            - Renderer is ready to call render()
            - ffmpeg availability check deferred to first render()
        """
        self.gemini_client    = gemini_client
        self.max_videos       = max_videos
        self.debug            = debug
        self.verbose          = verbose
        self._ffmpeg_available = None  # Lazy cache
        self._videos_rendered = 0     # Per-deck counter

    def _check_ffmpeg_available( self ) -> bool:
        """
        Check if ffmpeg is installed (cached after first call).

        Ensures:
            - Returns True if ffmpeg is on PATH
            - Caches result for subsequent calls
        """
        if self._ffmpeg_available is None:
            self._ffmpeg_available = shutil.which( "ffmpeg" ) is not None
            if not self._ffmpeg_available:
                logger.warning( "VeoRenderer: ffmpeg not found — frame extraction disabled" )
            elif self.debug:
                print( f"[VeoRenderer] ffmpeg found: {shutil.which( 'ffmpeg' )}" )
        return self._ffmpeg_available

    async def render( self, visual_type: str, visual_description: str, **kwargs ) -> Optional[ str ]:
        """
        Generate video from natural-language description via Veo API.

        Requires:
            - visual_type is one of SUPPORTED_TYPES
            - visual_description is a non-empty string
            - kwargs[ "output_dir" ] is a writable directory path

        Ensures:
            - Returns HTML video block on success
            - Returns None on failure (non-fatal)

        kwargs:
            slide_title: str (optional, for alt text)
            output_dir: str (required, directory for MP4/PNG output)
            slide_index: int (optional, for filename numbering, default 0)

        Returns:
            str: HTML video block, or None on failure
        """
        slide_title = kwargs.get( "slide_title", "" )
        output_dir  = kwargs.get( "output_dir" )
        slide_index = kwargs.get( "slide_index", 0 )

        if self.gemini_client is None:
            logger.warning( "VeoRenderer: No gemini_client provided" )
            return None

        if output_dir is None:
            logger.warning( "VeoRenderer: No output_dir provided" )
            return None

        # Per-deck video limit
        if self._videos_rendered >= self.max_videos:
            logger.warning( f"VeoRenderer: Max videos per deck reached ({self.max_videos})" )
            return None

        try:
            from ..prompts.video_gen import get_video_prompt, get_video_duration

            # Build prompt and get duration
            prompt   = get_video_prompt( visual_type, visual_description, slide_title )
            duration = get_video_duration( visual_type )

            if self.debug: print( f"[VeoRenderer] Generating {duration}s video for: {slide_title[ :40 ]}" )

            # Ensure output directory exists
            os.makedirs( output_dir, exist_ok=True )

            # Generate video
            video_filename = f"video-{slide_index:03d}.mp4"
            video_path     = os.path.join( output_dir, video_filename )

            success = await self.gemini_client.generate_video( prompt, video_path, duration )

            if not success:
                logger.warning( f"VeoRenderer: Video generation failed for: {slide_title[ :40 ]}" )
                return None

            if not os.path.exists( video_path ):
                logger.warning( f"VeoRenderer: Video file not created: {video_path}" )
                return None

            self._videos_rendered += 1

            # Extract static frame for PDF/PPTX fallback
            frame_filename = f"video-{slide_index:03d}-frame.png"
            frame_path     = os.path.join( output_dir, frame_filename )
            has_frame      = False

            if self._check_ffmpeg_available():
                has_frame = await self._extract_frame( video_path, frame_path )

            if self.debug:
                video_size = os.path.getsize( video_path )
                print( f"[VeoRenderer] Video {self._videos_rendered}: {video_size:,} bytes, frame: {has_frame}" )

            # Build dual-format HTML
            video_rel = os.path.join( "visuals", video_filename )
            frame_rel = os.path.join( "visuals", frame_filename )
            alt_text  = slide_title or visual_description[ :60 ]

            if has_frame:
                return (
                    f'<video src="{video_rel}" autoplay muted loop '
                    f'style="width:100%;max-height:500px;object-fit:cover;">\n'
                    f'  <img src="{frame_rel}" alt="{alt_text}" />\n'
                    f'</video>'
                )
            else:
                return (
                    f'<video src="{video_rel}" autoplay muted loop '
                    f'style="width:100%;max-height:500px;object-fit:cover;">\n'
                    f'</video>'
                )

        except Exception as e:
            logger.error( f"VeoRenderer failed: {e}" )
            if self.debug: print( f"[VeoRenderer] Exception: {e}" )
            return None

    async def _extract_frame( self, video_path: str, frame_path: str ) -> bool:
        """
        Extract a still frame at 1-second mark from MP4 using ffmpeg.

        Requires:
            - video_path is an existing MP4 file
            - frame_path is a writable file path

        Ensures:
            - Returns True if frame PNG was created
            - Returns False on any error (logged as warning)
        """
        try:
            loop   = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                lambda: subprocess.run(
                    [ "ffmpeg", "-i", video_path, "-ss", "1", "-frames:v", "1",
                      "-q:v", "2", frame_path, "-y" ],
                    capture_output=True,
                    text=True,
                    timeout=15
                )
            )

            if result.returncode != 0:
                logger.warning( f"VeoRenderer: ffmpeg frame extraction failed: {result.stderr[ :200 ]}" )
                return False

            return os.path.exists( frame_path )

        except subprocess.TimeoutExpired:
            logger.warning( "VeoRenderer: ffmpeg frame extraction timed out (15s)" )
            return False

        except Exception as e:
            logger.warning( f"VeoRenderer: Frame extraction error: {e}" )
            return False


# =============================================================================
# Smoke Test
# =============================================================================

def quick_smoke_test():
    """Quick smoke test for VeoRenderer (no live API calls)."""

    print( "=" * 60 )
    print( "VeoRenderer Smoke Test" )
    print( "=" * 60 )

    try:
        import asyncio
        from unittest.mock import MagicMock

        # Test 1: SUPPORTED_TYPES
        print( "\nTest 1: Supported types..." )
        assert "title_video" in VeoRenderer.SUPPORTED_TYPES
        assert "flow_animation" in VeoRenderer.SUPPORTED_TYPES
        assert "process_video" in VeoRenderer.SUPPORTED_TYPES
        print( "  PASS" )

        # Test 2: Construction
        print( "\nTest 2: Construction..." )
        renderer = VeoRenderer( debug=True, max_videos=3 )
        assert renderer.gemini_client is None
        assert renderer.max_videos == 3
        assert renderer._videos_rendered == 0
        print( "  PASS" )

        # Test 3: Render without client returns None
        print( "\nTest 3: No client → None..." )
        renderer = VeoRenderer()
        result   = asyncio.run( renderer.render( "title_video", "Abstract tech landscape" ) )
        assert result is None
        print( "  PASS" )

        # Test 4: Render without output_dir returns None
        print( "\nTest 4: No output_dir → None..." )
        renderer = VeoRenderer( gemini_client=MagicMock() )
        result   = asyncio.run( renderer.render( "title_video", "Abstract tech" ) )
        assert result is None
        print( "  PASS" )

        print( f"\n{'=' * 60}" )
        print( "All VeoRenderer smoke tests passed" )
        print( f"{'=' * 60}" )

    except Exception as e:
        print( f"\nSmoke test FAILED: {e}" )
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    quick_smoke_test()
