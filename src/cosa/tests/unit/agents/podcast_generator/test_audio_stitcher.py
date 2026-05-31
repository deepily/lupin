#!/usr/bin/env python3
"""
Unit tests for cosa.agents.podcast_generator.audio_stitcher

Target: StitchingResult + PodcastAudioStitcher. pydub in-memory ops (silent /
empty / PCM->segment / concatenation / len) are pure and used for real; the
only boundaries — AudioSegment.export (ffmpeg subprocess + file write),
os.makedirs, os.path.getsize — are mocked so NO subprocess / disk write occurs.

quick_smoke_test() and __main__ are coverage-excluded.
"""

from unittest.mock import patch, MagicMock

import pytest
from pydub import AudioSegment

from cosa.agents.podcast_generator.audio_stitcher import (
    StitchingResult,
    PodcastAudioStitcher,
)
from cosa.agents.podcast_generator.tts_client import TTSSegmentResult


def _seg( index, speaker, *, success=True, pcm=b"\x00" * 24000, role="curious" ):
    return TTSSegmentResult(
        segment_index = index,
        speaker       = speaker,
        role          = role,
        pcm_audio     = pcm,
        success       = success,
    )


class TestStitchingResult:
    """StitchingResult dataclass — error_message defaults to None."""

    def test_defaults( self ):
        r = StitchingResult(
            output_path="/tmp/x.mp3", total_duration_seconds=10.0,
            segments_stitched=3, file_size_bytes=999, success=True,
        )
        assert r.error_message is None
        assert r.success is True


class TestInit:
    """PodcastAudioStitcher init stores params, builds reusable silence, debug print."""

    def test_init_and_debug( self, capsys ):
        s = PodcastAudioStitcher( silence_between_speakers_ms=250, audio_bitrate="128k", debug=True )
        assert s.silence_between_speakers_ms == 250
        assert s.audio_bitrate == "128k"
        assert len( s._silence ) == 250          # reusable silence segment built
        assert "[PodcastAudioStitcher] Initialized" in capsys.readouterr().out

    def test_init_no_debug_quiet( self, capsys ):
        PodcastAudioStitcher( debug=False )
        assert capsys.readouterr().out == ""


class TestPcmHelpers:
    """pcm_to_audio_segment + create_silence_segment produce correct in-memory audio."""

    def test_pcm_to_audio_segment( self ):
        s = PodcastAudioStitcher()
        seg = s.pcm_to_audio_segment( b"\x00" * 48000 )   # 24000 samples * 2 bytes = 1s
        assert len( seg ) == 1000                          # ms
        assert seg.frame_rate == 24000
        assert seg.channels   == 1

    def test_create_silence_segment( self ):
        s = PodcastAudioStitcher()
        assert len( s.create_silence_segment( 300 ) ) == 300


class TestStitchSegments:
    """
    stitch_segments concatenation + export branches.

    Ensures: empty input -> failure; all-failed -> failure; happy path with a
    speaker change inserts silence + exports (mocked); no-dir output skips
    makedirs; export exception -> failure with error_message.
    """

    def test_empty_results_returns_failure( self ):
        s = PodcastAudioStitcher()
        r = s.stitch_segments( [], "/tmp/out.mp3" )
        assert r.success is False
        assert r.error_message == "No segments to stitch"
        assert r.segments_stitched == 0

    def test_all_failed_segments_returns_failure( self, capsys ):
        # one success=False, one success=True but empty pcm -> both skipped
        s = PodcastAudioStitcher( debug=True )
        results = [
            _seg( 0, "Nora", success=False ),
            _seg( 1, "Nora", success=True, pcm=b"" ),
        ]
        r = s.stitch_segments( results, "/tmp/out.mp3" )
        assert r.success is False
        assert r.error_message == "No successful segments to stitch"
        assert "Skipping failed segment" in capsys.readouterr().out

    def test_happy_path_with_speaker_change_exports( self, capsys ):
        s = PodcastAudioStitcher( debug=True, verbose=True )
        results = [
            _seg( 0, "Nora" ),
            _seg( 1, "Nora" ),       # same speaker -> no silence
            _seg( 2, "Quentin" ),    # speaker change -> silence inserted
        ]
        with patch.object( AudioSegment, "export" ) as exp, \
             patch( "os.makedirs" ) as mkd, \
             patch( "os.path.getsize", return_value=4096 ):
            r = s.stitch_segments( results, "/io/pod/out.mp3" )
        assert r.success is True
        assert r.segments_stitched == 3
        assert r.file_size_bytes   == 4096
        assert r.total_duration_seconds > 0
        exp.assert_called_once()
        mkd.assert_called_once_with( "/io/pod", exist_ok=True )
        out = capsys.readouterr().out
        assert "Added 300ms silence" in out          # verbose, speaker-change branch
        assert "Exported:" in out                     # debug

    def test_output_path_without_dir_skips_makedirs( self ):
        s = PodcastAudioStitcher()
        with patch.object( AudioSegment, "export" ), \
             patch( "os.makedirs" ) as mkd, \
             patch( "os.path.getsize", return_value=10 ):
            r = s.stitch_segments( [ _seg( 0, "Nora" ) ], "out.mp3" )   # dirname("") -> falsy
        assert r.success is True
        mkd.assert_not_called()

    def test_export_exception_returns_failure( self ):
        s = PodcastAudioStitcher()
        with patch.object( AudioSegment, "export", side_effect=RuntimeError( "ffmpeg missing" ) ), \
             patch( "os.makedirs" ):
            r = s.stitch_segments( [ _seg( 0, "Nora" ) ], "/io/pod/out.mp3" )
        assert r.success is False
        assert "ffmpeg missing" in r.error_message
        assert r.segments_stitched == 0

    def test_all_failed_segments_debug_false_skips_print( self, capsys ):
        # debug=False exercises the 174->176 skip arc (no "Skipping" print).
        s = PodcastAudioStitcher( debug=False )
        r = s.stitch_segments( [ _seg( 0, "Nora", success=False ) ], "/tmp/out.mp3" )
        assert r.success is False
        assert "Skipping failed segment" not in capsys.readouterr().out

    def test_speaker_change_verbose_false_skips_silence_print( self, capsys ):
        # verbose=False + speaker change exercises the 181->185 skip arc.
        s = PodcastAudioStitcher( debug=False, verbose=False )
        results = [ _seg( 0, "Nora" ), _seg( 1, "Quentin" ) ]
        with patch.object( AudioSegment, "export" ), \
             patch( "os.makedirs" ), \
             patch( "os.path.getsize", return_value=2048 ):
            r = s.stitch_segments( results, "/io/pod/out.mp3" )
        assert r.success is True
        assert r.segments_stitched == 2
        assert "silence" not in capsys.readouterr().out
