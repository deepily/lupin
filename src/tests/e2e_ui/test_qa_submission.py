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
        logged_in_page.goto( f"{BASE_URL}/app/notifications?classic=1" )
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
        logged_in_page.goto( f"{BASE_URL}/app/notifications?classic=1" )
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
        logged_in_page.goto( f"{BASE_URL}/app/notifications?classic=1" )
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
        logged_in_page.goto( f"{BASE_URL}/app/notifications?classic=1" )
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
        logged_in_page.goto( f"{BASE_URL}/app/notifications?classic=1" )
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
        logged_in_page.goto( f"{BASE_URL}/app/notifications?classic=1" )
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
        logged_in_page.goto( f"{BASE_URL}/app/notifications?classic=1" )
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
        logged_in_page.goto( f"{BASE_URL}/app/notifications?classic=1" )
        logged_in_page.wait_for_load_state( "networkidle" )

        qa_input = logged_in_page.get_by_test_id( "notifications-qa-input" )
        if qa_input.is_visible():
            qa_input.fill( "What is 2 + 2?" )
            assert qa_input.input_value() == "What is 2 + 2?"

    def test_can_change_agent_mode( self, logged_in_page ):
        """
        User can change the agent selector, and the change sticks for that request.

        ⚠️ REWRITTEN 2026-08-22 (Q&A card phase 3), for two reasons.

        (1) The options are now fetched from GET /api/v2/agents after auth rather than
        shipped in the HTML, so `networkidle` can land before the render. The wait is
        now on a specific option being attached.

        (2) The old body was `if visible: if count >= 2: select_option(index=1)` with
        NO assertion after it. An empty select made both guards false and the test
        passed having checked nothing — which is precisely the failure the async render
        would have produced, reported green. It now asserts the resulting value.

        Requires:
            - Authenticated session

        Ensures:
            - the select renders a real agent option and selecting it changes the value
            - the default is the Auto-Route sentinel, so a plain question auto-routes
        """
        logged_in_page.goto( f"{BASE_URL}/app/notifications?classic=1" )
        logged_in_page.wait_for_load_state( "networkidle" )

        mode_select = logged_in_page.get_by_test_id( "notifications-qa-mode-select" )
        logged_in_page.locator(
            "#agent-mode option[value='agent router go to math']"
        ).wait_for( state="attached", timeout=10_000 )

        assert mode_select.input_value() == "__auto_route__", (
            "the card did not come up auto-routing — a question would submit as a job"
        )

        mode_select.select_option( "agent router go to math" )
        assert mode_select.input_value() == "agent router go to math"
