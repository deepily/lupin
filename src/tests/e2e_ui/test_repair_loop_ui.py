"""
E2E UI tests for the automated repair loop (BFE Phase 6).

Verifies that the repair chain (failed job → BFE fix → resubmitted job)
is correctly displayed in the notifications UI job history section.

Uses seeded data: 3 linked job_history records injected directly into
the test database. No live BFE execution needed.

Requires:
    - Server running on port 7999 in Testing mode (lupin_db_test)
    - run-e2e-ui-tests.sh handles config hot-swap

Run:
    ./src/scripts/run-e2e-ui-tests.sh --bg -v -k test_repair_loop
"""

import pytest

from tests.e2e_ui.conftest import BASE_URL, get_user_id_from_page
from tests.e2e_ui.test_job_history_ui import expand_history_section


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture( scope="function" )
def seeded_repair_chain_page( logged_in_page ):
    """
    Seed DB with a 3-job repair chain, navigate to notifications.

    Requires:
        - logged_in_page fixture (authenticated browser session)

    Ensures:
        - 3 linked job_history rows inserted (failed → BFE → resubmitted)
        - Page navigated to /app/notifications
        - Returns (page, records) tuple

    Returns:
        tuple: (Playwright page, list of 3 seeded record dicts)
    """
    from tests.helpers.repair_chain_seed import seed_repair_chain

    user_id    = get_user_id_from_page( logged_in_page )
    user_email = "e2e_test@example.com"
    records    = seed_repair_chain( user_id, user_email )

    logged_in_page.goto( f"{BASE_URL}/app/notifications" )
    logged_in_page.wait_for_load_state( "networkidle" )

    return logged_in_page, records


# =============================================================================
# Repair Chain Visibility
# =============================================================================

class TestRepairChainVisibility:
    """Verify the 3-job repair chain is visible in job history."""

    def test_repair_chain_visible_in_history( self, seeded_repair_chain_page ):
        """
        All 3 repair chain jobs appear in the history section.

        Requires:
            - 3 seeded repair chain records

        Ensures:
            - History container has at least 3 .job-card elements
        """
        page, records = seeded_repair_chain_page
        expand_history_section( page )

        container = page.locator( "#history-jobs-container" )
        cards     = container.locator( ".job-card" )
        assert cards.count() >= 3, f"Expected >= 3 job cards, got {cards.count()}"

    def test_history_count_includes_chain( self, seeded_repair_chain_page ):
        """
        Count badge includes all 3 repair chain jobs.

        Requires:
            - 3 seeded repair chain records

        Ensures:
            - Badge text is >= "3"
        """
        page, records = seeded_repair_chain_page
        expand_history_section( page )

        badge = page.locator( "#history-count-badge" )
        count = int( badge.text_content() or "0" )
        assert count >= 3, f"Expected badge >= 3, got {count}"


# =============================================================================
# Status Styling
# =============================================================================

