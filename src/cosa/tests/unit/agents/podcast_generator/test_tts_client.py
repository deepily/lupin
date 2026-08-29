#!/usr/bin/env python3
"""
Unit tests for cosa.agents.podcast_generator.tts_client

Targets: TTSSegmentResult / VoiceConfig dataclasses and PodcastTTSClient. The
ElevenLabs WebSocket boundary (websockets.connect) is faked entirely, the
retry/segment loops drive _generate_via_websocket via AsyncMock, and
asyncio.sleep is patched. NO real network / API key / spend.

quick_smoke_test() and __main__ are coverage-excluded.
"""

import json
import base64
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch

import pytest

import cosa.agents.podcast_generator.tts_client as tc
from cosa.agents.podcast_generator.tts_client import (
    TTSSegmentResult,
    VoiceConfig,
    PodcastTTSClient,
)
from cosa.agents.podcast_generator.state import ScriptSegment, PodcastScript


def _run( coro ):
    return asyncio.run( coro )


def _client( **kw ):
    kw.setdefault( "api_key", "test-key" )
    return PodcastTTSClient( **kw )


# ----------------------------------------------------------------------------
# Fake websocket
# ----------------------------------------------------------------------------
class _FakeWS:
    def __init__( self, messages ):
        self._messages = messages
        self.sent      = []

    async def send( self, m ):
        self.sent.append( m )

    async def __aiter__( self ):
        for m in self._messages:
            yield m


class _FakeConnect:
    def __init__( self, ws ):
        self.ws = ws

    async def __aenter__( self ):
        return self.ws

    async def __aexit__( self, *a ):
        return False


def _audio_msg( raw=b"\x01\x02" ):
    return json.dumps( { "audio": base64.b64encode( raw ).decode() } )


# ----------------------------------------------------------------------------
# Dataclasses
# ----------------------------------------------------------------------------
class TestDataclasses:
    """TTSSegmentResult duration auto-calc + VoiceConfig defaults."""

    def test_duration_calculated_from_pcm( self ):
        r = TTSSegmentResult( segment_index=0, speaker="Nora", role="curious", pcm_audio=b"\x00" * 48000 )
        assert r.duration_seconds == 1.0                    # 48000/2/24000

    def test_duration_not_recalculated_when_set( self ):
        r = TTSSegmentResult( segment_index=0, speaker="N", role="curious", pcm_audio=b"\x00" * 48000, duration_seconds=5.0 )
        assert r.duration_seconds == 5.0

    def test_no_pcm_leaves_duration_zero( self ):
        r = TTSSegmentResult( segment_index=0, speaker="N", role="curious" )
        assert r.duration_seconds == 0.0

    def test_voice_config_default_language( self ):
        assert VoiceConfig( voice_id="v", name="n" ).language_code == "en"


# ----------------------------------------------------------------------------
# __init__ key resolution
# ----------------------------------------------------------------------------
class TestInit:
    """
    PodcastTTSClient key resolution (parameter / env / local file) + guards.

    Ensures the three-tier key lookup, the empty-key and exception local-file
    paths, and the debug present/missing status line.
    """

    def test_param_key( self, capsys ):
        c = PodcastTTSClient( api_key="param", debug=True )
        assert c._api_key == "param"
        assert c._key_source == "parameter"
        assert "API key: present (via parameter)" in capsys.readouterr().out

    def test_env_key( self ):
        with patch.dict( "os.environ", { "ELEVENLABS_API_KEY": "env-key" } ):
            c = PodcastTTSClient()
        assert c._api_key == "env-key"
        assert c._key_source == "environment"

    def test_local_file_key_stripped( self ):
        with patch.dict( "os.environ", {}, clear=True ), \
             patch( "cosa.utils.util.get_api_key", return_value="  file-key  " ):
            c = PodcastTTSClient()
        assert c._api_key == "file-key"
        assert c._key_source == "local file"

    def test_local_file_empty_value_leaves_key_none( self, capsys ):
        with patch.dict( "os.environ", {}, clear=True ), \
             patch( "cosa.utils.util.get_api_key", return_value="" ):
            c = PodcastTTSClient( debug=True )
        assert c._api_key is None
        assert "API key: MISSING" in capsys.readouterr().out

    def test_local_file_exception_debug( self, capsys ):
        with patch.dict( "os.environ", {}, clear=True ), \
             patch( "cosa.utils.util.get_api_key", side_effect=RuntimeError( "no file" ) ):
            c = PodcastTTSClient( debug=True )
        assert c._api_key is None
        assert "Could not load local key file" in capsys.readouterr().out

    def test_local_file_exception_no_debug_quiet( self, capsys ):
        with patch.dict( "os.environ", {}, clear=True ), \
             patch( "cosa.utils.util.get_api_key", side_effect=RuntimeError( "x" ) ):
            PodcastTTSClient( debug=False )
        assert capsys.readouterr().out == ""


