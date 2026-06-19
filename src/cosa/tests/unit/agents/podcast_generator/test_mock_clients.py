#!/usr/bin/env python3
"""
Unit tests for cosa.agents.podcast_generator.mock_clients

Targets: MockCostEstimate, MockPodcastAPIClient, MockTTSSegmentResult,
MockTTSClient — the dry-run stand-ins. These are already mock objects, so the
only boundary is asyncio.sleep (patched to avoid real latency). No network /
API / disk.

quick_smoke_test() and __main__ are coverage-excluded.
"""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from cosa.agents.podcast_generator.mock_clients import (
    MockCostEstimate,
    MockPodcastAPIClient,
    MockTTSClient,
    MockTTSSegmentResult,
    MOCK_SCRIPT_RESPONSE,
)


def _run( coro ):
    return asyncio.run( coro )


class TestMockCostEstimate:
    """MockCostEstimate.add_usage increments call count at zero cost."""

    def test_add_usage_increments_calls_only( self ):
        ce = MockCostEstimate()
        ce.add_usage( "claude", 100, 50 )
        ce.add_usage( "claude", 10, 5 )
        assert ce.total_api_calls    == 2
        assert ce.estimated_cost_usd == 0.0
        assert ce.total_input_tokens == 0       # mock never accrues tokens


class TestMockPodcastAPIClient:
    """
    MockPodcastAPIClient canned responses + call counting.

    Ensures generate_script / call_with_json_output / revise_script each bump
    call_count, return the canned schema (with language stamping where
    applicable), and that debug output prints when enabled.
    """

    def test_init_defaults( self ):
        c = MockPodcastAPIClient()
        assert c.call_count == 0
        assert isinstance( c.cost_estimate, MockCostEstimate )

    def test_generate_script_stamps_language_and_counts( self, capsys ):
        c = MockPodcastAPIClient( debug=True )
        with patch( "asyncio.sleep", AsyncMock() ) as slp:
            out = _run( c.generate_script( "research", language_code="es" ) )
        assert out[ "language_code" ] == "es"
        assert out[ "title" ] == MOCK_SCRIPT_RESPONSE[ "title" ]
        assert c.call_count == 1
        slp.assert_awaited_once()
        assert "generate_script()" in capsys.readouterr().out

    def test_generate_script_debug_false_quiet( self, capsys ):
        c = MockPodcastAPIClient( debug=False )
        with patch( "asyncio.sleep", AsyncMock() ):
            _run( c.generate_script( "research" ) )
        assert capsys.readouterr().out == ""

    def test_call_with_json_output_counts_and_debug( self, capsys ):
        c = MockPodcastAPIClient( debug=True )
        with patch( "asyncio.sleep", AsyncMock() ):
            out = _run( c.call_with_json_output( messages=[ { "role": "user", "content": "x" } ] ) )
        assert out is MOCK_SCRIPT_RESPONSE
        assert c.call_count == 1
        assert "call_with_json_output()" in capsys.readouterr().out

    def test_call_with_json_output_debug_false_quiet( self, capsys ):
        c = MockPodcastAPIClient( debug=False )
        with patch( "asyncio.sleep", AsyncMock() ):
            _run( c.call_with_json_output( messages=[] ) )
        assert capsys.readouterr().out == ""

    def test_revise_script_modifies_title( self, capsys ):
        c = MockPodcastAPIClient( debug=True )
        with patch( "asyncio.sleep", AsyncMock() ):
            out = _run( c.revise_script( { "title": "orig" }, feedback="make it punchier", language_code="fr" ) )
        assert out[ "title" ] == "Mock Podcast: Revised (Dry Run)"
        assert out[ "language_code" ] == "fr"
        assert c.call_count == 1
        assert "revise_script()" in capsys.readouterr().out

    def test_revise_script_debug_false_quiet( self, capsys ):
        c = MockPodcastAPIClient( debug=False )
        with patch( "asyncio.sleep", AsyncMock() ):
            _run( c.revise_script( { "title": "orig" }, feedback="x" ) )
        assert capsys.readouterr().out == ""


class TestMockTTSSegmentResult:
    """MockTTSSegmentResult defaults match the dry-run success contract."""

    def test_defaults( self ):
        r = MockTTSSegmentResult( segment_index=0, speaker="Alex", role="curious" )
        assert r.pcm_audio     == b""
        assert r.success       is True
        assert r.error_message is None
        assert r.retry_count   == 0


class TestMockTTSClient:
    """
    MockTTSClient silence generation + segment simulation.

    Ensures the PCM silence length formula, per-segment result fields, the
    progress_callback invocation (present vs absent), and generate_all_segments
    loop + debug totals.
    """

    class _Seg:
        def __init__( self, speaker, role, dialogue ):
            self.speaker  = speaker
            self.role     = role
            self.dialogue = dialogue

    def test_generate_silence_pcm_length( self ):
        c = MockTTSClient()
        # 24000 samples/sec * 2 bytes/sample * 1.0s
        assert len( c._generate_silence_pcm( 1.0 ) ) == 24000 * 2
        assert len( c._generate_silence_pcm( 0.5 ) ) == int( 24000 * 0.5 ) * 2

    def test_generate_segment_with_progress_callback_and_debug( self, capsys ):
        seen = []
        async def progress( idx, total, speaker, eta ):
            seen.append( ( idx, total, speaker, eta ) )
        c = MockTTSClient( progress_callback=progress, debug=True )
        seg = self._Seg( "Alex", "curious", "one two three four five" )
        with patch( "asyncio.sleep", AsyncMock() ):
            result = _run( c.generate_segment( seg, segment_index=0, total_segments=2 ) )
        assert result.speaker == "Alex"
        assert result.role    == "curious"
        assert result.character_count == len( "one two three four five" )
        assert result.success is True
        assert c.segment_count == 1
        # progress callback fired with (idx+1, total, speaker, eta)
        assert seen == [ ( 1, 2, "Alex", ( 2 - 0 - 1 ) * 0.3 ) ]
        assert "Segment 1/2: Alex" in capsys.readouterr().out

    def test_generate_segment_without_callback( self ):
        c = MockTTSClient( progress_callback=None )
        seg = self._Seg( "Jordan", "expert", "hi" )
        with patch( "asyncio.sleep", AsyncMock() ):
            result = _run( c.generate_segment( seg, segment_index=1, total_segments=3 ) )
        # short text -> duration floored at 1.0s
        assert result.duration_seconds == 1.0
        assert result.segment_index    == 1

    def test_generate_all_segments_loops_and_debug( self, capsys ):
        c = MockTTSClient( debug=True )

        class _Script:
            segments = [
                TestMockTTSClient._Seg( "Alex", "curious", "a b c" ),
                TestMockTTSClient._Seg( "Jordan", "expert", "d e" ),
            ]
        with patch( "asyncio.sleep", AsyncMock() ):
            results = _run( c.generate_all_segments( _Script(), language_code="es" ) )
        assert len( results ) == 2
        assert c.segment_count == 2
        out = capsys.readouterr().out
        assert "Generating 2 segments in es" in out
        assert "Complete:" in out

    def test_generate_all_segments_debug_false_quiet( self, capsys ):
        c = MockTTSClient( debug=False )

        class _Script:
            segments = [ TestMockTTSClient._Seg( "Alex", "curious", "a b" ) ]
        with patch( "asyncio.sleep", AsyncMock() ):
            results = _run( c.generate_all_segments( _Script() ) )
        assert len( results ) == 1
        assert capsys.readouterr().out == ""
