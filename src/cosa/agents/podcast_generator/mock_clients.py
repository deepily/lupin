#!/usr/bin/env python3
"""
Mock clients for dry-run mode testing of Podcast Generator.

Provides canned responses that simulate API calls without making real requests.
Used when dry_run=True to test job submission UI flows and queue mechanics.

Usage:
    from .mock_clients import MockPodcastAPIClient, MockTTSClient

    if dry_run:
        api_client = MockPodcastAPIClient( debug=True )
        tts_client = MockTTSClient( debug=True )
"""

import asyncio
from dataclasses import dataclass, field
from typing import Optional, Callable, Awaitable, List, Any

from .state import PodcastScript, ScriptSegment


# =============================================================================
# Mock API Response Data
# =============================================================================

MOCK_SCRIPT_RESPONSE = {
    "title"                        : "Mock Podcast: Dry Run Test",
    "estimated_duration_minutes"   : 5.0,
    "speakers"                     : {
        "curious" : { "name": "Alex", "personality": "Friendly and curious" },
        "expert"  : { "name": "Jordan", "personality": "Knowledgeable and engaging" }
    },
    "segments": [
        { "speaker": "Alex", "role": "curious", "dialogue": "Welcome to today's mock podcast!" },
        { "speaker": "Jordan", "role": "expert", "dialogue": "Thanks for having me. We're testing the dry run mode." },
        { "speaker": "Alex", "role": "curious", "dialogue": "How does dry run mode work?" },
        { "speaker": "Jordan", "role": "expert", "dialogue": "It simulates the entire workflow without making real API calls." },
        { "speaker": "Alex", "role": "curious", "dialogue": "That's great for testing the UI!" },
        { "speaker": "Jordan", "role": "expert", "dialogue": "Exactly. No cost, no delays, just quick validation." },
        { "speaker": "Alex", "role": "curious", "dialogue": "What about the audio generation?" },
        { "speaker": "Jordan", "role": "expert", "dialogue": "We return silence bytes that look like real PCM audio." },
        { "speaker": "Alex", "role": "curious", "dialogue": "Perfect for end-to-end testing." },
        { "speaker": "Jordan", "role": "expert", "dialogue": "That wraps up our dry run demonstration!" }
    ]
}


# =============================================================================
# Mock API Client
# =============================================================================

@dataclass
class MockCostEstimate:
    """Mock cost tracking for dry-run mode."""
    total_input_tokens  : int   = 0
    total_output_tokens : int   = 0
    total_api_calls     : int   = 0
    estimated_cost_usd  : float = 0.0

    def add_usage( self, model: str, input_tokens: int, output_tokens: int ):
        """Add mock usage (always zero cost in dry run)."""
        self.total_api_calls += 1


class MockPodcastAPIClient:
    """
    Mock API client that returns canned responses without calling Claude.

    Simulates the PodcastAPIClient interface for dry-run mode testing.
    Includes realistic delays to simulate API latency.

    Requires:
        - None (no API key needed)

    Ensures:
        - Returns structurally valid script generation responses
        - Simulates ~1 second delay per API call
        - Tracks mock call count
    """

    def __init__( self, config = None, debug: bool = False, verbose: bool = False ):
        """
        Initialize mock API client.

        Args:
            config: PodcastConfig (ignored in mock)
            debug: Enable debug output
            verbose: Enable verbose output
        """
        self.config       = config
        self.debug        = debug
        self.verbose      = verbose
        self.call_count   = 0
        self.cost_estimate = MockCostEstimate()

    async def generate_script(
        self,
        research_content : str,
        language_code    : str = "en",
        additional_context : Optional[ str ] = None
    ) -> dict:
        """
        Return mock script generation response.

        Requires:
            - research_content is a non-empty string (not validated in mock)

        Ensures:
            - Returns valid PodcastScript-compatible dict
            - Includes ~1 second simulated latency

        Args:
            research_content: Research document text (ignored)
            language_code: Target language (noted in response)
            additional_context: Extra context (ignored)

        Returns:
            dict: Mock script response matching expected schema
        """
        self.call_count += 1

        if self.debug:
            print( f"[MockPodcastAPIClient] Call #{self.call_count} - generate_script()" )
            print( f"[MockPodcastAPIClient] Language: {language_code}" )

        # Simulate API latency
        await asyncio.sleep( 1.0 )

        # Return mock response with language noted
        response = MOCK_SCRIPT_RESPONSE.copy()
        response[ "language_code" ] = language_code

        return response

    async def call_with_json_output(
        self,
        messages        : List[ dict ],
        schema          : Optional[ dict ] = None,
        model           : Optional[ str ] = None,
        max_tokens      : int = 8192,
        temperature     : float = 0.7
    ) -> dict:
        """
        Generic mock JSON output call.

        Args:
            messages: Conversation messages (ignored)
            schema: JSON schema for output (ignored)
            model: Model to use (ignored)
            max_tokens: Max output tokens (ignored)
            temperature: Sampling temperature (ignored)

        Returns:
            dict: Mock response
        """
        self.call_count += 1

        if self.debug:
            print( f"[MockPodcastAPIClient] Call #{self.call_count} - call_with_json_output()" )

        await asyncio.sleep( 1.0 )
        return MOCK_SCRIPT_RESPONSE

    async def revise_script(
        self,
        current_script : dict,
        feedback       : str,
        language_code  : str = "en"
    ) -> dict:
        """
        Mock script revision - returns slightly modified original.

        Args:
            current_script: Current script (used as base)
            feedback: User feedback (noted in debug)
            language_code: Target language

        Returns:
            dict: Mock revised script
        """
        self.call_count += 1

        if self.debug:
            print( f"[MockPodcastAPIClient] Call #{self.call_count} - revise_script()" )
            print( f"[MockPodcastAPIClient] Feedback: {feedback[ :50 ]}..." )

        await asyncio.sleep( 1.0 )

        # Return modified copy
        response = MOCK_SCRIPT_RESPONSE.copy()
        response[ "title" ] = "Mock Podcast: Revised (Dry Run)"
        response[ "language_code" ] = language_code

        return response


