#!/usr/bin/env python3
"""
Shared Gemini Image/Video Generation Client for Presentation Generator.

Provides a lazy-initialized, cost-tracking wrapper around Google's
google-genai SDK for image generation (Imagen 3 / Nano Banana 2).
Designed for reuse by both NanoBananaRenderer (images) and
VeoRenderer (video, Phase 10B).

Uses native async: client.aio.models.generate_images() — no run_in_executor needed.
"""

import os
import asyncio
import logging
from typing import Optional

logger = logging.getLogger( __name__ )

# Default cost per image at 1K resolution (March 2026 pricing)
COST_PER_IMAGE_1K = 0.067

# Default cost per second of video (Veo 2 pricing, March 2026)
COST_PER_VIDEO_SECOND = 0.20


class GeminiImageClient:
    """
    Shared client for Gemini image generation APIs.

    Lazy-initializes the google.genai.Client on first use, loading the
    API key from src/conf/keys/gemini via cu.get_api_key().

    Requires:
        - Gemini API key at src/conf/keys/gemini (or GEMINI_API_KEY env var)

    Ensures:
        - Client initialized only when first generation requested
        - Cost tracked per image generated
        - Native async support (no executor wrapping)
    """

    def __init__( self, model: str = "imagen-4.0-generate-001", aspect_ratio: str = "16:9",
                  budget_limit: float = 1.00, video_model: str = "veo-2.0-generate-001",
                  video_budget_limit: float = 5.00, debug: bool = False ):
        """
        Initialize GeminiImageClient.

        Requires:
            - model is a valid Imagen model ID
            - aspect_ratio is one of: "1:1", "3:4", "4:3", "9:16", "16:9"
            - budget_limit is a positive float (max image spend per presentation)
            - video_model is a valid Veo model ID
            - video_budget_limit is a positive float (max video spend per presentation)

        Ensures:
            - Client ready for lazy initialization on first generate_image/video() call
        """
        self.model              = model
        self.aspect_ratio       = aspect_ratio
        self.budget_limit       = budget_limit
        self.video_model        = video_model
        self.video_budget_limit = video_budget_limit
        self.debug              = debug
        self._client            = None
        self.cost_total         = 0.0
        self.images_generated   = 0
        self.video_cost_total   = 0.0
        self.videos_generated   = 0

    def _get_client( self ):
        """
        Lazy-initialize google.genai.Client with API key.

        Requires:
            - Gemini API key available via cu.get_api_key("gemini")

        Ensures:
            - Returns initialized genai.Client
            - Raises RuntimeError if key not found

        Returns:
            google.genai.Client instance
        """
        if self._client is None:
            from google import genai
            import cosa.utils.util as cu

            api_key = cu.get_api_key( "gemini" )
            if not api_key:
                raise RuntimeError( "Gemini API key not found at src/conf/keys/gemini" )

            self._client = genai.Client( api_key=api_key )
            if self.debug: print( f"[GeminiImageClient] Initialized with model={self.model}" )

        return self._client

    async def generate_image( self, prompt: str, output_path: str, **kwargs ) -> bool:
        """
        Generate an image via Imagen 3 (Nano Banana 2).

        Uses native async: client.aio.models.generate_images()

        Requires:
            - prompt is a non-empty string
            - output_path is a writable file path

        Ensures:
            - Returns True if image saved to output_path
            - Returns False on any failure (API error, RAI filter, empty response)
            - Cost tracked on success

        Returns:
            bool: True on success, False on failure
        """
        from google.genai import types

        # Budget check
        if self.cost_total >= self.budget_limit:
            logger.warning( f"GeminiImageClient: Budget limit reached (${self.cost_total:.2f} >= ${self.budget_limit:.2f})" )
            return False

        try:
            client = self._get_client()

            config = types.GenerateImagesConfig(
                number_of_images    = 1,
                aspect_ratio        = kwargs.get( "aspect_ratio", self.aspect_ratio ),
                output_mime_type    = "image/png",
                include_rai_reason  = True,
                person_generation   = types.PersonGeneration.ALLOW_ADULT,
                safety_filter_level = types.SafetyFilterLevel.BLOCK_LOW_AND_ABOVE,
            )

            response = await client.aio.models.generate_images(
                model  = self.model,
                prompt = prompt,
                config = config,
            )

            if not response.generated_images:
                logger.warning( "GeminiImageClient: No images in response" )
                return False

            generated = response.generated_images[ 0 ]

            # Check RAI filter
            if generated.rai_filtered_reason:
                logger.warning( f"GeminiImageClient: Image filtered by safety: {generated.rai_filtered_reason}" )
                return False

            if generated.image is None:
                logger.warning( "GeminiImageClient: Generated image object is None" )
                return False

            # Save image to disk
            generated.image.save( output_path )
            self.images_generated += 1
            self._track_cost()

            if self.debug:
                file_size = os.path.getsize( output_path ) if os.path.exists( output_path ) else 0
                print( f"[GeminiImageClient] Image {self.images_generated}: {file_size:,} bytes, total cost: ${self.cost_total:.3f}" )

            return True

        except Exception as e:
            logger.error( f"GeminiImageClient: Image generation failed: {e}" )
            if self.debug: print( f"[GeminiImageClient] Exception: {e}" )
            return False

    def _track_cost( self ):
        """Track cost per image at current resolution pricing."""
        self.cost_total += COST_PER_IMAGE_1K

    # =========================================================================
    # Video Generation (Veo 2 / Veo 3)
    # =========================================================================

    async def generate_video( self, prompt: str, output_path: str, duration_seconds: int = 8 ) -> bool:
        """
        Generate a video via Veo model with async polling.

        Uses async polling: generate_videos() returns an operation that must
        be polled until completion (~30-60 seconds typical).

        Requires:
            - prompt is a non-empty string
            - output_path is a writable file path
            - duration_seconds is 1-8

        Ensures:
            - Returns True if video saved to output_path
            - Returns False on any failure (budget, timeout, API error)
            - Video cost tracked on success

        Returns:
            bool: True on success, False on failure
        """
        from google.genai import types

        # Budget check
        estimated_cost = duration_seconds * COST_PER_VIDEO_SECOND
        if self.video_cost_total + estimated_cost > self.video_budget_limit:
            logger.warning(
                f"GeminiImageClient: Video budget limit reached "
                f"(${self.video_cost_total:.2f} + ${estimated_cost:.2f} > ${self.video_budget_limit:.2f})"
            )
            return False

        try:
            client = self._get_client()

            config = types.GenerateVideosConfig(
                number_of_videos = 1,
                duration_seconds = duration_seconds,
                resolution       = "1080p",
                aspect_ratio     = "16:9",
            )

            if self.debug: print( f"[GeminiImageClient] Generating video: model={self.video_model}, {duration_seconds}s" )

            operation = await client.aio.models.generate_videos(
                model  = self.video_model,
                prompt = prompt,
                config = config,
            )

            # Poll for completion (max 120s, 10s intervals)
            for poll_count in range( 12 ):
                if operation.done: break
                if self.debug: print( f"[GeminiImageClient] Polling video... ({( poll_count + 1 ) * 10}s)" )
                await asyncio.sleep( 10 )
                operation = await client.aio.operations.get( operation )

            if not operation.done:
                logger.warning( "GeminiImageClient: Video generation timed out (120s)" )
                return False

            # Check for errors
            if operation.error:
                logger.warning( f"GeminiImageClient: Video generation error: {operation.error}" )
                return False

            # Extract video bytes
            if operation.result and operation.result.generated_videos:
                generated = operation.result.generated_videos[ 0 ]

                # Check RAI filter
                if operation.result.rai_media_filtered_count and operation.result.rai_media_filtered_count > 0:
                    logger.warning( f"GeminiImageClient: Video filtered by safety: {operation.result.rai_media_filtered_reasons}" )
                    return False

                if generated.video and generated.video.video_bytes:
                    with open( output_path, "wb" ) as f:
                        f.write( generated.video.video_bytes )
                    self._track_video_cost( duration_seconds )

                    if self.debug:
                        file_size = os.path.getsize( output_path ) if os.path.exists( output_path ) else 0
                        print( f"[GeminiImageClient] Video {self.videos_generated}: {file_size:,} bytes, cost: ${self.video_cost_total:.2f}" )

                    return os.path.exists( output_path )

            logger.warning( "GeminiImageClient: No video in response" )
            return False

        except Exception as e:
            logger.error( f"GeminiImageClient: Video generation failed: {e}" )
            if self.debug: print( f"[GeminiImageClient] Video exception: {e}" )
            return False

    def _track_video_cost( self, duration_seconds: int ):
        """Track cost per video at current per-second pricing."""
        self.video_cost_total += duration_seconds * COST_PER_VIDEO_SECOND
        self.videos_generated += 1


