"""
E2E UI tests for agentic job dispatch cards on the notifications page.

Phase 6: Notifications & Q&A Tests — validates Claude Code, Research and
Test Suite submission card elements and interactions.

The Podcast and SWE Team card classes were DELETED, not disabled, when their doors
retired: Rick ruled 2026-08-21 that the Submit Agentic Jobs accordion is going away and
Q&A is the entrance, so each door commit deletes its own card, and a UI test for a card
that no longer exists is not a gap in coverage — it is coverage of nothing.

Requires:
    - Dev server running on port 7999 with Testing config
    - Clean test database (via logged_in_page fixture)
"""

from .conftest import BASE_URL


# ---------------------------------------------------------------------------
# Claude Code Card
# ---------------------------------------------------------------------------

class TestClaudeCodeCard:
    """Tests for Claude Code job dispatch card."""

    def test_cc_card_present( self, logged_in_page ):
        """
        Claude Code dispatcher card exists in DOM.

        Requires:
            - Authenticated session

        Ensures:
            - CC card element present
        """
        logged_in_page.goto( f"{BASE_URL}/app/notifications?classic=1" )
        logged_in_page.wait_for_load_state( "networkidle" )

        assert logged_in_page.get_by_test_id( "notifications-cc-card" ).count() > 0

    def test_cc_card_has_project_select( self, logged_in_page ):
        """
        CC card has project selector dropdown.

        Requires:
            - Authenticated session

        Ensures:
            - Project select element exists
        """
        logged_in_page.goto( f"{BASE_URL}/app/notifications?classic=1" )
        logged_in_page.wait_for_load_state( "networkidle" )

        assert logged_in_page.get_by_test_id( "notifications-cc-project-select" ).count() > 0

    def test_cc_card_has_prompt_textarea( self, logged_in_page ):
        """
        CC card has prompt textarea.

        Requires:
            - Authenticated session

        Ensures:
            - Prompt textarea exists
        """
        logged_in_page.goto( f"{BASE_URL}/app/notifications?classic=1" )
        logged_in_page.wait_for_load_state( "networkidle" )

        assert logged_in_page.get_by_test_id( "notifications-cc-prompt-textarea" ).count() > 0

    def test_cc_card_has_task_type_select( self, logged_in_page ):
        """
        CC card has task type selector.

        Requires:
            - Authenticated session

        Ensures:
            - Task type select element exists
        """
        logged_in_page.goto( f"{BASE_URL}/app/notifications?classic=1" )
        logged_in_page.wait_for_load_state( "networkidle" )

        assert logged_in_page.get_by_test_id( "notifications-cc-task-type-select" ).count() > 0

    def test_cc_card_has_dry_run_checkbox( self, logged_in_page ):
        """
        CC card has dry-run checkbox.

        Requires:
            - Authenticated session

        Ensures:
            - Dry-run checkbox element exists
        """
        logged_in_page.goto( f"{BASE_URL}/app/notifications?classic=1" )
        logged_in_page.wait_for_load_state( "networkidle" )

        assert logged_in_page.get_by_test_id( "notifications-cc-dry-run-checkbox" ).count() > 0

    def test_cc_card_has_submit_button( self, logged_in_page ):
        """
        CC card has submit button.

        Requires:
            - Authenticated session

        Ensures:
            - Submit button element exists
        """
        logged_in_page.goto( f"{BASE_URL}/app/notifications?classic=1" )
        logged_in_page.wait_for_load_state( "networkidle" )

        assert logged_in_page.get_by_test_id( "notifications-cc-submit-btn" ).count() > 0

    def test_cc_card_has_stt_button( self, logged_in_page ):
        """
        CC card has speech-to-text button.

        Requires:
            - Authenticated session

        Ensures:
            - STT button element exists
        """
        logged_in_page.goto( f"{BASE_URL}/app/notifications?classic=1" )
        logged_in_page.wait_for_load_state( "networkidle" )

        assert logged_in_page.get_by_test_id( "notifications-cc-stt-btn" ).count() > 0

    def test_cc_card_renders_in_sibling_shape( self, logged_in_page ):
        """
        CC card renders in the standard sibling DOM shape post-normalization
        (2026-05-11): header text, prompt textarea, submit button, status div.
        Zero references to the 5 dead UI blocks deleted by Phase 1 (no
        cc-execution-mode, cc-response, cc-option-b-controls, cc-session-info,
        cc-retired-banner). See
        src/rnd/v0.1.7/2026.05.09-cc-card-normalization/01-design.md.

        Requires:
            - Authenticated session

        Ensures:
            - Header h4 reads "🤖 Submit Claude Code Task"
            - Prompt textarea + submit button + status div all present
            - INTERACTIVE option exists but is disabled (Q2 FROZEN — visible
              breadcrumb for future return)
        """
        logged_in_page.goto( f"{BASE_URL}/app/notifications?classic=1" )
        logged_in_page.wait_for_load_state( "networkidle" )

        # Header text
        card_header = logged_in_page.locator( "#claude-code-submit-card h4" )
        assert card_header.count() > 0
        assert "Submit Claude Code Task" in card_header.text_content()

        # Standard sibling controls present
        assert logged_in_page.get_by_test_id( "notifications-cc-prompt-textarea" ).count() > 0
        assert logged_in_page.get_by_test_id( "notifications-cc-submit-btn" ).count() > 0
        assert logged_in_page.get_by_test_id( "notifications-cc-submit-status" ).count() > 0

        # INTERACTIVE option present but disabled (Q2 FROZEN)
        task_type_select = logged_in_page.get_by_test_id( "notifications-cc-task-type-select" )
        interactive_option = task_type_select.locator( "option[value='INTERACTIVE']" )
        assert interactive_option.count() > 0
        assert interactive_option.is_disabled()

    def test_cc_card_can_fill_prompt( self, logged_in_page ):
        """
        User can type into the CC prompt textarea.

        Requires:
            - Authenticated session

        Ensures:
            - Text can be entered into prompt textarea
        """
        logged_in_page.goto( f"{BASE_URL}/app/notifications?classic=1" )
        logged_in_page.wait_for_load_state( "networkidle" )

        textarea = logged_in_page.get_by_test_id( "notifications-cc-prompt-textarea" )
        if textarea.count() > 0 and textarea.is_visible():
            textarea.fill( "Test prompt for E2E" )
            assert "Test prompt" in textarea.input_value()


