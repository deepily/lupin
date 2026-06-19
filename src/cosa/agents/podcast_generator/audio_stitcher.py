#!/usr/bin/env python3
"""
Audio Stitcher for COSA Podcast Generator Agent - Phase 2.

Concatenates TTS-generated PCM audio segments into a single podcast MP3 file.
Uses pydub for audio manipulation and ffmpeg for MP3 encoding.

Design Pattern: Sequential audio concatenation with silence gaps
- Converts PCM 24000Hz to pydub AudioSegment
- Adds configurable silence between different speakers
- Exports final podcast as MP3 at 192k bitrate
"""

import logging
import os
from dataclasses import dataclass
from typing import List, Optional

from pydub import AudioSegment

from .tts_client import TTSSegmentResult

logger = logging.getLogger( __name__ )


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class StitchingResult:
    """
    Result of audio stitching operation.

    Contains metadata about the final podcast audio file.

    Requires:
        - output_path is a valid file path if success is True

    Ensures:
        - file_size_bytes is positive if success is True
        - total_duration_seconds reflects actual audio length
    """

    output_path            : str
    total_duration_seconds : float
    segments_stitched      : int
    file_size_bytes        : int
    success                : bool
    error_message          : Optional[ str ] = None


# =============================================================================
# Audio Stitcher Class
# =============================================================================