# =============================================================================
# Smoke Test
# =============================================================================

def quick_smoke_test():
    """Quick smoke test for GeminiImageClient (no live API calls)."""

    print( "=" * 60 )
    print( "GeminiImageClient Smoke Test" )
    print( "=" * 60 )

    try:
        # Test 1: Construction with defaults
        print( "\nTest 1: Construction with defaults..." )
        client = GeminiImageClient()
        assert client.model == "imagen-3.0-generate-002"
        assert client.aspect_ratio == "16:9"
        assert client.budget_limit == 1.00
        assert client.cost_total == 0.0
        assert client.images_generated == 0
        assert client._client is None  # Lazy — not initialized yet
        print( "  PASS" )

        # Test 2: Construction with custom params
        print( "\nTest 2: Custom construction..." )
        client = GeminiImageClient( model="custom-model", aspect_ratio="1:1", budget_limit=5.0, debug=True )
        assert client.model == "custom-model"
        assert client.aspect_ratio == "1:1"
        assert client.budget_limit == 5.0
        print( "  PASS" )

        # Test 3: Cost tracking
        print( "\nTest 3: Cost tracking..." )
        client = GeminiImageClient()
        client._track_cost()
        assert client.cost_total == COST_PER_IMAGE_1K
        client._track_cost()
        assert client.cost_total == COST_PER_IMAGE_1K * 2
        print( "  PASS" )

        # Test 4: Budget limit constant
        print( "\nTest 4: Cost constant..." )
        assert COST_PER_IMAGE_1K == 0.067
        print( "  PASS" )

        print( f"\n{'=' * 60}" )
        print( "All GeminiImageClient smoke tests passed" )
        print( f"{'=' * 60}" )

    except Exception as e:
        print( f"\nSmoke test FAILED: {e}" )
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    quick_smoke_test()