# ----------------------------------------------------------------------------
# get_voice_config_for_speaker + _load_voice_config_for_speaker
# ----------------------------------------------------------------------------
class TestVoiceConfigResolution:
    """
    Voice-config resolution: caching, speaker->voice-type mapping, language
    prefixing, config_mgr success/fallback ladders, and hardcoded defaults.
    """

    def test_cache_hit_returns_same_object( self, capsys ):
        c = _client( debug=True )
        first  = c.get_voice_config_for_speaker( "Nora" )
        second = c.get_voice_config_for_speaker( "Nora" )
        assert first is second                              # cached
        assert "Voice config for Nora" in capsys.readouterr().out

    def test_defaults_female_when_no_config_mgr( self ):
        cfg = _client().get_voice_config_for_speaker( "Nora" )
        assert cfg.name == "Maria"
        assert cfg.voice_id == "kcQkGnn0HAT2JRDQ4Ljp"

    def test_defaults_male_when_no_config_mgr( self ):
        cfg = _client().get_voice_config_for_speaker( "Quentin" )
        assert cfg.name == "Mr. Radio"
        assert cfg.voice_id == "Aa6nEBJJMKJwJkCx8VU2"

    def test_unknown_speaker_warns_and_defaults_female( self, caplog ):
        cfg = _client().get_voice_config_for_speaker( "Zaphod" )
        assert cfg.name == "Maria"                          # female default

    def test_config_mgr_english_success( self ):
        cm = MagicMock()
        cm.get.side_effect = lambda key, return_type=None: {
            "podcast voice male id"                : "MV1",
            "podcast voice male name"              : "Quentin",
            "podcast voice male stability"         : 0.5,
            "podcast voice male similarity boost"  : 0.6,
            "podcast voice male style"             : 0.7,
        }[ key ]
        cfg = _client( config_mgr=cm ).get_voice_config_for_speaker( "Quentin", language="en" )
        assert cfg.voice_id == "MV1"
        assert cfg.stability == 0.5
        assert cfg.language_code == "en"

    def test_config_mgr_language_specific_success( self ):
        cm = MagicMock()
        cm.get.side_effect = lambda key, return_type=None: {
            "podcast voice spanish female id"               : "ESV",
            "podcast voice spanish female name"             : "Sofia",
            "podcast voice spanish female stability"        : 0.6,
            "podcast voice spanish female similarity boost" : 0.7,
            "podcast voice spanish female style"            : 0.4,
        }[ key ]
        cfg = _client( config_mgr=cm ).get_voice_config_for_speaker( "Nora", language="es-MX" )
        assert cfg.voice_id == "ESV"
        assert cfg.name == "Sofia"
        assert cfg.language_code == "es-MX"

    def test_language_specific_fails_then_english_fallback( self ):
        cm = MagicMock()
        def _get( key, return_type=None ):
            if "spanish" in key:
                raise KeyError( "no spanish config" )
            return {
                "podcast voice female id"               : "ENV",
                "podcast voice female name"             : "Nora",
                "podcast voice female stability"        : 0.6,
                "podcast voice female similarity boost" : 0.7,
                "podcast voice female style"            : 0.4,
            }[ key ]
        cm.get.side_effect = _get
        cfg = _client( config_mgr=cm ).get_voice_config_for_speaker( "Nora", language="es-MX" )
        assert cfg.voice_id == "ENV"                        # fell back to English keys
        assert cfg.language_code == "es-MX"

    def test_english_config_fails_then_hardcoded_default( self ):
        cm = MagicMock()
        cm.get.side_effect = RuntimeError( "config blew up" )
        cfg = _client( config_mgr=cm ).get_voice_config_for_speaker( "Quentin", language="en" )
        assert cfg.voice_id == "Aa6nEBJJMKJwJkCx8VU2"       # hardcoded male default