# ---------------------------------------------------------------------------
# Research Card
# ---------------------------------------------------------------------------

class TestResearchCard:
    """Tests for Deep Research job dispatch card."""

    def test_research_card_has_topic_input( self, logged_in_page ):
        """
        Research card has topic input field.

        Requires:
            - Authenticated session

        Ensures:
            - Topic input element exists
        """
        logged_in_page.goto( f"{BASE_URL}/app/notifications?classic=1" )
        logged_in_page.wait_for_load_state( "networkidle" )

        assert logged_in_page.get_by_test_id( "notifications-research-topic-input" ).count() > 0

    def test_research_card_has_budget_input( self, logged_in_page ):
        """
        Research card has budget input field.

        Requires:
            - Authenticated session

        Ensures:
            - Budget input element exists
        """
        logged_in_page.goto( f"{BASE_URL}/app/notifications?classic=1" )
        logged_in_page.wait_for_load_state( "networkidle" )

        assert logged_in_page.get_by_test_id( "notifications-research-budget-input" ).count() > 0

    def test_research_card_has_podcast_checkbox( self, logged_in_page ):
        """
        Research card has podcast generation checkbox.

        Requires:
            - Authenticated session

        Ensures:
            - Podcast checkbox element exists
        """
        logged_in_page.goto( f"{BASE_URL}/app/notifications?classic=1" )
        logged_in_page.wait_for_load_state( "networkidle" )

        assert logged_in_page.get_by_test_id( "notifications-research-podcast-checkbox" ).count() > 0

    def test_research_card_has_dry_run_and_submit( self, logged_in_page ):
        """
        Research card has dry-run checkbox and submit button.

        Requires:
            - Authenticated session

        Ensures:
            - Dry-run checkbox and submit button exist
        """
        logged_in_page.goto( f"{BASE_URL}/app/notifications?classic=1" )
        logged_in_page.wait_for_load_state( "networkidle" )

        assert logged_in_page.get_by_test_id( "notifications-research-dry-run-checkbox" ).count() > 0
        assert logged_in_page.get_by_test_id( "notifications-research-submit-btn" ).count() > 0

    def test_research_card_has_stt_button( self, logged_in_page ):
        """
        Research card has speech-to-text button.

        Requires:
            - Authenticated session

        Ensures:
            - STT button element exists
        """
        logged_in_page.goto( f"{BASE_URL}/app/notifications?classic=1" )
        logged_in_page.wait_for_load_state( "networkidle" )

        assert logged_in_page.get_by_test_id( "notifications-research-stt-btn" ).count() > 0

    def test_research_card_has_presentation_checkbox( self, logged_in_page ):
        """
        Research card has presentation generation checkbox.

        Requires:
            - Authenticated session

        Ensures:
            - Presentation checkbox element exists alongside podcast checkbox
        """
        logged_in_page.goto( f"{BASE_URL}/app/notifications?classic=1" )
        logged_in_page.wait_for_load_state( "networkidle" )

        assert logged_in_page.get_by_test_id( "notifications-research-presentation-checkbox" ).count() > 0

    def test_mode_selector_has_research_to_presentation( self, logged_in_page ):
        """
        Mode selector dropdown includes research_to_presentation option.

        Requires:
            - Authenticated session

        Ensures:
            - research_to_presentation option exists in mode dropdown
        """
        logged_in_page.goto( f"{BASE_URL}/app/notifications?classic=1" )
        logged_in_page.wait_for_load_state( "networkidle" )

        mode_select = logged_in_page.locator( "#agent-mode" )
        options = mode_select.locator( "option[value='research_to_presentation']" )
        assert options.count() > 0


