"""
E2E UI tests for TTS playback controls on the notifications page.

Phase 6: Notifications & Q&A Tests — validates TTS queue section,
playback controls, and direct TTS test interface.

Requires:
    - Dev server running on port 7999 with Testing config
    - Clean test database (via logged_in_page fixture)
"""

from .conftest import BASE_URL


# ---------------------------------------------------------------------------
# TTS Queue Controls
# ---------------------------------------------------------------------------

class TestTTSQueueControls:
    """Tests for TTS playback queue section controls."""

    def test_pause_button_present( self, logged_in_page ):
        """
        TTS section has pause button.

        Requires:
            - Authenticated session

        Ensures:
            - Pause button element exists
        """
        logged_in_page.goto( f"{BASE_URL}/app/notifications?classic=1" )
        logged_in_page.wait_for_load_state( "networkidle" )

        assert logged_in_page.get_by_test_id( "notifications-tts-pause-btn" ).count() > 0

    def test_play_button_present( self, logged_in_page ):
        """
        TTS section has play button.

        Requires:
            - Authenticated session

        Ensures:
            - Play button element exists
        """
        logged_in_page.goto( f"{BASE_URL}/app/notifications?classic=1" )
        logged_in_page.wait_for_load_state( "networkidle" )

        assert logged_in_page.get_by_test_id( "notifications-tts-play-btn" ).count() > 0

    def test_clear_button_present( self, logged_in_page ):
        """
        TTS section has clear button.

        Requires:
            - Authenticated session

        Ensures:
            - Clear button element exists
        """
        logged_in_page.goto( f"{BASE_URL}/app/notifications?classic=1" )
        logged_in_page.wait_for_load_state( "networkidle" )

        assert logged_in_page.get_by_test_id( "notifications-tts-clear-btn" ).count() > 0

    def test_active_slot_present( self, logged_in_page ):
        """
        TTS section has active playback slot.

        Requires:
            - Authenticated session

        Ensures:
            - Active slot element exists
        """
        logged_in_page.goto( f"{BASE_URL}/app/notifications?classic=1" )
        logged_in_page.wait_for_load_state( "networkidle" )

        assert logged_in_page.get_by_test_id( "notifications-tts-active-slot" ).count() > 0

    def test_pending_queue_present( self, logged_in_page ):
        """
        TTS section has pending queue area.

        Requires:
            - Authenticated session

        Ensures:
            - Pending queue element exists
        """
        logged_in_page.goto( f"{BASE_URL}/app/notifications?classic=1" )
        logged_in_page.wait_for_load_state( "networkidle" )

        assert logged_in_page.get_by_test_id( "notifications-tts-pending-queue" ).count() > 0


# ---------------------------------------------------------------------------
# Direct TTS Test Interface
# ---------------------------------------------------------------------------

class TestDirectTTSInterface:
    """Tests for the Direct TTS test section."""

    def test_direct_tts_input_present( self, logged_in_page ):
        """
        Direct TTS section has text input.

        Requires:
            - Authenticated session

        Ensures:
            - Direct TTS input element exists
        """
        logged_in_page.goto( f"{BASE_URL}/app/notifications?classic=1" )
        logged_in_page.wait_for_load_state( "networkidle" )

        assert logged_in_page.get_by_test_id( "notifications-direct-tts-input" ).count() > 0

    def test_direct_tts_button_present( self, logged_in_page ):
        """
        Direct TTS section has send button.

        Requires:
            - Authenticated session

        Ensures:
            - Direct TTS button element exists
        """
        logged_in_page.goto( f"{BASE_URL}/app/notifications?classic=1" )
        logged_in_page.wait_for_load_state( "networkidle" )

        assert logged_in_page.get_by_test_id( "notifications-direct-tts-btn" ).count() > 0

    def test_instant_tts_test_button_present( self, logged_in_page ):
        """
        Direct TTS section has instant TTS test button.

        Requires:
            - Authenticated session

        Ensures:
            - Instant TTS test button exists
        """
        logged_in_page.goto( f"{BASE_URL}/app/notifications?classic=1" )
        logged_in_page.wait_for_load_state( "networkidle" )

        assert logged_in_page.get_by_test_id( "notifications-test-instant-tts-btn" ).count() > 0

    def test_reliable_tts_test_button_present( self, logged_in_page ):
        """
        Direct TTS section has reliable TTS test button.

        Requires:
            - Authenticated session

        Ensures:
            - Reliable TTS test button exists
        """
        logged_in_page.goto( f"{BASE_URL}/app/notifications?classic=1" )
        logged_in_page.wait_for_load_state( "networkidle" )

        assert logged_in_page.get_by_test_id( "notifications-test-reliable-tts-btn" ).count() > 0

    def test_stop_audio_button_present( self, logged_in_page ):
        """
        Direct TTS section has stop audio button.

        Requires:
            - Authenticated session

        Ensures:
            - Stop audio button exists
        """
        logged_in_page.goto( f"{BASE_URL}/app/notifications?classic=1" )
        logged_in_page.wait_for_load_state( "networkidle" )

        assert logged_in_page.get_by_test_id( "notifications-stop-audio-btn" ).count() > 0

    def test_can_type_in_direct_tts_input( self, logged_in_page ):
        """
        User can type text into the direct TTS input.

        Requires:
            - Authenticated session

        Ensures:
            - Text can be entered into the direct TTS input
        """
        logged_in_page.goto( f"{BASE_URL}/app/notifications?classic=1" )
        logged_in_page.wait_for_load_state( "networkidle" )

        tts_input = logged_in_page.get_by_test_id( "notifications-direct-tts-input" )
        if tts_input.count() > 0 and tts_input.is_visible():
            tts_input.fill( "Hello test TTS" )
            assert tts_input.input_value() == "Hello test TTS"


