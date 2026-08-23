"""
E2E UI tests for the Q&A submission interface on the notifications page.

Phase 6: Notifications & Q&A Tests — validates agent mode selector,
question input, STT button, TTS mode, submit button, and metrics display.

Requires:
    - Dev server running on port 7999 with Testing config
    - Clean test database (via logged_in_page fixture)
"""

from cosa.rest.v2.registry import AUTO_ROUTE_VALUE
from .agent_select_contract import expected_option_values, option_value_drift
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

    def test_mode_selector_renders_exactly_the_expected_option_values( self, logged_in_page ):
        """
        The agent mode dropdown renders exactly the option values it is supposed to.

        Was `assert options.count() >= 2` — a count, which the retirement plan's §6
        disqualifies, and which survives a PARTIAL render (Auto-Route plus one agent
        satisfies `>= 2` while 15 agents are missing). Now a set-equality against the
        registry, via the shared `option_value_drift` predicate whose must-fail
        control is test_agent_select_contract_control.py.

        The oracle MOVED here on 2026-08-22 and was not moved by hand: phase 3 emptied
        the hardcoded options out of notifications.html, so `checked_in_option_values()`
        returned an empty set, and the predicate's ORACLE EMPTY arm refused to compare
        rather than passing an empty-vs-empty equality. The guard stayed red until the
        oracle was repointed at the registry. That was the design.

        Requires:
            - Authenticated session

        Ensures:
            - the rendered option values equal the expected set, with no missing,
              phantom, or blank values, and an empty select is a FAILURE not a pass
        """
        logged_in_page.goto( f"{BASE_URL}/app/notifications?classic=1" )
        logged_in_page.wait_for_load_state( "networkidle" )

        mode_select = logged_in_page.get_by_test_id( "notifications-qa-mode-select" )

        # The options arrive from GET /api/v2/agents AFTER auth, so `networkidle` can
        # land before the render — a DOM read taken there sees an empty select and this
        # guard would red on a working page. Wait for the render, then measure.
        logged_in_page.locator(
            "#agent-mode option[value='agent router go to math']"
        ).wait_for( state="attached", timeout=10_000 )

        options     = mode_select.locator( "option" )
        rendered    = [ options.nth( i ).get_attribute( "value" ) for i in range( options.count() ) ]

        problems = option_value_drift( rendered, expected=expected_option_values() )
        assert problems == [], "#agent-mode option drift:\n  " + "\n  ".join( problems )

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
            - the select renders EXACTLY the user-initiable set plus the sentinel
            - the default is the Auto-Route sentinel, so a plain question auto-routes
            - selecting a real agent changes the value

        MERGE NOTE (2026-08-22): Sam and I rewrote this test independently, having both
        found the same vacuity. Both halves are kept because each catches what the
        other misses. His async wait is load-bearing — phase 3 fetches the options
        after auth, so `networkidle` can land BEFORE the render and a DOM read taken
        there sees an empty select. My set-equality is load-bearing too — waiting on
        one option proves only that ONE option arrived, so a partial render carrying
        Auto-Route plus `math` would satisfy it while 15 agents were missing.
        """
        logged_in_page.goto( f"{BASE_URL}/app/notifications?classic=1" )
        logged_in_page.wait_for_load_state( "networkidle" )

        mode_select = logged_in_page.get_by_test_id( "notifications-qa-mode-select" )

        # Sam's wait: the options arrive from GET /api/v2/agents after auth, so read
        # the DOM only once at least one of them is attached.
        logged_in_page.locator(
            "#agent-mode option[value='agent router go to math']"
        ).wait_for( state="attached", timeout=10_000 )

        assert mode_select.is_visible(), "#agent-mode is not visible — cannot be skipped past"
        assert mode_select.input_value() == AUTO_ROUTE_VALUE, (
            "the card did not come up auto-routing — a question would submit as a job"
        )

        # ...and then the WHOLE set, not just the one option we waited on.
        options  = mode_select.locator( "option" )
        rendered = [ options.nth( i ).get_attribute( "value" ) for i in range( options.count() ) ]
        problems = option_value_drift( rendered, expected=expected_option_values() )
        assert problems == [], "#agent-mode option drift:\n  " + "\n  ".join( problems )

        mode_select.select_option( "agent router go to math" )
        assert mode_select.input_value() == "agent router go to math"