# =============================================================================
# Mock TTS Client
# =============================================================================

@dataclass
class MockTTSSegmentResult:
    """
    Mock result matching TTSSegmentResult interface.

    Contains silence audio that looks like real PCM data.
    """
    segment_index    : int
    speaker          : str
    role             : str
    pcm_audio        : bytes            = b""
    duration_seconds : float            = 0.0
    character_count  : int              = 0
    success          : bool             = True
    error_message    : Optional[ str ]  = None
    retry_count      : int              = 0


class MockTTSClient:
    """
    Mock TTS client that returns silence without calling ElevenLabs.

    Simulates the PodcastTTSClient interface for dry-run mode testing.
    Returns PCM-format silence bytes that look like real audio.

    Requires:
        - None (no API key needed)

    Ensures:
        - Returns structurally valid TTSSegmentResult objects
        - Simulates ~0.5 second delay per segment
        - Tracks mock generation count
    """

    def __init__(
        self,
        config_mgr         = None,
        progress_callback  : Optional[ Callable[ [ int, int, str, float ], Awaitable[ None ] ] ] = None,
        retry_callback     : Optional[ Callable[ [ int, int, int, str ], Awaitable[ None ] ] ] = None,
        debug              : bool = False,
        verbose            : bool = False,
        max_retries        : int  = 3,
        retry_base_delay   : float = 1.0,
    ):
        """
        Initialize mock TTS client.

        Args:
            config_mgr: ConfigurationManager (ignored)
            progress_callback: Progress callback (called during generation)
            retry_callback: Retry callback (not called in mock - always succeeds)
            debug: Enable debug output
            verbose: Enable verbose output
            max_retries: Max retries (ignored - always succeeds)
            retry_base_delay: Retry delay (ignored)
        """
        self.config_mgr        = config_mgr
        self.progress_callback = progress_callback
        self.retry_callback    = retry_callback
        self.debug             = debug
        self.verbose           = verbose
        self.max_retries       = max_retries
        self.retry_base_delay  = retry_base_delay
        self.segment_count     = 0

    def _generate_silence_pcm( self, duration_seconds: float = 1.0 ) -> bytes:
        """
        Generate PCM silence bytes.

        PCM 24000Hz, 16-bit mono = 2 bytes per sample.
        1 second = 48000 bytes of silence.

        Args:
            duration_seconds: Duration of silence to generate

        Returns:
            bytes: PCM silence (all zeros)
        """
        samples = int( 24000 * duration_seconds )
        return b'\x00\x00' * samples

    async def generate_segment(
        self,
        segment       : Any,  # ScriptSegment
        segment_index : int,
        total_segments : int
    ) -> MockTTSSegmentResult:
        """
        Generate mock TTS for a single segment.

        Args:
            segment: ScriptSegment with speaker/role/dialogue
            segment_index: Index in the segment list
            total_segments: Total number of segments

        Returns:
            MockTTSSegmentResult: Mock result with silence audio
        """
        self.segment_count += 1

        # Extract segment info
        speaker = getattr( segment, 'speaker', 'Unknown' )
        role    = getattr( segment, 'role', 'expert' )
        text    = getattr( segment, 'dialogue', '' )

        if self.debug:
            print( f"[MockTTSClient] Segment {segment_index + 1}/{total_segments}: {speaker}" )

        # Simulate TTS latency (shorter than real)
        await asyncio.sleep( 0.3 )

        # Generate silence proportional to text length (rough ~150 wpm estimate)
        word_count = len( text.split() )
        duration   = max( 1.0, word_count / 2.5 )  # ~150 wpm speaking rate

        # Create mock result
        result = MockTTSSegmentResult(
            segment_index    = segment_index,
            speaker          = speaker,
            role             = role,
            pcm_audio        = self._generate_silence_pcm( duration ),
            duration_seconds = duration,
            character_count  = len( text ),
            success          = True
        )

        # Call progress callback if provided
        if self.progress_callback:
            eta = ( total_segments - segment_index - 1 ) * 0.3
            await self.progress_callback( segment_index + 1, total_segments, speaker, eta )

        return result

    async def generate_all_segments(
        self,
        script        : Any,  # PodcastScript
        language_code : str = "en"
    ) -> List[ MockTTSSegmentResult ]:
        """
        Generate mock TTS for all segments in a script.

        Args:
            script: PodcastScript with segments
            language_code: Target language (noted in debug)

        Returns:
            List[MockTTSSegmentResult]: Results for all segments
        """
        segments = getattr( script, 'segments', [] )
        total    = len( segments )

        if self.debug:
            print( f"[MockTTSClient] Generating {total} segments in {language_code}" )

        results = []
        for i, segment in enumerate( segments ):
            result = await self.generate_segment( segment, i, total )
            results.append( result )

        if self.debug:
            total_duration = sum( r.duration_seconds for r in results )
            print( f"[MockTTSClient] Complete: {total_duration:.1f}s total duration" )

        return results


