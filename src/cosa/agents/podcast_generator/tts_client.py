#!/usr/bin/env python3
"""
TTS Client for COSA Podcast Generator Agent - Phase 2.

Handles ElevenLabs WebSocket TTS generation for podcast dialogue segments.
Uses voice IDs from ConfigurationManager for speaker-to-voice mapping.

Design Pattern: WebSocket streaming with retry logic
- Connects to ElevenLabs streaming API
- Collects PCM 24000Hz audio bytes
- Maps speaker names to voice configurations
- Provides progress callbacks for UI notification
"""

import asyncio
import base64
import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Optional, Callable, Awaitable, List, Tuple

import websockets

from .state import ScriptSegment, PodcastScript

logger = logging.getLogger( __name__ )


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class TTSSegmentResult:
    """
    Result of TTS generation for a single podcast segment.

    Contains the raw PCM audio bytes and metadata about the generation.

    Requires:
        - segment_index is a non-negative integer
        - speaker is a non-empty string
        - role is "curious" or "expert"

    Ensures:
        - success is True if pcm_audio contains valid audio
        - duration_seconds is calculated from PCM byte length
    """

    segment_index    : int
    speaker          : str
    role             : str
    pcm_audio        : bytes            = b""
    duration_seconds : float            = 0.0
    character_count  : int              = 0      # For audio cost tracking
    success          : bool             = False
    error_message    : Optional[ str ]  = None
    retry_count      : int              = 0

    def __post_init__( self ):
        """Calculate duration from PCM audio if not set."""
        if self.pcm_audio and self.duration_seconds == 0.0:
            # PCM 24000Hz, 16-bit mono = 2 bytes per sample
            samples = len( self.pcm_audio ) // 2
            self.duration_seconds = samples / 24000.0


@dataclass
class VoiceConfig:
    """
    Voice configuration for TTS generation.

    Loaded from ConfigurationManager settings.

    Requires:
        - voice_id is a valid ElevenLabs voice ID
        - All numeric values are in valid ranges (0.0-1.0)
        - language_code is a valid ISO language code
    """

    voice_id         : str
    name             : str
    language_code    : str   = "en"  # ISO language code (en, es, es-MX, etc.)
    stability        : float = 0.65
    similarity_boost : float = 0.75
    style            : float = 0.35


# =============================================================================
# TTS Client Class
# =============================================================================