class TestLanguageHelpers:
    """_get_language_prefix + _get_model_for_language mappings."""

    @pytest.mark.parametrize( "lang,prefix", [
        ( "en", "" ), ( "es", "spanish" ), ( "es-MX", "spanish" ), ( "fr", "" ),
    ] )
    def test_language_prefix( self, lang, prefix ):
        assert _client()._get_language_prefix( lang ) == prefix

    def test_model_for_language( self ):
        c = _client()
        assert c._get_model_for_language( "en" )    == "eleven_turbo_v2_5"
        assert c._get_model_for_language( "es-MX" ) == "eleven_multilingual_v2"


# ----------------------------------------------------------------------------
# _clean_text_for_tts
# ----------------------------------------------------------------------------
class TestCleanText:
    """_clean_text_for_tts strips prosody markers + collapses whitespace."""

    def test_strips_prosody_and_collapses_whitespace( self ):
        out = _client()._clean_text_for_tts( "So *[pause]* what    you're *[excited]* saying!" )
        assert out == "So what you're saying!"

    def test_preserves_pause_markers_and_strips_dead_tags( self ):
        # <break>, ellipsis and CAPS survive; only *[...]* is removed.
        out = _client()._clean_text_for_tts(
            'Wait *[excited]* for it... <break time="1.5s"/> HUGE news!'
        )
        assert '<break time="1.5s"/>' in out
        assert "..." in out
        assert "HUGE" in out
        assert "*[" not in out


# ----------------------------------------------------------------------------
# _generate_via_websocket
# ----------------------------------------------------------------------------
class TestGenerateViaWebsocket:
    """
    _generate_via_websocket message protocol with a faked WebSocket.

    Ensures: audio chunks decode+join; isFinal breaks; error message raises;
    non-JSON message is skipped (warning); language_code added only for non-en.
    """

    def _patch_connect( self, ws ):
        return patch.object( tc.websockets, "connect", MagicMock( return_value=_FakeConnect( ws ) ) )

    def test_collects_audio_until_final( self ):
        ws = _FakeWS( [ _audio_msg( b"\x01\x02" ), _audio_msg( b"\x03\x04" ), json.dumps( { "isFinal": True } ) ] )
        c  = _client()
        vc = VoiceConfig( voice_id="v", name="n", language_code="en" )
        with self._patch_connect( ws ):
            out = _run( c._generate_via_websocket( "hello", vc ) )
        assert out == b"\x01\x02\x03\x04"
        # en -> no language_code in config message
        config_sent = json.loads( ws.sent[ 0 ] )
        assert "language_code" not in config_sent

    def test_url_enables_ssml_parsing( self ):
        # enable_ssml_parsing=true must reach websockets.connect so <break>
        # pause tags render on the stream-input endpoint.
        assert "enable_ssml_parsing=true" in tc.PodcastTTSClient.WS_URL_TEMPLATE
        ws          = _FakeWS( [ json.dumps( { "isFinal": True } ) ] )
        connect_mock = MagicMock( return_value=_FakeConnect( ws ) )
        c  = _client()
        vc = VoiceConfig( voice_id="v", name="n", language_code="en" )
        with patch.object( tc.websockets, "connect", connect_mock ):
            _run( c._generate_via_websocket( "hello", vc ) )
        built_url = connect_mock.call_args[ 0 ][ 0 ]
        assert "enable_ssml_parsing=true" in built_url

    def test_non_english_adds_language_code( self ):
        ws = _FakeWS( [ json.dumps( { "isFinal": True } ) ] )
        c  = _client()
        vc = VoiceConfig( voice_id="v", name="n", language_code="es-MX" )
        with self._patch_connect( ws ):
            _run( c._generate_via_websocket( "hola", vc ) )
        assert json.loads( ws.sent[ 0 ] )[ "language_code" ] == "es-MX"

    def test_error_message_raises( self ):
        ws = _FakeWS( [ json.dumps( { "error": "quota exceeded" } ) ] )
        c  = _client()
        vc = VoiceConfig( voice_id="v", name="n" )
        with self._patch_connect( ws ):
            with pytest.raises( Exception, match="ElevenLabs error: quota exceeded" ):
                _run( c._generate_via_websocket( "x", vc ) )

    def test_neutral_message_skipped_and_loop_exhausts_without_final( self ):
        # A valid-JSON message with no audio/isFinal/error falls through all
        # branches (553->542); the stream ends with no isFinal so the async-for
        # exhausts naturally (542->559) and the collected audio is returned.
        ws = _FakeWS( [ json.dumps( { "info": "keepalive" } ), _audio_msg( b"\x07\x08" ) ] )
        c  = _client()
        vc = VoiceConfig( voice_id="v", name="n" )
        with self._patch_connect( ws ):
            out = _run( c._generate_via_websocket( "x", vc ) )
        assert out == b"\x07\x08"

    def test_non_json_message_skipped( self ):
        ws = _FakeWS( [ "<<not json>>", _audio_msg( b"\xaa\xbb" ), json.dumps( { "isFinal": True } ) ] )
        c  = _client()
        vc = VoiceConfig( voice_id="v", name="n" )
        with self._patch_connect( ws ):
            out = _run( c._generate_via_websocket( "x", vc ) )
        assert out == b"\xaa\xbb"