# ---------------------------------------------------------------------------
# Test Suite Card
# ---------------------------------------------------------------------------

class TestTestSuiteCard:
    """Tests for Test Suite job dispatch card."""

    def test_test_suite_card_exists( self, logged_in_page ):
        """
        Test Suite card element exists on notifications page.

        Requires:
            - Authenticated session

        Ensures:
            - Test suite card container element exists
        """
        logged_in_page.goto( f"{BASE_URL}/app/notifications?classic=1" )
        logged_in_page.wait_for_load_state( "networkidle" )

        assert logged_in_page.get_by_test_id( "notifications-test-suite-card" ).count() > 0

    def test_test_suite_card_has_types_select( self, logged_in_page ):
        """
        Test Suite card has test types dropdown selector.

        Requires:
            - Authenticated session

        Ensures:
            - Types select element exists
        """
        logged_in_page.goto( f"{BASE_URL}/app/notifications?classic=1" )
        logged_in_page.wait_for_load_state( "networkidle" )

        assert logged_in_page.get_by_test_id( "notifications-test-suite-types-select" ).count() > 0

    def test_test_suite_card_has_pytest_args_input( self, logged_in_page ):
        """
        Test Suite card has pytest args text input.

        Requires:
            - Authenticated session

        Ensures:
            - Pytest args input element exists
        """
        logged_in_page.goto( f"{BASE_URL}/app/notifications?classic=1" )
        logged_in_page.wait_for_load_state( "networkidle" )

        assert logged_in_page.get_by_test_id( "notifications-test-suite-pytest-args-input" ).count() > 0

    def test_test_suite_card_has_dry_run_and_submit( self, logged_in_page ):
        """
        Test Suite card has dry-run checkbox and submit button.

        Requires:
            - Authenticated session

        Ensures:
            - Dry-run checkbox and submit button exist
        """
        logged_in_page.goto( f"{BASE_URL}/app/notifications?classic=1" )
        logged_in_page.wait_for_load_state( "networkidle" )

        assert logged_in_page.get_by_test_id( "notifications-test-suite-dry-run-checkbox" ).count() > 0
        assert logged_in_page.get_by_test_id( "notifications-test-suite-submit-btn" ).count() > 0

    def test_test_suite_card_has_schedule_option( self, logged_in_page ):
        """
        Test Suite card has schedule-for-later checkbox.

        Requires:
            - Authenticated session

        Ensures:
            - Schedule checkbox element exists
        """
        logged_in_page.goto( f"{BASE_URL}/app/notifications?classic=1" )
        logged_in_page.wait_for_load_state( "networkidle" )

        assert logged_in_page.get_by_test_id( "notifications-test-suite-schedule-checkbox" ).count() > 0

    def test_mode_selector_has_test_suite( self, logged_in_page ):
        """
        Mode selector dropdown includes test_suite option.

        Requires:
            - Authenticated session

        Ensures:
            - test_suite option exists in mode dropdown
        """
        logged_in_page.goto( f"{BASE_URL}/app/notifications?classic=1" )
        logged_in_page.wait_for_load_state( "networkidle" )

        mode_select = logged_in_page.get_by_test_id( "notifications-qa-mode-select" )
        options     = mode_select.locator( "option[value='test_suite']" )
        assert options.count() > 0