class PodcastTTSClient:
    """
    ElevenLabs TTS client for podcast audio generation.

    Handles WebSocket streaming to ElevenLabs API and collects PCM audio
    for each dialogue segment. Maps speaker names to voice configurations.

    Requires:
        - ELEVENLABS_API_KEY environment variable is set
        - Voice configurations are available via ConfigurationManager

    Ensures:
        - Returns TTSSegmentResult for each segment
        - Retries failed segments up to max_retries times
        - Calls progress_callback to report generation progress
    """

    # ElevenLabs WebSocket URL template.
    # enable_ssml_parsing=true is REQUIRED for <break time="x.xs"/> pause tags to
    # render on the stream-input endpoint (default off → tags spoken/ignored).
    # Pause-only prosody per Rick's 2026-08-15 ruling; expressive audio tags are
    # Eleven v3 only and out of scope for our turbo/multilingual models.
    WS_URL_TEMPLATE = (
        "wss://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream-input"
        "?model_id={model_id}&output_format=pcm_24000&enable_ssml_parsing=true"
    )

    def __init__(
        self,
        config_mgr         = None,
        api_key            : Optional[ str ] = None,
        progress_callback  : Optional[ Callable[ [ int, int, str, float ], Awaitable[ None ] ] ] = None,
        retry_callback     : Optional[ Callable[ [ int, int, int, str ], Awaitable[ None ] ] ] = None,
        debug              : bool = False,
        verbose            : bool = False,
        max_retries        : int  = 3,
        retry_base_delay   : float = 1.0,
    ):
        """
        Initialize the TTS client.

        Args:
            config_mgr: ConfigurationManager instance for voice settings
            api_key: Optional explicit API key (highest priority)
            progress_callback: Async callback(current, total, speaker, eta_seconds) for progress
            retry_callback: Async callback(segment_index, attempt, max_attempts, speaker) for retries
            debug: Enable debug output
            verbose: Enable verbose output
            max_retries: Maximum retry attempts per segment
            retry_base_delay: Base delay in seconds for exponential backoff
        """
        self.config_mgr        = config_mgr
        self.progress_callback = progress_callback
        self.retry_callback    = retry_callback
        self.debug             = debug
        self.verbose           = verbose
        self.max_retries       = max_retries
        self.retry_base_delay  = retry_base_delay

        # Cache voice configurations
        self._voice_cache: dict[ str, VoiceConfig ] = {}

        # Get API key using three-tier priority (matches api_client.py pattern)
        self._api_key    = api_key
        self._key_source = "parameter"

        if not self._api_key:
            self._api_key    = os.getenv( "ELEVENLABS_API_KEY" )
            self._key_source = "environment"

        if not self._api_key:
            try:
                import cosa.utils.util as cu
                key_value = cu.get_api_key( "eleven11" )
                if key_value:
                    self._api_key    = key_value.strip()
                    self._key_source = "local file"
            except Exception as e:
                if self.debug:
                    print( f"[PodcastTTSClient] Could not load local key file: {e}" )

        if self.debug:
            key_status = f"present (via {self._key_source})" if self._api_key else "MISSING"
            print( f"[PodcastTTSClient] Initialized (API key: {key_status})" )

    def get_voice_config_for_speaker( self, speaker: str, language: str = "en" ) -> VoiceConfig:
        """
        Get voice configuration for a speaker name in specified language.

        Maps speaker names to voice configurations from config:
        - "Maria" → podcast voice female config
        - "Mr. Radio" → podcast voice male config

        For non-English languages, uses language-specific voices if configured,
        otherwise falls back to English voices with multilingual model.

        Requires:
            - speaker is a non-empty string
            - language is a valid ISO language code
            - config_mgr is set if using dynamic config

        Ensures:
            - Returns VoiceConfig for the speaker and language
            - Falls back to English voices if language-specific not available
            - Sets language_code in returned config

        Args:
            speaker: Speaker name from script segment
            language: ISO language code (e.g., "en", "es-MX")

        Returns:
            VoiceConfig: Voice configuration for TTS
        """
        # Cache key includes language
        cache_key = f"{speaker}:{language}"

        # Check cache
        if cache_key in self._voice_cache:
            return self._voice_cache[ cache_key ]

        # Load from config
        config = self._load_voice_config_for_speaker( speaker, language )
        self._voice_cache[ cache_key ] = config

        if self.debug:
            print( f"[PodcastTTSClient] Voice config for {speaker} ({language}): {config.name} ({config.voice_id[ :8 ]}...)" )

        return config

    def _load_voice_config_for_speaker( self, speaker: str, language: str = "en" ) -> VoiceConfig:
        """
        Load voice configuration from ConfigurationManager.

        For non-English languages, attempts to load language-specific voices.
        Falls back to English voices with language_code set for multilingual model.

        Args:
            speaker: Speaker name
            language: ISO language code (e.g., "en", "es-MX")

        Returns:
            VoiceConfig: Loaded or default configuration with language_code set
        """
        # Determine voice type based on speaker name
        speaker_lower = speaker.lower()

        # Map common curious host names to female voice
        if speaker_lower in [ "maria", "nora", "alex", "curious" ]:
            voice_type = "female"
        # Map common expert host names to male voice
        elif speaker_lower in [ "mr radio", "mr. radio", "quentin", "jordan", "expert" ]:
            voice_type = "male"
        else:
            # Default to female for unknown speakers
            voice_type = "female"
            logger.warning( f"Unknown speaker '{speaker}', defaulting to female voice" )

        # Determine language prefix for config keys (es-MX → spanish, en → empty)
        lang_prefix = self._get_language_prefix( language )

        # Try to load from config_mgr
        if self.config_mgr:
            # First try language-specific voice (e.g., "podcast voice spanish female id")
            if lang_prefix:
                try:
                    voice_id = self.config_mgr.get( f"podcast voice {lang_prefix} {voice_type} id" )
                    name     = self.config_mgr.get( f"podcast voice {lang_prefix} {voice_type} name" )
                    stability = self.config_mgr.get(
                        f"podcast voice {lang_prefix} {voice_type} stability",
                        return_type = "float"
                    )
                    similarity = self.config_mgr.get(
                        f"podcast voice {lang_prefix} {voice_type} similarity boost",
                        return_type = "float"
                    )
                    style = self.config_mgr.get(
                        f"podcast voice {lang_prefix} {voice_type} style",
                        return_type = "float"
                    )

                    return VoiceConfig(
                        voice_id         = voice_id,
                        name             = name,
                        language_code    = language,
                        stability        = stability,
                        similarity_boost = similarity,
                        style            = style,
                    )
                except Exception as e:
                    logger.debug( f"No {lang_prefix} voice config found, falling back to English: {e}" )

            # Try English voice (original config keys)
            try:
                voice_id = self.config_mgr.get( f"podcast voice {voice_type} id" )
                name     = self.config_mgr.get( f"podcast voice {voice_type} name" )
                stability = self.config_mgr.get(
                    f"podcast voice {voice_type} stability",
                    return_type = "float"
                )
                similarity = self.config_mgr.get(
                    f"podcast voice {voice_type} similarity boost",
                    return_type = "float"
                )
                style = self.config_mgr.get(
                    f"podcast voice {voice_type} style",
                    return_type = "float"
                )

                return VoiceConfig(
                    voice_id         = voice_id,
                    name             = name,
                    language_code    = language,  # Use requested language for multilingual model
                    stability        = stability,
                    similarity_boost = similarity,
                    style            = style,
                )
            except Exception as e:
                logger.warning( f"Failed to load voice config from config_mgr: {e}" )

        # Return defaults with language_code set
        if voice_type == "female":
            return VoiceConfig(
                voice_id         = "kcQkGnn0HAT2JRDQ4Ljp",
                name             = "Maria",
                language_code    = language,
                stability        = 0.60,
                similarity_boost = 0.75,
                style            = 0.40,
            )
        else:
            return VoiceConfig(
                voice_id         = "Aa6nEBJJMKJwJkCx8VU2",
                name             = "Mr. Radio",
                language_code    = language,
                stability        = 0.55,  # Lower = more varied delivery
                similarity_boost = 0.80,
                style            = 0.50,  # Higher = more expressive
            )

    def _get_language_prefix( self, language: str ) -> str:
        """
        Get config key prefix for a language code.

        Args:
            language: ISO language code (e.g., "en", "es", "es-MX")

        Returns:
            str: Config key prefix (e.g., "spanish") or empty string for English
        """
        # Map language codes to config prefixes
        lang_map = {
            "es"    : "spanish",
            "es-ES" : "spanish",
            "es-MX" : "spanish",
            "es-AR" : "spanish",
        }

        # Get base language for codes like es-MX
        base_lang = language.split( "-" )[ 0 ]

        return lang_map.get( language, lang_map.get( base_lang, "" ) )

    async def generate_segment_audio(
        self,
        segment  : ScriptSegment,
        index    : int,
        language : str = "en"
    ) -> TTSSegmentResult:
        """
        Generate TTS audio for a single segment with retry logic.

        Connects to ElevenLabs WebSocket API, sends text, and collects
        PCM audio bytes. Retries on failure with exponential backoff.

        Requires:
            - segment has non-empty text
            - API key is available

        Ensures:
            - Returns TTSSegmentResult with success=True on success
            - Returns TTSSegmentResult with error_message on failure
            - Retries up to max_retries times

        Args:
            segment: Script segment to synthesize
            index: Segment index for tracking
            language: ISO language code for voice selection (default: "en")

        Returns:
            TTSSegmentResult: Result with PCM audio or error
        """
        if not self._api_key:
            return TTSSegmentResult(
                segment_index = index,
                speaker       = segment.speaker,
                role          = segment.role,
                success       = False,
                error_message = "ELEVENLABS_API_KEY not set",
            )

        # Get voice config for speaker and language
        voice_config = self.get_voice_config_for_speaker( segment.speaker, language )

        # Extract clean text (remove prosody annotations for TTS)
        text = self._clean_text_for_tts( segment.text )

        if not text.strip():
            return TTSSegmentResult(
                segment_index = index,
                speaker       = segment.speaker,
                role          = segment.role,
                success       = False,
                error_message = "Empty text after cleaning",
            )

        # Retry loop with exponential backoff
        last_error = None
        for attempt in range( self.max_retries ):
            try:
                pcm_audio = await self._generate_via_websocket(
                    text         = text,
                    voice_config = voice_config,
                )

                return TTSSegmentResult(
                    segment_index   = index,
                    speaker         = segment.speaker,
                    role            = segment.role,
                    pcm_audio       = pcm_audio,
                    character_count = len( text ),  # Track chars sent to ElevenLabs
                    success         = True,
                    retry_count     = attempt,
                )

            except Exception as e:
                last_error = str( e )
                # Always print failures to console — logger.warning() doesn't reach stdout
                print( f"[PodcastTTSClient] TTS attempt {attempt + 1}/{self.max_retries} failed for segment {index + 1} ({segment.speaker}): {e}" )

                # Notify user of retry (low priority)
                if self.retry_callback and attempt < self.max_retries - 1:
                    try:
                        await self.retry_callback( index, attempt + 2, self.max_retries, segment.speaker )
                    except Exception as cb_error:
                        logger.warning( f"Retry callback failed: {cb_error}" )

                if attempt < self.max_retries - 1:
                    delay = self.retry_base_delay * ( 2 ** attempt )
                    print( f"[PodcastTTSClient] Retrying segment {index + 1} in {delay:.1f}s..." )
                    await asyncio.sleep( delay )

        # Always print final failure — this is the root cause users need to see
        print( f"[PodcastTTSClient] SEGMENT {index + 1} FAILED after {self.max_retries} attempts: {last_error}" )

        return TTSSegmentResult(
            segment_index = index,
            speaker       = segment.speaker,
            role          = segment.role,
            success       = False,
            error_message = f"Failed after {self.max_retries} attempts: {last_error}",
            retry_count   = self.max_retries,
        )

    def _get_model_for_language( self, language_code: str ) -> str:
        """
        Get the appropriate ElevenLabs model for a language.

        Uses multilingual model for non-English languages.

        Args:
            language_code: ISO language code

        Returns:
            str: ElevenLabs model ID
        """
        if language_code == "en":
            return "eleven_turbo_v2_5"  # Fast English-optimized model
        else:
            return "eleven_multilingual_v2"  # Multilingual model for other languages

    async def _generate_via_websocket(
        self,
        text: str,
        voice_config: VoiceConfig,
    ) -> bytes:
        """
        Generate audio via ElevenLabs WebSocket API.

        Connects to the streaming API, sends text with voice settings,
        and collects all PCM audio chunks.

        For non-English languages, uses multilingual model and passes
        language_code in the config message.

        Args:
            text: Text to synthesize
            voice_config: Voice configuration (includes language_code)

        Returns:
            bytes: Raw PCM 24000Hz audio

        Raises:
            Exception: On WebSocket or API errors
        """
        # Select model based on language
        model_id = self._get_model_for_language( voice_config.language_code )

        # Build WebSocket URL
        ws_url = self.WS_URL_TEMPLATE.format(
            voice_id = voice_config.voice_id,
            model_id = model_id,
        )

        # Connect to ElevenLabs
        async with websockets.connect(
            ws_url,
            additional_headers = { "xi-api-key": self._api_key }
        ) as ws:

            # Build configuration message
            config_msg = {
                "text"           : " ",  # Initial space to start stream
                "voice_settings" : {
                    "stability"        : voice_config.stability,
                    "similarity_boost" : voice_config.similarity_boost,
                    "style"            : voice_config.style,
                    "use_speaker_boost": True,
                },
                "generation_config": {
                    "chunk_length_schedule": [ 120, 160, 250, 290 ],  # Low latency
                },
            }

            # Add language_code for multilingual model
            if voice_config.language_code != "en":
                config_msg[ "language_code" ] = voice_config.language_code

            await ws.send( json.dumps( config_msg ) )

            # Send text
            text_msg = {
                "text"                   : text,
                "try_trigger_generation" : True,
            }
            await ws.send( json.dumps( text_msg ) )

            # Send end-of-stream marker
            await ws.send( json.dumps( { "text": "" } ) )

            # Collect audio chunks
            audio_chunks = []
            async for message in ws:
                try:
                    data = json.loads( message )

                    if data.get( "audio" ):
                        chunk = base64.b64decode( data[ "audio" ] )
                        audio_chunks.append( chunk )

                    elif data.get( "isFinal" ):
                        break

                    elif data.get( "error" ):
                        raise Exception( f"ElevenLabs error: {data.get( 'error' )}" )

                except json.JSONDecodeError:
                    logger.warning( "Non-JSON message from ElevenLabs" )

            return b"".join( audio_chunks )

    def _clean_text_for_tts( self, text: str ) -> str:
        """
        Clean text for TTS synthesis.

        Removes ONLY the dead `*[annotation]*` vocabulary (e.g. *[excited]*,
        *[laughs]*) — those expressive audio tags are Eleven v3 only and render
        as nothing on our turbo/multilingual models. The pause-only markers the
        script LLM now emits — SSML `<break time="x.xs"/>`, ellipsis, dashes,
        CAPS — are DELIBERATELY PRESERVED so they reach synthesis. Pause-only
        prosody per Rick's 2026-08-15 ruling.

        Requires:
            - text is a string

        Ensures:
            - every `*[...]*` marker is removed
            - `<break ...>` tags, ellipsis, dashes, and CAPS survive verbatim
            - internal whitespace is collapsed to single spaces and trimmed

        Args:
            text: Raw dialogue text with markers

        Returns:
            str: Clean text ready for TTS, with pause markers intact
        """
        import re

        # Remove ONLY the dead *[...]* audio-tag vocabulary. <break>, ellipsis,
        # dashes and CAPS are intentionally left untouched.
        clean = re.sub( r'\*\[[^\]]+\]\*', '', text )

        # Clean up extra whitespace (does not affect <break time="x.xs"/> tags).
        clean = re.sub( r'\s+', ' ', clean ).strip()

        return clean

    async def generate_all_segments(
        self,
        script   : PodcastScript,
        language : str = "en"
    ) -> Tuple[ List[ TTSSegmentResult ], List[ int ] ]:
        """
        Generate TTS audio for all segments in a podcast script.

        Processes segments sequentially and reports progress via callback.

        Requires:
            - script has at least one segment

        Ensures:
            - Returns list of TTSSegmentResult for all segments
            - Returns list of indices for failed segments
            - Calls progress_callback after each segment

        Args:
            script: Podcast script with dialogue segments
            language: ISO language code for voice selection (default: "en")

        Returns:
            Tuple[List[TTSSegmentResult], List[int]]:
                - All results (including failures)
                - Indices of failed segments
        """
        results        = []
        failed_indices = []
        total          = len( script.segments )
        segment_times  = []  # Track per-segment durations for ETA

        for i, segment in enumerate( script.segments ):
            if self.debug:
                print( f"[PodcastTTSClient] Generating segment {i + 1}/{total}: {segment.speaker} ({language})" )

            segment_start = time.time()
            result = await self.generate_segment_audio( segment, i, language )
            segment_elapsed = time.time() - segment_start
            segment_times.append( segment_elapsed )

            results.append( result )

            if not result.success:
                failed_indices.append( i )
                if self.debug:
                    print( f"[PodcastTTSClient] Segment {i + 1} failed: {result.error_message}" )

            # Calculate ETA based on average segment time
            avg_time    = sum( segment_times ) / len( segment_times )
            remaining   = total - ( i + 1 )
            eta_seconds = avg_time * remaining

            # Report progress with ETA
            if self.progress_callback:
                try:
                    await self.progress_callback( i + 1, total, segment.speaker, eta_seconds )
                except Exception as e:
                    logger.warning( f"Progress callback failed: {e}" )

        # Always print completion summary — critical for diagnosing failures
        success_count = total - len( failed_indices )
        total_time    = sum( segment_times )
        print( f"[PodcastTTSClient] Complete: {success_count}/{total} segments in {total_time:.1f}s" )

        if failed_indices:
            # Print first unique error for diagnosis
            first_error = next(
                ( r.error_message for r in results if not r.success and r.error_message ),
                "Unknown error"
            )
            print( f"[PodcastTTSClient] {len( failed_indices )} segments failed. First error: {first_error}" )

        return results, failed_indices