# ----------------------------------------------------------------------------
# generate_segment_audio retry loop
# ----------------------------------------------------------------------------
class TestGenerateSegmentAudio:
    """
    generate_segment_audio guards + retry ladder.

    Ensures: missing key / empty-cleaned-text early returns; success on first
    attempt; failure-then-success with retry_callback; retry_callback failure
    swallowed; total failure after max_retries.
    """

    def _seg( self, text="Hello there", speaker="Nora", role="curious" ):
        return ScriptSegment( speaker=speaker, role=role, text=text )

    def test_missing_api_key_returns_failure( self ):
        c = PodcastTTSClient( api_key=None )
        c._api_key = None
        out = _run( c.generate_segment_audio( self._seg(), 0 ) )
        assert out.success is False
        assert out.error_message == "ELEVENLABS_API_KEY not set"

    def test_empty_text_after_clean_returns_failure( self ):
        c = _client()
        out = _run( c.generate_segment_audio( self._seg( text="*[pause]*" ), 0 ) )
        assert out.success is False
        assert out.error_message == "Empty text after cleaning"

    def test_success_first_attempt( self ):
        c = _client()
        c._generate_via_websocket = AsyncMock( return_value=b"\x00" * 100 )
        out = _run( c.generate_segment_audio( self._seg(), 2 ) )
        assert out.success is True
        assert out.segment_index   == 2
        assert out.retry_count     == 0
        assert out.character_count == len( "Hello there" )

    def test_failure_then_success_invokes_retry_callback( self ):
        seen = []
        async def retry_cb( idx, attempt, max_a, speaker ):
            seen.append( ( idx, attempt, max_a, speaker ) )
        c = _client( retry_callback=retry_cb, max_retries=3 )
        c._generate_via_websocket = AsyncMock( side_effect=[ RuntimeError( "blip" ), b"\x00" * 10 ] )
        with patch( "asyncio.sleep", AsyncMock() ) as slp:
            out = _run( c.generate_segment_audio( self._seg(), 0 ) )
        assert out.success is True
        assert out.retry_count == 1
        assert seen == [ ( 0, 2, 3, "Nora" ) ]              # attempt+2, max
        slp.assert_awaited_once()

    def test_retry_callback_failure_is_swallowed( self ):
        async def bad_cb( *a ):
            raise RuntimeError( "cb down" )
        c = _client( retry_callback=bad_cb, max_retries=2 )
        c._generate_via_websocket = AsyncMock( side_effect=[ RuntimeError( "blip" ), b"\x00" ] )
        with patch( "asyncio.sleep", AsyncMock() ):
            out = _run( c.generate_segment_audio( self._seg(), 0 ) )
        assert out.success is True                          # callback failure didn't abort

    def test_all_attempts_fail_returns_failure( self ):
        c = _client( max_retries=2 )
        c._generate_via_websocket = AsyncMock( side_effect=RuntimeError( "always down" ) )
        with patch( "asyncio.sleep", AsyncMock() ):
            out = _run( c.generate_segment_audio( self._seg(), 1 ) )
        assert out.success is False
        assert "Failed after 2 attempts" in out.error_message
        assert out.retry_count == 2