# =============================================================================
# Smoke Test
# =============================================================================

def quick_smoke_test():
    """Quick smoke test for podcast generator mock clients."""
    import cosa.utils.util as cu

    cu.print_banner( "Podcast Generator Mock Clients Smoke Test", prepend_nl=True )

    try:
        # Test 1: Import
        print( "Testing module import..." )
        from cosa.agents.podcast_generator.mock_clients import (
            MockPodcastAPIClient,
            MockTTSClient,
            MockTTSSegmentResult,
            MOCK_SCRIPT_RESPONSE
        )
        print( "✓ Module imported successfully" )

        # Test 2: Mock API client instantiation
        print( "Testing MockPodcastAPIClient instantiation..." )
        api_client = MockPodcastAPIClient( debug=True )
        assert api_client.call_count == 0
        print( "✓ MockPodcastAPIClient created" )

        # Test 3: Mock TTS client instantiation
        print( "Testing MockTTSClient instantiation..." )
        tts_client = MockTTSClient( debug=True )
        assert tts_client.segment_count == 0
        print( "✓ MockTTSClient created" )

        # Test 4: Mock script response structure
        print( "Testing mock script response structure..." )
        assert "title" in MOCK_SCRIPT_RESPONSE
        assert "segments" in MOCK_SCRIPT_RESPONSE
        assert len( MOCK_SCRIPT_RESPONSE[ "segments" ] ) == 10
        print( f"✓ Mock script has {len( MOCK_SCRIPT_RESPONSE[ 'segments' ] )} segments" )

        # Test 5: Generate script async
        print( "Testing async generate_script..." )

        async def test_generate_script():
            result = await api_client.generate_script( "test research content" )
            return result

        result = asyncio.run( test_generate_script() )
        assert "title" in result
        assert api_client.call_count == 1
        print( "✓ generate_script() works" )

        # Test 6: Generate silence PCM
        print( "Testing silence PCM generation..." )
        silence = tts_client._generate_silence_pcm( 1.0 )
        expected_bytes = 24000 * 2  # 24kHz, 16-bit mono
        assert len( silence ) == expected_bytes
        print( f"✓ Generated {len( silence )} bytes of silence (1 second)" )

        # Test 7: Mock segment result
        print( "Testing MockTTSSegmentResult..." )
        segment_result = MockTTSSegmentResult(
            segment_index    = 0,
            speaker          = "Alex",
            role             = "curious",
            pcm_audio        = silence,
            duration_seconds = 1.0,
            character_count  = 50
        )
        assert segment_result.success == True
        print( "✓ MockTTSSegmentResult works" )

        print( "\n✓ Mock clients smoke test completed successfully" )

    except Exception as e:
        print( f"\n✗ Smoke test failed: {e}" )
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    quick_smoke_test()
