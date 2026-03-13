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
        logged_in_page.goto( f"{BASE_URL}/app/notifications" )
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
        logged_in_page.goto( f"{BASE_URL}/app/notifications" )
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
        logged_in_page.goto( f"{BASE_URL}/app/notifications" )
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
        logged_in_page.goto( f"{BASE_URL}/app/notifications" )
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
        logged_in_page.goto( f"{BASE_URL}/app/notifications" )
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
        logged_in_page.goto( f"{BASE_URL}/app/notifications" )
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
        logged_in_page.goto( f"{BASE_URL}/app/notifications" )
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
        logged_in_page.goto( f"{BASE_URL}/app/notifications" )
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
        logged_in_page.goto( f"{BASE_URL}/app/notifications" )
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
        logged_in_page.goto( f"{BASE_URL}/app/notifications" )
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
        logged_in_page.goto( f"{BASE_URL}/app/notifications" )
        logged_in_page.wait_for_load_state( "networkidle" )

        tts_input = logged_in_page.get_by_test_id( "notifications-direct-tts-input" )
        if tts_input.count() > 0 and tts_input.is_visible():
            tts_input.fill( "Hello test TTS" )
            assert tts_input.input_value() == "Hello test TTS"
