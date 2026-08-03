"""
E2E — the podcast overlay actually PLAYS under a REAL user gesture (durable gate).

THE GAP THIS CLOSES (Clayton + Mr Radio, 2026-08-03). Three gates guard the audio
player P0 (row 4cfabc0f); the other two each leave half the claim unproven:
  - Rachel's `test_podcast_overlay_playhere.py` does a REAL Play Here click but
    asserts only that the <audio> element is ATTACHED inside the frame — not that
    it plays.
  - The header smoke test asserts /app/audio serves X-Frame-Options: SAMEORIGIN —
    the frame is ALLOWED, but says nothing about sound.
  - Clayton's first probe asserted playback but launched Chromium with
    --autoplay-policy=no-user-gesture-required — a SYNTHETIC gesture. That proves
    "auto-starts WHEN PERMITTED", not that the real click's user activation
    PROPAGATES through allow="autoplay" into the same-origin iframe.

This test proves the whole path in one shot, with NO autoplay-policy override:
  real Playwright click (genuine user activation)
    → Rio's interception opens the overlay, iframe src carries &autoplay=1
    → the frame's <audio> auto-starts and its currentTime ADVANCES.
If user activation did NOT reach the frame, the page's autoplay play() is blocked,
the element stays paused, and this test fails — which is exactly the six-week
silent-player regression it guards against.

WHY --mute-audio (set in conftest launch args, NOT here). Headless Chromium has no
audio sink, so an UNMUTED playing element's media clock can freeze at ~0. The
browser-level --mute-audio flag lets the clock advance under headless WITHOUT
touching the autoplay-gesture policy — so the gesture requirement this test exists
to exercise stays fully real. (Verified: with --mute-audio the clock advanced
0.043→0.628; without it, frozen.) It mutes the speaker, never pauses the element.

Venue: :8000 e2e_ui (scheduled) — registers a user, real browser, real server.
"""

import time

from src.tests.e2e_ui.test_podcast_overlay_playhere import (
    _render_abstract,
    _click_play_here,
    OVERLAY,
    FRAME,
)


class TestPodcastOverlayPlays:
    """The overlay auto-starts and plays sound when Play Here is genuinely clicked."""

    def test_real_click_gesture_propagates_and_audio_plays( self, notifications_page ):
        page = notifications_page

        # Render the completion abstract + click the REAL Play Here anchor. This is a
        # genuine Playwright user gesture — NOT an autoplay-policy override.
        _render_abstract( page )
        _click_play_here( page )
        page.locator( OVERLAY ).wait_for( state="visible", timeout=5000 )

        frame = page.frame_locator( FRAME )
        # RENDER: audio element reachable inside the frame (not the XFO DENY doc).
        frame.locator( "audio" ).wait_for( state="attached", timeout=8000 )
        audio = frame.locator( "audio" )

        # AUTH-IN-FRAME: wait for Rio's blob-fetch to buffer + wire a blob: src.
        blob_src = ""
        for _ in range( 60 ):
            blob_src = audio.get_attribute( "src" ) or ""
            if blob_src.startswith( "blob:" ):
                break
            time.sleep( 0.25 )
        assert blob_src.startswith( "blob:" ), (
            f"blob-fetch did not authenticate inside the frame — src={blob_src!r} "
            f"(a 401 leaves the player in an error state with no blob: src)"
        )

        handle = audio.element_handle()
        # currentTime advances only because conftest launches with --mute-audio (see
        # module docstring); the gesture + auto-start already happened, unmuted.
        time.sleep( 0.5 )
        ct0 = page.evaluate( "( el ) => el.currentTime", handle )
        time.sleep( 2.0 )
        paused = page.evaluate( "( el ) => el.paused", handle )
        ct1    = page.evaluate( "( el ) => el.currentTime", handle )

        # AUTO-START under a REAL gesture: playing (not paused) AND the clock advanced.
        assert paused is False, (
            "audio is PAUSED after a real Play Here click — the click's user "
            "activation did not propagate into the overlay iframe (allow=autoplay), "
            "so the page's auto-start play() was blocked"
        )
        assert ct1 > ct0, (
            f"currentTime did not advance ({ct0} → {ct1}) — the <audio> is attached "
            f"and unpaused but not actually decoding/playing"
        )