class PodcastAudioStitcher:
    """
    Audio stitcher for podcast generation.

    Concatenates TTS segment results into a single MP3 podcast file.
    Adds silence between different speakers for natural pacing.

    Requires:
        - ffmpeg is installed on the system (for MP3 export)
        - pydub is available

    Ensures:
        - Output is MP3 format at specified bitrate
        - Silence gaps are added between speaker changes
        - Failed segments are skipped (silent gaps)
    """

    def __init__(
        self,
        silence_between_speakers_ms : int   = 300,
        audio_bitrate               : str   = "192k",
        debug                       : bool  = False,
        verbose                     : bool  = False,
    ):
        """
        Initialize the audio stitcher.

        Args:
            silence_between_speakers_ms: Milliseconds of silence between speakers
            audio_bitrate: MP3 bitrate (e.g., "128k", "192k", "256k")
            debug: Enable debug output
            verbose: Enable verbose output
        """
        self.silence_between_speakers_ms = silence_between_speakers_ms
        self.audio_bitrate               = audio_bitrate
        self.debug                       = debug
        self.verbose                     = verbose

        # Create silence segment for reuse
        self._silence = AudioSegment.silent(
            duration = self.silence_between_speakers_ms
        )

        if self.debug:
            print( f"[PodcastAudioStitcher] Initialized (silence={silence_between_speakers_ms}ms, bitrate={audio_bitrate})" )

    def pcm_to_audio_segment( self, pcm_bytes: bytes ) -> AudioSegment:
        """
        Convert raw PCM 24000Hz mono bytes to pydub AudioSegment.

        Requires:
            - pcm_bytes is raw PCM audio data
            - Format is 16-bit signed, mono, 24000Hz

        Ensures:
            - Returns AudioSegment with correct sample rate
            - Duration matches input data length

        Args:
            pcm_bytes: Raw PCM audio data

        Returns:
            AudioSegment: Converted audio
        """
        return AudioSegment(
            data         = pcm_bytes,
            sample_width = 2,       # 16-bit = 2 bytes
            frame_rate   = 24000,   # 24kHz sample rate
            channels     = 1,       # Mono
        )

    def stitch_segments(
        self,
        tts_results : List[ TTSSegmentResult ],
        output_path : str,
    ) -> StitchingResult:
        """
        Stitch TTS segment results into a single MP3 file.

        Concatenates all successful segments with silence between
        different speakers. Failed segments create silent gaps.

        Requires:
            - tts_results is a non-empty list
            - output_path parent directory exists or can be created

        Ensures:
            - Creates MP3 file at output_path on success
            - Returns StitchingResult with metadata
            - Skips failed segments (no silent placeholder)

        Args:
            tts_results: List of TTSSegmentResult from TTS client
            output_path: Full path for output MP3 file

        Returns:
            StitchingResult: Result with file info or error
        """
        try:
            if not tts_results:
                return StitchingResult(
                    output_path            = output_path,
                    total_duration_seconds = 0.0,
                    segments_stitched      = 0,
                    file_size_bytes        = 0,
                    success                = False,
                    error_message          = "No segments to stitch",
                )

            # Build the combined audio
            combined     = AudioSegment.empty()
            last_speaker = None
            stitched     = 0

            for result in tts_results:
                # Skip failed segments
                if not result.success or not result.pcm_audio:
                    if self.debug:
                        print( f"[PodcastAudioStitcher] Skipping failed segment {result.segment_index}" )
                    continue

                # Add silence between different speakers
                if last_speaker is not None and last_speaker != result.speaker:
                    combined += self._silence
                    if self.verbose:
                        print( f"[PodcastAudioStitcher] Added {self.silence_between_speakers_ms}ms silence" )

                # Convert PCM to AudioSegment and append
                segment_audio = self.pcm_to_audio_segment( result.pcm_audio )
                combined += segment_audio
                stitched += 1

                last_speaker = result.speaker

                if self.verbose:
                    print( f"[PodcastAudioStitcher] Added segment {result.segment_index}: {result.duration_seconds:.2f}s ({result.speaker})" )

            if stitched == 0:
                return StitchingResult(
                    output_path            = output_path,
                    total_duration_seconds = 0.0,
                    segments_stitched      = 0,
                    file_size_bytes        = 0,
                    success                = False,
                    error_message          = "No successful segments to stitch",
                )

            # Ensure output directory exists
            output_dir = os.path.dirname( output_path )
            if output_dir:
                os.makedirs( output_dir, exist_ok=True )

            # Export as MP3
            combined.export(
                output_path,
                format   = "mp3",
                bitrate  = self.audio_bitrate,
            )

            # Get file size
            file_size = os.path.getsize( output_path )

            # Calculate duration
            duration_seconds = len( combined ) / 1000.0  # pydub uses milliseconds

            if self.debug:
                print( f"[PodcastAudioStitcher] Exported: {output_path}" )
                print( f"[PodcastAudioStitcher] Duration: {duration_seconds:.1f}s, Size: {file_size / 1024:.1f}KB" )

            return StitchingResult(
                output_path            = output_path,
                total_duration_seconds = duration_seconds,
                segments_stitched      = stitched,
                file_size_bytes        = file_size,
                success                = True,
            )

        except Exception as e:
            logger.error( f"Stitching failed: {e}" )
            return StitchingResult(
                output_path            = output_path,
                total_duration_seconds = 0.0,
                segments_stitched      = 0,
                file_size_bytes        = 0,
                success                = False,
                error_message          = str( e ),
            )

    def create_silence_segment( self, duration_ms: int ) -> AudioSegment:
        """
        Create a silent audio segment of specified duration.

        Useful for testing or creating placeholder audio.

        Args:
            duration_ms: Duration in milliseconds

        Returns:
            AudioSegment: Silent audio
        """
        return AudioSegment.silent( duration=duration_ms )


# =============================================================================
# Smoke Test
# =============================================================================