# =============================================================================
# Smoke Test
# =============================================================================

def quick_smoke_test():
    """Quick smoke test for PodcastTTSClient."""
    import cosa.utils.util as cu

    cu.print_banner( "Podcast TTS Client Smoke Test", prepend_nl=True )

    try:
        # Test 1: TTSSegmentResult dataclass
        print( "Testing TTSSegmentResult dataclass..." )
        result = TTSSegmentResult(
            segment_index = 0,
            speaker       = "Maria",
            role          = "curious",
            pcm_audio     = b"\x00" * 48000,  # 1 second of silence at 24kHz
            success       = True,
        )
        assert result.segment_index == 0
        assert result.speaker == "Maria"
        assert result.success is True
        assert result.duration_seconds == 1.0  # 48000 bytes / 2 bytes/sample / 24000 Hz
        print( f"  Segment result: {result.speaker}, duration={result.duration_seconds:.2f}s" )

        # Test with failure
        failed_result = TTSSegmentResult(
            segment_index = 1,
            speaker       = "Mr. Radio",
            role          = "expert",
            success       = False,
            error_message = "API error",
        )
        assert failed_result.success is False
        assert failed_result.error_message == "API error"
        print( "  TTSSegmentResult dataclass works correctly" )

        # Test 2: VoiceConfig dataclass
        print( "Testing VoiceConfig dataclass..." )
        voice = VoiceConfig(
            voice_id         = "test_voice_id",
            name             = "TestVoice",
            language_code    = "es-MX",
            stability        = 0.65,
            similarity_boost = 0.75,
            style            = 0.35,
        )
        assert voice.voice_id == "test_voice_id"
        assert voice.name == "TestVoice"
        assert voice.language_code == "es-MX"
        print( f"  VoiceConfig: {voice.name} (lang={voice.language_code}, stability={voice.stability})" )

        # Test default language_code
        voice_default = VoiceConfig( voice_id="test", name="Test" )
        assert voice_default.language_code == "en"
        print( "  VoiceConfig default language_code is 'en'" )

        # Test 3: PodcastTTSClient instantiation
        print( "Testing PodcastTTSClient instantiation..." )
        client = PodcastTTSClient( debug=True )
        assert client.max_retries == 3
        assert client.retry_base_delay == 1.0
        print( "  PodcastTTSClient instantiated successfully" )

        # Test 4: Voice config lookup (without config_mgr)
        print( "Testing voice config lookup..." )
        maria_config = client.get_voice_config_for_speaker( "Maria" )
        assert maria_config.name == "Maria"
        assert maria_config.voice_id == "kcQkGnn0HAT2JRDQ4Ljp"

        mr_radio_config = client.get_voice_config_for_speaker( "Mr. Radio" )
        assert mr_radio_config.name == "Mr. Radio"
        assert mr_radio_config.voice_id == "Aa6nEBJJMKJwJkCx8VU2"

        # Test fallback for Alex (curious) and Jordan (expert)
        alex_config = client.get_voice_config_for_speaker( "Alex" )
        assert alex_config.name == "Maria"  # Fallback to female
        jordan_config = client.get_voice_config_for_speaker( "Jordan" )
        assert jordan_config.name == "Mr. Radio"  # Fallback to male
        print( "  Voice config lookup works (Maria/Mr. Radio + Alex/Jordan fallback)" )

        # Test language-aware voice lookup
        spanish_config = client.get_voice_config_for_speaker( "Maria", language="es-MX" )
        assert spanish_config.language_code == "es-MX"
        # Should use same voice ID (fallback) but with Spanish language code
        print( f"  Spanish voice lookup: {spanish_config.name} (lang={spanish_config.language_code})" )

        # Test model selection
        assert client._get_model_for_language( "en" ) == "eleven_turbo_v2_5"
        assert client._get_model_for_language( "es-MX" ) == "eleven_multilingual_v2"
        assert client._get_model_for_language( "es" ) == "eleven_multilingual_v2"
        print( "  Model selection: en→turbo, es→multilingual" )

        # Test language prefix mapping
        assert client._get_language_prefix( "en" ) == ""
        assert client._get_language_prefix( "es" ) == "spanish"
        assert client._get_language_prefix( "es-MX" ) == "spanish"
        print( "  Language prefix mapping works" )

        # Test 5: Text cleaning
        print( "Testing text cleaning..." )
        dirty_text = "So *[pause]* what you're saying *[excited]* is amazing!"
        clean_text = client._clean_text_for_tts( dirty_text )
        assert "*[" not in clean_text
        assert "pause" not in clean_text
        assert "So what you're saying is amazing!" == clean_text
        print( f"  Clean text: '{clean_text}'" )

        # Pause-only markers must SURVIVE the clean (dead *[...]* still stripped)
        pause_text = 'Wait *[excited]* for it... <break time="1.5s"/> HUGE news!'
        pause_clean = client._clean_text_for_tts( pause_text )
        assert '<break time="1.5s"/>' in pause_clean  # SSML break preserved
        assert "..." in pause_clean                    # ellipsis preserved
        assert "HUGE" in pause_clean                   # caps preserved
        assert "*[" not in pause_clean                 # dead marker still gone
        print( f"  Pause markers preserved: '{pause_clean}'" )

        # Test 6: API key check
        print( "Testing API key detection..." )
        has_key = client._api_key is not None
        print( f"  ELEVENLABS_API_KEY: {'present' if has_key else 'not set'}" )
        # Not an error if key is missing - just informational

        print( "\n  Podcast TTS Client smoke test completed successfully" )

    except Exception as e:
        print( f"\n  Smoke test failed: {e}" )
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    quick_smoke_test()