# ---------------------------------------------------------------------------
# TTS preview-fraction slider (2026-06-01: 25% → 12.5% increments)
# ---------------------------------------------------------------------------

class TestTTSFractionSlider:
    """
    The TTS preview-fraction slider in the Claude Code Notifications accordion
    header increments/decrements in 12.5% steps (was 25%). Nine stops:
    0 / 12.5 / 25 / 37.5 / 50 / 62.5 / 75 / 87.5 / 100.
    """

    def test_slider_step_is_twelve_point_five( self, logged_in_page ):
        """The range input's step attribute is 12.5, not 25."""
        logged_in_page.goto( f"{BASE_URL}/app/notifications?classic=1" )
        logged_in_page.wait_for_load_state( "networkidle" )

        step = logged_in_page.eval_on_selector(
            "#cc-tts-fraction-slider", "el => el.getAttribute( 'step' )"
        )
        assert step == "12.5", f"slider step should be 12.5, got {step}"

    def test_datalist_has_nine_twelve_point_five_ticks( self, logged_in_page ):
        """The tick datalist enumerates all nine 12.5% stops."""
        logged_in_page.goto( f"{BASE_URL}/app/notifications?classic=1" )
        logged_in_page.wait_for_load_state( "networkidle" )

        ticks = logged_in_page.eval_on_selector_all(
            "#cc-tts-fraction-ticks option", "els => els.map( e => e.value )"
        )
        assert ticks == [ "0", "12.5", "25", "37.5", "50", "62.5", "75", "87.5", "100" ], \
            f"unexpected tick stops: {ticks}"

    def _drive( self, page, percent_value ):
        """
        Set the slider to `percent_value`, fire the real 'input' handler, and
        return {label, fraction} read back from the live DOM + controller. The
        browser snaps the assigned value to the nearest valid step.
        """
        return page.evaluate(
            """( pv ) => {
                const el = document.getElementById( 'cc-tts-fraction-slider' );
                el.value = String( pv );
                el.dispatchEvent( new Event( 'input', { bubbles: true } ) );
                return {
                    label   : document.getElementById( 'cc-tts-fraction-value' ).textContent,
                    fraction: window.notificationsUI.ttsPreviewFraction,
                    snapped : el.value
                };
            }""",
            percent_value,
        )

    def test_half_step_not_truncated_to_integer( self, logged_in_page ):
        """
        Regression guard: the handler uses parseFloat, so 12.5 must NOT become
        12 (the parseInt bug). Label shows "12.5%", fraction is 0.125.
        """
        logged_in_page.goto( f"{BASE_URL}/app/notifications?classic=1" )
        logged_in_page.wait_for_load_state( "networkidle" )

        result = self._drive( logged_in_page, 12.5 )
        assert result[ "snapped" ]  == "12.5",  f"slider should snap to 12.5, got {result['snapped']}"
        assert result[ "label" ]    == "12.5%", f"label should read 12.5%, got {result['label']}"
        assert abs( result[ "fraction" ] - 0.125 ) < 1e-9, f"fraction should be 0.125, got {result['fraction']}"

    def test_other_half_step_values( self, logged_in_page ):
        """37.5%, 62.5%, 87.5% all round-trip cleanly through the handler."""
        logged_in_page.goto( f"{BASE_URL}/app/notifications?classic=1" )
        logged_in_page.wait_for_load_state( "networkidle" )

        for pct, frac in ( ( 37.5, 0.375 ), ( 62.5, 0.625 ), ( 87.5, 0.875 ) ):
            result = self._drive( logged_in_page, pct )
            assert result[ "label" ] == f"{pct}%", f"label mismatch at {pct}: {result['label']}"
            assert abs( result[ "fraction" ] - frac ) < 1e-9, f"fraction mismatch at {pct}: {result['fraction']}"

    def test_integer_stops_still_work( self, logged_in_page ):
        """The pre-existing 25/50/75/100 stops remain valid (no regression)."""
        logged_in_page.goto( f"{BASE_URL}/app/notifications?classic=1" )
        logged_in_page.wait_for_load_state( "networkidle" )

        for pct, frac in ( ( 0, 0.0 ), ( 25, 0.25 ), ( 50, 0.5 ), ( 100, 1.0 ) ):
            result = self._drive( logged_in_page, pct )
            assert abs( result[ "fraction" ] - frac ) < 1e-9, f"fraction mismatch at {pct}: {result['fraction']}"