def quick_smoke_test():
    """Quick smoke test for PodcastAudioStitcher."""
    import cosa.utils.util as cu
    import tempfile

    cu.print_banner( "Podcast Audio Stitcher Smoke Test", prepend_nl=True )

    try:
        # Test 1: StitchingResult dataclass
        print( "Testing StitchingResult dataclass..." )
        result = StitchingResult(
            output_path            = "/tmp/test-podcast.mp3",
            total_duration_seconds = 125.5,
            segments_stitched      = 15,
            file_size_bytes        = 1500000,
            success                = True,
        )
        assert result.success is True
        assert result.segments_stitched == 15
        assert result.total_duration_seconds == 125.5
        print( f"  Result: {result.segments_stitched} segments, {result.total_duration_seconds}s" )

        # Test with error
        error_result = StitchingResult(
            output_path            = "/tmp/failed.mp3",
            total_duration_seconds = 0.0,
            segments_stitched      = 0,
            file_size_bytes        = 0,
            success                = False,
            error_message          = "ffmpeg not found",
        )
        assert error_result.success is False
        assert error_result.error_message == "ffmpeg not found"
        print( "  StitchingResult dataclass works correctly" )

        # Test 2: PodcastAudioStitcher instantiation
        print( "Testing PodcastAudioStitcher instantiation..." )
        stitcher = PodcastAudioStitcher(
            silence_between_speakers_ms = 300,
            audio_bitrate               = "192k",
            debug                       = True,
        )
        assert stitcher.silence_between_speakers_ms == 300
        assert stitcher.audio_bitrate == "192k"
        print( "  PodcastAudioStitcher instantiated successfully" )

        # Test 3: PCM to AudioSegment conversion
        print( "Testing PCM to AudioSegment conversion..." )
        # Create 1 second of silent PCM (24000 samples * 2 bytes = 48000 bytes)
        silent_pcm = b"\x00" * 48000
        segment = stitcher.pcm_to_audio_segment( silent_pcm )
        assert len( segment ) == 1000  # 1000ms = 1 second
        assert segment.frame_rate == 24000
        assert segment.channels == 1
        print( f"  Converted: {len( segment )}ms at {segment.frame_rate}Hz" )

        # Test 4: Silence generation
        print( "Testing silence generation..." )
        silence = stitcher.create_silence_segment( 300 )
        assert len( silence ) == 300  # 300ms
        print( f"  Generated {len( silence )}ms of silence" )

        # Test 5: Stitch segments (with simulated TTS results)
        print( "Testing segment stitching..." )

        # Create mock TTS results with actual PCM data
        mock_results = [
            TTSSegmentResult(
                segment_index = 0,
                speaker       = "Nora",
                role          = "curious",
                pcm_audio     = b"\x00" * 24000,  # 0.5s
                success       = True,
            ),
            TTSSegmentResult(
                segment_index = 1,
                speaker       = "Quentin",
                role          = "expert",
                pcm_audio     = b"\x00" * 24000,  # 0.5s
                success       = True,
            ),
            TTSSegmentResult(
                segment_index = 2,
                speaker       = "Nora",
                role          = "curious",
                pcm_audio     = b"\x00" * 24000,  # 0.5s
                success       = True,
            ),
        ]

        # Use temp file
        with tempfile.NamedTemporaryFile( suffix=".mp3", delete=False ) as tmp:
            output_path = tmp.name

        try:
            stitch_result = stitcher.stitch_segments( mock_results, output_path )

            assert stitch_result.success is True
            assert stitch_result.segments_stitched == 3
            # Should be ~1.5s audio + 2x300ms silence = ~2.1s
            assert 2.0 <= stitch_result.total_duration_seconds <= 2.5
            assert stitch_result.file_size_bytes > 0
            print( f"  Stitched: {stitch_result.segments_stitched} segments, {stitch_result.total_duration_seconds:.2f}s" )
            print( f"  Output: {stitch_result.file_size_bytes / 1024:.1f}KB" )

        finally:
            # Clean up temp file
            if os.path.exists( output_path ):
                os.remove( output_path )

        # Test 6: Handle empty results
        print( "Testing empty results handling..." )
        empty_result = stitcher.stitch_segments( [], "/tmp/empty.mp3" )
        assert empty_result.success is False
        assert "No segments" in empty_result.error_message
        print( "  Empty results handled correctly" )

        # Test 7: Handle all-failed results
        print( "Testing all-failed segments handling..." )
        failed_results = [
            TTSSegmentResult(
                segment_index = 0,
                speaker       = "Nora",
                role          = "curious",
                success       = False,
                error_message = "API error",
            ),
        ]
        all_failed = stitcher.stitch_segments( failed_results, "/tmp/failed.mp3" )
        assert all_failed.success is False
        print( "  All-failed segments handled correctly" )

        print( "\n  Podcast Audio Stitcher smoke test completed successfully" )

    except Exception as e:
        print( f"\n  Smoke test failed: {e}" )
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    quick_smoke_test()