class TestRepairChainStyling:
    """Verify correct CSS status classes on repair chain job cards."""

    def test_original_failure_has_dead_styling( self, seeded_repair_chain_page ):
        """
        The original failed job card in the history pane carries the
        unified `status-history` outer class (post 2026-04-26 unification —
        was `status-dead` under the old status→queue mapping). The
        failed-state signal is now carried by the inner ✗ completion badge.

        Requires:
            - Seeded record 0 (repair-001) has status=failed

        Ensures:
            - Card has 'status-history' in its class list
            - Card contains a `.completion-badge.failed` (✗) inner element
        """
        page, records = seeded_repair_chain_page
        expand_history_section( page )

        failed_rec = records[ 0 ]
        assert failed_rec[ "status" ] == "failed"

        card = page.locator( f".job-card[data-job-id='{failed_rec[ 'id_hash' ]}']" )
        assert card.count() > 0, f"Failed job card not found: {failed_rec[ 'id_hash' ]}"
        classes = card.get_attribute( "class" ) or ""
        assert "status-history" in classes, f"Expected 'status-history', got: {classes!r}"
        failed_badge = card.locator( ".completion-badge.failed" )
        assert failed_badge.count() > 0, (
            "Expected a `.completion-badge.failed` (✗) inside the failed history card."
        )

    def test_bfe_job_has_completed_styling( self, seeded_repair_chain_page ):
        """
        The BFE job card in the history pane carries the unified
        `status-history` outer class (post 2026-04-26 unification —
        was `status-done` under the old status→queue mapping). The
        completed-state signal is now carried by the inner ✓ completion badge.

        Requires:
            - Seeded record 1 (repair-bfe-002) has status=completed

        Ensures:
            - Card has 'status-history' in its class list
            - Card contains a `.completion-badge.success` (✓) inner element
        """
        page, records = seeded_repair_chain_page
        expand_history_section( page )

        bfe_rec = records[ 1 ]
        assert bfe_rec[ "status" ] == "completed"

        card = page.locator( f".job-card[data-job-id='{bfe_rec[ 'id_hash' ]}']" )
        assert card.count() > 0, f"BFE job card not found: {bfe_rec[ 'id_hash' ]}"
        classes = card.get_attribute( "class" ) or ""
        assert "status-history" in classes, f"Expected 'status-history', got: {classes!r}"
        success_badge = card.locator( ".completion-badge.success" )
        assert success_badge.count() > 0, (
            "Expected a `.completion-badge.success` (✓) inside the completed BFE history card."
        )

    def test_resubmitted_job_has_completed_styling( self, seeded_repair_chain_page ):
        """
        The resubmitted job card in the history pane carries the unified
        `status-history` outer class (post 2026-04-26 unification —
        was `status-done` under the old status→queue mapping). The
        completed-state signal is now carried by the inner ✓ completion badge.

        Requires:
            - Seeded record 2 (repair-003) has status=completed

        Ensures:
            - Card has 'status-history' in its class list
            - Card contains a `.completion-badge.success` (✓) inner element
        """
        page, records = seeded_repair_chain_page
        expand_history_section( page )

        resubmit_rec = records[ 2 ]
        assert resubmit_rec[ "status" ] == "completed"

        card = page.locator( f".job-card[data-job-id='{resubmit_rec[ 'id_hash' ]}']" )
        assert card.count() > 0, f"Resubmitted job card not found: {resubmit_rec[ 'id_hash' ]}"
        classes = card.get_attribute( "class" ) or ""
        assert "status-history" in classes, f"Expected 'status-history', got: {classes!r}"
        success_badge = card.locator( ".completion-badge.success" )
        assert success_badge.count() > 0, (
            "Expected a `.completion-badge.success` (✓) inside the completed resubmitted history card."
        )


# =============================================================================
# Error Display
# =============================================================================

class TestRepairChainErrorDisplay:
    """Verify error text is visible on the failed job card."""

    def test_original_failure_shows_error( self, seeded_repair_chain_page ):
        """
        The original failed job card displays the error message.

        Requires:
            - Seeded record 0 has error text

        Ensures:
            - Card contains a portion of the error text
        """
        page, records = seeded_repair_chain_page
        expand_history_section( page )

        failed_rec = records[ 0 ]
        card = page.locator( f".job-card[data-job-id='{failed_rec[ 'id_hash' ]}']" )
        card_text = card.text_content() or ""

        # The error should appear somewhere in the card (may be truncated)
        assert "missing_slide_config" in card_text or "KeyError" in card_text, \
            f"Expected error text in card, got: {card_text[ :200 ]}"


# =============================================================================
# Chronological Order
# =============================================================================

class TestRepairChainOrder:
    """Verify repair chain jobs appear in chronological order."""

    def test_repair_chain_chronological_order( self, seeded_repair_chain_page ):
        """
        Jobs appear in reverse chronological order (newest first) in history.

        Requires:
            - 3 seeded records with staggered created_at

        Ensures:
            - Resubmitted job (newest) appears before original failure (oldest)
            - Based on DOM order in history container
        """
        page, records = seeded_repair_chain_page
        expand_history_section( page )

        container = page.locator( "#history-jobs-container" )
        all_cards = container.locator( ".job-card" )
        card_count = all_cards.count()

        if card_count < 3:
            pytest.skip( f"Only {card_count} cards found, need >= 3" )

        # Collect job IDs in DOM order
        card_ids = []
        for i in range( card_count ):
            job_id = all_cards.nth( i ).get_attribute( "data-job-id" )
            if job_id:
                card_ids.append( job_id )

        # Find indices of our 3 repair chain jobs
        original_id  = records[ 0 ][ "id_hash" ]
        bfe_id       = records[ 1 ][ "id_hash" ]
        resubmit_id  = records[ 2 ][ "id_hash" ]

        # All three should be present
        assert original_id in card_ids, f"Original job not in history: {original_id}"
        assert bfe_id in card_ids, f"BFE job not in history: {bfe_id}"
        assert resubmit_id in card_ids, f"Resubmit job not in history: {resubmit_id}"

        # Reverse chronological: resubmit (newest) should appear before original (oldest)
        idx_resubmit = card_ids.index( resubmit_id )
        idx_original = card_ids.index( original_id )
        assert idx_resubmit < idx_original, \
            f"Expected resubmit ({idx_resubmit}) before original ({idx_original}) in reverse-chron order"