# ----------------------------------------------------------------------------
# generate_all_segments
# ----------------------------------------------------------------------------
class TestGenerateAllSegments:
    """
    generate_all_segments sequential loop + progress + failure summary.

    Ensures results/failed_indices accounting, progress_callback invocation and
    error-swallow, and debug diagnostics including the first-error summary.
    """

    def _script( self ):
        return PodcastScript(
            title="T", research_source="/r.md", host_a_name="Nora", host_b_name="Quentin",
            segments=[
                ScriptSegment( speaker="Nora", role="curious", text="a b" ),
                ScriptSegment( speaker="Quentin", role="expert", text="c d" ),
            ],
        )

    def _result( self, idx, speaker, ok, err=None ):
        return TTSSegmentResult(
            segment_index=idx, speaker=speaker, role="curious",
            success=ok, error_message=err, pcm_audio=( b"\x00" * 10 if ok else b"" ),
        )

    def test_mixed_results_with_progress_and_debug( self, capsys ):
        prog = []
        async def progress( cur, total, speaker, eta ):
            prog.append( ( cur, total, speaker ) )
        c = _client( progress_callback=progress, debug=True )
        c.generate_segment_audio = AsyncMock( side_effect=[
            self._result( 0, "Nora", True ),
            self._result( 1, "Quentin", False, err="boom" ),
        ] )
        results, failed = _run( c.generate_all_segments( self._script() ) )
        assert len( results ) == 2
        assert failed == [ 1 ]
        assert prog == [ ( 1, 2, "Nora" ), ( 2, 2, "Quentin" ) ]
        out = capsys.readouterr().out
        assert "Complete: 1/2 segments" in out
        assert "1 segments failed. First error: boom" in out
        assert "Segment 2 failed: boom" in out             # debug failure line

    def test_progress_callback_failure_swallowed( self ):
        async def bad_progress( *a ):
            raise RuntimeError( "prog down" )
        c = _client( progress_callback=bad_progress )
        c.generate_segment_audio = AsyncMock( return_value=self._result( 0, "Nora", True ) )
        script = PodcastScript(
            title="T", research_source="/r.md", host_a_name="N", host_b_name="Q",
            segments=[ ScriptSegment( speaker="Nora", role="curious", text="a" ) ],
        )
        results, failed = _run( c.generate_all_segments( script ) )
        assert len( results ) == 1
        assert failed == []                                 # callback failure didn't break loop

    def test_failed_segment_debug_false_skips_failure_print( self, capsys ):
        # failed segment with debug=False exercises the 628->632 skip arc.
        c = _client( debug=False )
        c.generate_segment_audio = AsyncMock( side_effect=[
            self._result( 0, "Nora", True ),
            self._result( 1, "Quentin", False, err="boom" ),
        ] )
        results, failed = _run( c.generate_all_segments( self._script() ) )
        assert failed == [ 1 ]
        out = capsys.readouterr().out
        assert "Segment 2 failed:" not in out               # debug-off: no per-segment failure line
        assert "Complete: 1/2 segments" in out              # summary still prints

    def test_all_success_no_failure_summary( self, capsys ):
        c = _client( debug=False )
        c.generate_segment_audio = AsyncMock( side_effect=[
            self._result( 0, "Nora", True ),
            self._result( 1, "Quentin", True ),
        ] )
        results, failed = _run( c.generate_all_segments( self._script() ) )
        assert failed == []
        out = capsys.readouterr().out
        assert "Complete: 2/2 segments" in out
        assert "segments failed" not in out                 # no failure summary branch
