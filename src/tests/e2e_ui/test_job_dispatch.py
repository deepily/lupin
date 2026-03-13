"""
E2E UI tests for agentic job dispatch cards on the notifications page.

Phase 6: Notifications & Q&A Tests — validates Claude Code, Research,
Podcast, and SWE Team submission card elements and interactions.

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
        logged_in_page.goto( f"{BASE_URL}/app/notifications" )
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
        logged_in_page.goto( f"{BASE_URL}/app/notifications" )
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
        logged_in_page.goto( f"{BASE_URL}/app/notifications" )
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
        logged_in_page.goto( f"{BASE_URL}/app/notifications" )
        logged_in_page.wait_for_load_state( "networkidle" )

        assert logged_in_page.get_by_test_id( "notifications-cc-task-type-select" ).count() > 0

    def test_cc_card_has_execution_mode_select( self, logged_in_page ):
        """
        CC card has execution mode selector.

        Requires:
            - Authenticated session

        Ensures:
            - Execution mode select element exists
        """
        logged_in_page.goto( f"{BASE_URL}/app/notifications" )
        logged_in_page.wait_for_load_state( "networkidle" )

        assert logged_in_page.get_by_test_id( "notifications-cc-execution-mode-select" ).count() > 0

    def test_cc_card_has_dry_run_checkbox( self, logged_in_page ):
        """
        CC card has dry-run checkbox.

        Requires:
            - Authenticated session

        Ensures:
            - Dry-run checkbox element exists
        """
        logged_in_page.goto( f"{BASE_URL}/app/notifications" )
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
        logged_in_page.goto( f"{BASE_URL}/app/notifications" )
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
        logged_in_page.goto( f"{BASE_URL}/app/notifications" )
        logged_in_page.wait_for_load_state( "networkidle" )

        assert logged_in_page.get_by_test_id( "notifications-cc-stt-btn" ).count() > 0

    def test_cc_card_has_session_controls( self, logged_in_page ):
        """
        CC card has interactive session controls (inject, interrupt, end).

        Requires:
            - Authenticated session

        Ensures:
            - Inject input, inject button, interrupt button, end button exist
        """
        logged_in_page.goto( f"{BASE_URL}/app/notifications" )
        logged_in_page.wait_for_load_state( "networkidle" )

        assert logged_in_page.get_by_test_id( "notifications-cc-inject-input" ).count() > 0
        assert logged_in_page.get_by_test_id( "notifications-cc-inject-btn" ).count() > 0
        assert logged_in_page.get_by_test_id( "notifications-cc-interrupt-btn" ).count() > 0
        assert logged_in_page.get_by_test_id( "notifications-cc-end-btn" ).count() > 0

    def test_cc_card_can_fill_prompt( self, logged_in_page ):
        """
        User can type into the CC prompt textarea.

        Requires:
            - Authenticated session

        Ensures:
            - Text can be entered into prompt textarea
        """
        logged_in_page.goto( f"{BASE_URL}/app/notifications" )
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
        logged_in_page.goto( f"{BASE_URL}/app/notifications" )
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
        logged_in_page.goto( f"{BASE_URL}/app/notifications" )
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
        logged_in_page.goto( f"{BASE_URL}/app/notifications" )
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
        logged_in_page.goto( f"{BASE_URL}/app/notifications" )
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
        logged_in_page.goto( f"{BASE_URL}/app/notifications" )
        logged_in_page.wait_for_load_state( "networkidle" )

        assert logged_in_page.get_by_test_id( "notifications-research-stt-btn" ).count() > 0


# ---------------------------------------------------------------------------
# Podcast Card
# ---------------------------------------------------------------------------

class TestPodcastCard:
    """Tests for Podcast Generator job dispatch card."""

    def test_podcast_card_has_source_input( self, logged_in_page ):
        """
        Podcast card has source input field.

        Requires:
            - Authenticated session

        Ensures:
            - Source input element exists
        """
        logged_in_page.goto( f"{BASE_URL}/app/notifications" )
        logged_in_page.wait_for_load_state( "networkidle" )

        assert logged_in_page.get_by_test_id( "notifications-podcast-source-input" ).count() > 0

    def test_podcast_card_has_dry_run_and_submit( self, logged_in_page ):
        """
        Podcast card has dry-run checkbox and submit button.

        Requires:
            - Authenticated session

        Ensures:
            - Dry-run checkbox and submit button exist
        """
        logged_in_page.goto( f"{BASE_URL}/app/notifications" )
        logged_in_page.wait_for_load_state( "networkidle" )

        assert logged_in_page.get_by_test_id( "notifications-podcast-dry-run-checkbox" ).count() > 0
        assert logged_in_page.get_by_test_id( "notifications-podcast-submit-btn" ).count() > 0

    def test_podcast_card_has_stt_button( self, logged_in_page ):
        """
        Podcast card has speech-to-text button.

        Requires:
            - Authenticated session

        Ensures:
            - STT button element exists
        """
        logged_in_page.goto( f"{BASE_URL}/app/notifications" )
        logged_in_page.wait_for_load_state( "networkidle" )

        assert logged_in_page.get_by_test_id( "notifications-podcast-stt-btn" ).count() > 0


# ---------------------------------------------------------------------------
# SWE Team Card
# ---------------------------------------------------------------------------

class TestSWETeamCard:
    """Tests for SWE Team job dispatch card."""

    def test_swe_card_has_task_textarea( self, logged_in_page ):
        """
        SWE Team card has task description textarea.

        Requires:
            - Authenticated session

        Ensures:
            - Task textarea element exists
        """
        logged_in_page.goto( f"{BASE_URL}/app/notifications" )
        logged_in_page.wait_for_load_state( "networkidle" )

        assert logged_in_page.get_by_test_id( "notifications-swe-task-textarea" ).count() > 0

    def test_swe_card_has_budget_and_timeout( self, logged_in_page ):
        """
        SWE Team card has budget and timeout inputs.

        Requires:
            - Authenticated session

        Ensures:
            - Budget and timeout input elements exist
        """
        logged_in_page.goto( f"{BASE_URL}/app/notifications" )
        logged_in_page.wait_for_load_state( "networkidle" )

        assert logged_in_page.get_by_test_id( "notifications-swe-budget-input" ).count() > 0
        assert logged_in_page.get_by_test_id( "notifications-swe-timeout-input" ).count() > 0

    def test_swe_card_has_trust_mode_select( self, logged_in_page ):
        """
        SWE Team card has trust mode selector.

        Requires:
            - Authenticated session

        Ensures:
            - Trust mode select element exists
        """
        logged_in_page.goto( f"{BASE_URL}/app/notifications" )
        logged_in_page.wait_for_load_state( "networkidle" )

        assert logged_in_page.get_by_test_id( "notifications-swe-trust-mode-select" ).count() > 0

    def test_swe_card_has_dry_run_and_submit( self, logged_in_page ):
        """
        SWE Team card has dry-run checkbox and submit button.

        Requires:
            - Authenticated session

        Ensures:
            - Dry-run checkbox and submit button exist
        """
        logged_in_page.goto( f"{BASE_URL}/app/notifications" )
        logged_in_page.wait_for_load_state( "networkidle" )

        assert logged_in_page.get_by_test_id( "notifications-swe-dry-run-checkbox" ).count() > 0
        assert logged_in_page.get_by_test_id( "notifications-swe-submit-btn" ).count() > 0

    def test_swe_card_has_stt_button( self, logged_in_page ):
        """
        SWE Team card has speech-to-text button.

        Requires:
            - Authenticated session

        Ensures:
            - STT button element exists
        """
        logged_in_page.goto( f"{BASE_URL}/app/notifications" )
        logged_in_page.wait_for_load_state( "networkidle" )

        assert logged_in_page.get_by_test_id( "notifications-swe-stt-btn" ).count() > 0
