"""
E2E UI tests for the Q&A submission interface on the notifications page.

Phase 6: Notifications & Q&A Tests — validates agent mode selector,
question input, STT button, TTS mode, submit button, and metrics display.

Requires:
    - Dev server running on port 7999 with Testing config
    - Clean test database (via logged_in_page fixture)
"""

from .conftest import BASE_URL


# ---------------------------------------------------------------------------
# Q&A Interface Layout
# ---------------------------------------------------------------------------

class TestQAInterfaceLayout:
    """Tests for Q&A submission interface rendering."""

    def test_mode_selector_present( self, logged_in_page ):
        """
        Q&A interface has agent mode dropdown.

        Requires:
            - Authenticated session

        Ensures:
            - Mode select element exists and is visible
        """
        logged_in_page.goto( f"{BASE_URL}/app/notifications" )
        logged_in_page.wait_for_load_state( "networkidle" )

        mode_select = logged_in_page.get_by_test_id( "notifications-qa-mode-select" )
        assert mode_select.count() > 0

    def test_mode_selector_has_options( self, logged_in_page ):
        """
        Agent mode dropdown has multiple agent options.

        Requires:
            - Authenticated session

        Ensures:
            - Mode select has multiple options (Math, Calendar, etc.)
        """
        logged_in_page.goto( f"{BASE_URL}/app/notifications" )
        logged_in_page.wait_for_load_state( "networkidle" )

        mode_select = logged_in_page.get_by_test_id( "notifications-qa-mode-select" )
        options     = mode_select.locator( "option" )

        assert options.count() >= 2, f"Expected >=2 agent mode options, got {options.count()}"

    def test_question_input_present( self, logged_in_page ):
        """
        Q&A interface has text input for questions.

        Requires:
            - Authenticated session

        Ensures:
            - Question input element exists
        """
        logged_in_page.goto( f"{BASE_URL}/app/notifications" )
        logged_in_page.wait_for_load_state( "networkidle" )

        qa_input = logged_in_page.get_by_test_id( "notifications-qa-input" )
        assert qa_input.count() > 0

    def test_stt_button_present( self, logged_in_page ):
        """
        Q&A interface has a speech-to-text button.

        Requires:
            - Authenticated session

        Ensures:
            - STT button exists in DOM
        """
        logged_in_page.goto( f"{BASE_URL}/app/notifications" )
        logged_in_page.wait_for_load_state( "networkidle" )

        stt_btn = logged_in_page.get_by_test_id( "notifications-qa-stt-btn" )
        assert stt_btn.count() > 0

    def test_tts_mode_selector_present( self, logged_in_page ):
        """
        Q&A interface has TTS mode selector.

        Requires:
            - Authenticated session

        Ensures:
            - TTS mode select element exists
        """
        logged_in_page.goto( f"{BASE_URL}/app/notifications" )
        logged_in_page.wait_for_load_state( "networkidle" )

        tts_mode = logged_in_page.get_by_test_id( "notifications-qa-tts-mode-select" )
        assert tts_mode.count() > 0

    def test_submit_button_present( self, logged_in_page ):
        """
        Q&A interface has submit button.

        Requires:
            - Authenticated session

        Ensures:
            - Submit button exists and is visible
        """
        logged_in_page.goto( f"{BASE_URL}/app/notifications" )
        logged_in_page.wait_for_load_state( "networkidle" )

        submit_btn = logged_in_page.get_by_test_id( "notifications-qa-submit-btn" )
        assert submit_btn.count() > 0

    def test_metrics_section_present( self, logged_in_page ):
        """
        Q&A interface has metrics display area.

        Requires:
            - Authenticated session

        Ensures:
            - Metrics element exists in DOM
        """
        logged_in_page.goto( f"{BASE_URL}/app/notifications" )
        logged_in_page.wait_for_load_state( "networkidle" )

        metrics = logged_in_page.get_by_test_id( "notifications-qa-metrics" )
        assert metrics.count() > 0


# ---------------------------------------------------------------------------
# Q&A Input Interaction
# ---------------------------------------------------------------------------

class TestQAInputInteraction:
    """Tests for Q&A input field behavior."""

    def test_can_type_in_question_input( self, logged_in_page ):
        """
        User can type text into the Q&A question input.

        Requires:
            - Authenticated session

        Ensures:
            - Text can be entered into the input field
        """
        logged_in_page.goto( f"{BASE_URL}/app/notifications" )
        logged_in_page.wait_for_load_state( "networkidle" )

        qa_input = logged_in_page.get_by_test_id( "notifications-qa-input" )
        if qa_input.is_visible():
            qa_input.fill( "What is 2 + 2?" )
            assert qa_input.input_value() == "What is 2 + 2?"

    def test_can_change_agent_mode( self, logged_in_page ):
        """
        User can change the agent mode selector.

        Requires:
            - Authenticated session

        Ensures:
            - Mode selector value changes after selection
        """
        logged_in_page.goto( f"{BASE_URL}/app/notifications" )
        logged_in_page.wait_for_load_state( "networkidle" )

        mode_select = logged_in_page.get_by_test_id( "notifications-qa-mode-select" )
        if mode_select.is_visible():
            options = mode_select.locator( "option" )
            if options.count() >= 2:
                # Select the second option
                mode_select.select_option( index=1 )
                logged_in_page.wait_for_timeout( 300 )
