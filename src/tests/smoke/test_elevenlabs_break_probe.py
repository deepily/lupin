#!/usr/bin/env python3
"""
:8000-ONLY empirical probe — does <break time="x.xs"/> actually render a SILENT
gap on our ElevenLabs stream-input endpoint?

Row 03d41dd8 (ElevenLabs pause-only prosody). Rick ruled 2026-08-15: pause-only.
The unit suite proves the strip PRESERVES <break>; it cannot prove the marker
RENDERS. This probe is the can-fail comparison that measures rendered audio.

SPENDS REAL ElevenLabs credit → route to :8000 (test_types="pytest_direct").
Never collected by the :7999 unit run (lives under smoke/, key-gated skip).

Three arms, SAME sentence, so a difference can only come from the marker:
  ARM 1  plain          no marker,       ssml flag ON   → baseline
  ARM 2  break-honored  <break 1.5s>,    ssml flag ON   → expect a ~1.5s SILENCE
  ARM 3  break-spoken   <break 1.5s>,    ssml flag OFF  → tag ignored/spoken, NO gap

Discriminator is NOT total duration alone — a model that READS the tag aloud
("break time one point five s") also lengthens the clip. The honest signal is
the LONGEST CONTINUOUS NEAR-SILENT RUN in the PCM: only an honored break inserts
a real ~1.5s silence. ARM 3 is the control that separates "silent gap" from
"spoken tag".

PREDICTION (stated before the run, per Cheech 2026-08-15):
  - ARM 2 longest silent run >= 1.2s (target ~1.5s)
  - ARM 2 silent run >= ARM 1 silent run + 1.0s
  - ARM 2 silent run >= ARM 3 silent run + 1.0s   (proves the FLAG, not the text)
A smaller ARM-2 gap = flag not honored = FAIL.
"""

import asyncio

import numpy as np
import pytest

import cosa.agents.podcast_generator.tts_client as tc
from cosa.agents.podcast_generator.tts_client import PodcastTTSClient, VoiceConfig

# PCM 24000Hz, 16-bit mono
_SAMPLE_RATE      = 24000
_SILENCE_ABS      = 300     # int16 magnitude below this counts as "silent"
_PLAIN_TEXT       = "Wait for it. Huge news everyone."
_BREAK_TEXT       = 'Wait for it. <break time="1.5s"/> Huge news everyone.'
_URL_NO_SSML      = (  # the pre-fix template — ssml parsing OFF (ARM 3 control)
    "wss://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream-input"
    "?model_id={model_id}&output_format=pcm_24000"
)


def _have_key() -> bool:
    """True iff an ElevenLabs key resolves (env or local key file)."""
    c = PodcastTTSClient()
    return bool( c._api_key )


def _pcm_duration_s( pcm: bytes ) -> float:
    """Total audio duration in seconds from PCM byte length."""
    return ( len( pcm ) // 2 ) / float( _SAMPLE_RATE )


def _longest_silent_run_s( pcm: bytes ) -> float:
    """
    Longest continuous run of near-silent samples, in seconds.

    Requires:
        - pcm is 16-bit mono little-endian bytes
    Ensures:
        - returns 0.0 for empty/all-loud audio
        - returns the max consecutive silent-sample run / sample_rate
    """
    if not pcm:
        return 0.0
    samples   = np.frombuffer( pcm, dtype=np.int16 )
    is_silent = np.abs( samples.astype( np.int32 ) ) < _SILENCE_ABS
    # Longest run of True in a boolean array.
    best = cur = 0
    for s in is_silent:
        cur  = cur + 1 if s else 0
        best = cur if cur > best else best
    return best / float( _SAMPLE_RATE )


def _synthesize( text: str, url_template: str ) -> bytes:
    """Run one real synthesis through _generate_via_websocket with a given URL template."""
    client = PodcastTTSClient()
    # English → eleven_turbo_v2_5 (our production model for EN podcasts)
    vc     = VoiceConfig( voice_id="Aa6nEBJJMKJwJkCx8VU2", name="Mr. Radio", language_code="en" )
    original = PodcastTTSClient.WS_URL_TEMPLATE
    PodcastTTSClient.WS_URL_TEMPLATE = url_template
    try:
        return asyncio.run( client._generate_via_websocket( text, vc ) )
    finally:
        PodcastTTSClient.WS_URL_TEMPLATE = original


@pytest.mark.skipif( not _have_key(), reason="ElevenLabs key not available — probe spends real credit" )
def test_break_tag_renders_a_silent_gap():
    """3-arm comparison: an honored <break> inserts a measured ~1.5s silence."""
    honored_url = PodcastTTSClient.WS_URL_TEMPLATE  # has enable_ssml_parsing=true (the fix)
    assert "enable_ssml_parsing=true" in honored_url, "fix missing — URL lacks ssml flag"
    assert "enable_ssml_parsing" not in _URL_NO_SSML, "control URL must NOT enable ssml"

    arm1 = _synthesize( _PLAIN_TEXT, honored_url )   # plain,          flag ON
    arm2 = _synthesize( _BREAK_TEXT, honored_url )   # <break>,        flag ON
    arm3 = _synthesize( _BREAK_TEXT, _URL_NO_SSML )  # <break>,        flag OFF

    dur1, sil1 = _pcm_duration_s( arm1 ), _longest_silent_run_s( arm1 )
    dur2, sil2 = _pcm_duration_s( arm2 ), _longest_silent_run_s( arm2 )
    dur3, sil3 = _pcm_duration_s( arm3 ), _longest_silent_run_s( arm3 )

    print( "\n=== ElevenLabs <break> probe (row 03d41dd8) ===" )
    print( f"{'ARM':<26} {'total_s':>9} {'max_silence_s':>14}" )
    print( f"{'1 plain (flag ON)':<26} {dur1:>9.3f} {sil1:>14.3f}" )
    print( f"{'2 <break> (flag ON)':<26} {dur2:>9.3f} {sil2:>14.3f}" )
    print( f"{'3 <break> (flag OFF)':<26} {dur3:>9.3f} {sil3:>14.3f}" )
    print( f"PREDICTION: arm2 silence >=1.2s, >= arm1+1.0s, >= arm3+1.0s" )

    # An honored 1.5s break must show a real silent gap...
    assert sil2 >= 1.2, f"arm2 silence {sil2:.3f}s < 1.2s — break not honored"
    # ...that the plain baseline does not have...
    assert sil2 >= sil1 + 1.0, f"arm2 silence {sil2:.3f}s not >= arm1 {sil1:.3f}s + 1.0s"
    # ...and that a flag-OFF run does not have (proves the FLAG, not the tag text).
    assert sil2 >= sil3 + 1.0, f"arm2 silence {sil2:.3f}s not >= arm3 {sil3:.3f}s + 1.0s"
    # Total duration also grows by roughly the break length.
    assert dur2 >= dur1 + 1.0, f"arm2 total {dur2:.3f}s not >= arm1 {dur1:.3f}s + 1.0s"


if __name__ == "__main__":
    if not _have_key():
        print( "SKIP: no ElevenLabs key" )
    else:
        test_break_tag_renders_a_silent_gap()
        print( "PROBE PASSED" )
