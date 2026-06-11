"""
E2E UI tests for history-card / done-card rendering parity.

Validates the Phase 2 frontend changes from
src/rnd/v0.1.7/2026.04.26-cj-flow-card-rendering-unification/04-frontend-flag-removal.md:
- _isHistory boolean flag is gone
- queueName='history' is now passed through renderJobCard, with completion
  badges, interactions indicator, and delete dispatch all routed via
  queueName-driven branches
- delete dispatch goes through DELETE_HANDLERS lookup table
- DOM-id namespacing for history cards uses `history-${jobId}` prefix

Venue: :8000 (E2E UI is :8000-bucket per CLAUDE.md TESTING VENUES).
Run via: ./src/scripts/run-e2e-ui-tests.sh --bg -v -k test_history_card_parity
"""

from .conftest import BASE_URL


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def expand_history_section( page ):
    """Click the history expand button and wait for the API response."""
    expand_btn = page.get_by_test_id( "notifications-queue-history-expand-btn" )
    with page.expect_response( lambda r: "/api/job-history" in r.url ) as response_info:
        expand_btn.click()
    response_info.value
    page.wait_for_timeout( 300 )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestHistoryCardParity:
    """
    Tests that history bucket renders cards with the same structure as
    the done bucket — Phase 2 (2026-04-26 CJ Flow card-rendering unification).
    """

    def test_history_card_uses_namespaced_dom_id( self, seeded_history_page ):
        """
        History cards prefix DOM ids with 'history-' to avoid collision with
        live done cards. Confirms the `idKey = queueName === 'history' ? ...`
        path replaces the old `_isHistory` flag.
        """
        page, records = seeded_history_page
        page.goto( f"{BASE_URL}/app/notifications?classic=1" )
        page.wait_for_load_state( "networkidle" )
        expand_history_section( page )

        # At least one card should have a DOM id starting with 'history-'
        # (jobcard / interactions content / cancel button etc. all use the prefix)
        cards = page.locator( "[id^='job-interactions-history-']" )
        assert cards.count() > 0, "Expected at least one history- prefixed DOM id"

    def test_history_card_shows_completion_badge_for_completed_status( self, seeded_history_page ):
        """
        A completed job in history shows the ✓ completion badge.
        Validates the `queueName === 'done' || queueName === 'history'`
        gate added in Phase 2.
        """
        page, records = seeded_history_page
        page.goto( f"{BASE_URL}/app/notifications?classic=1" )
        page.wait_for_load_state( "networkidle" )
        expand_history_section( page )

        # Seeded set includes 2 completed jobs → expect at least one ✓ badge
        success_badges = page.locator( ".completion-badge.success" )
        assert success_badges.count() >= 1, "Expected at least one ✓ success badge for completed history rows"

    def test_history_card_shows_failed_badge_for_failed_status( self, seeded_history_page ):
        """
        A failed/interrupted job in history shows the ✗ completion badge.
        """
        page, records = seeded_history_page
        page.goto( f"{BASE_URL}/app/notifications?classic=1" )
        page.wait_for_load_state( "networkidle" )
        expand_history_section( page )

        # Seeded set includes 1 failed + 1 interrupted → expect ✗ badge(s)
        failed_badges = page.locator( ".completion-badge.failed" )
        assert failed_badges.count() >= 1, "Expected at least one ✗ failed badge for failed/interrupted history rows"

    def test_history_card_renders_notification_conversation_section( self, seeded_history_page ):
        """
        History cards render the '📋 Notification Conversation' section
        (gate updated to `queueName === 'done' || queueName === 'history'`).

        Pre-Phase-2: the section was gated to `queueName === 'done'` only,
        and renderHistoryCard mapped completed→'done' which made it work
        accidentally — but the spinner inside never resolved because of the
        hardcoded has_interactions=false.

        Post-Phase-2: the section renders explicitly for history queueName.
        """
        page, records = seeded_history_page
        page.goto( f"{BASE_URL}/app/notifications?classic=1" )
        page.wait_for_load_state( "networkidle" )
        expand_history_section( page )

        # The header text "Notification Conversation" should appear at least once
        conversation_headers = page.get_by_text( "📋 Notification Conversation" )
        assert conversation_headers.count() >= 1, "Expected '📋 Notification Conversation' on at least one history card"

    def test_history_card_delete_button_routes_to_history_endpoint( self, seeded_history_page ):
        """
        The prominent "🗑 Delete" button on a history card calls
        deleteHistoryJob, which hits DELETE /api/job-history/{id}
        (NOT /api/queue/...).

        Validates that history cards have ONLY the prominent splice button
        (no small ✕ in the header — that was removed 2026-04-26 to fix the
        double-delete UX complaint).
        """
        page, records = seeded_history_page
        page.goto( f"{BASE_URL}/app/notifications?classic=1" )
        page.wait_for_load_state( "networkidle" )
        expand_history_section( page )

        # Find a prominent delete button via the splice container
        # (renderHistoryActions emits <div class="history-action-buttons">…<button class="history-action-btn delete-btn">)
        delete_buttons = page.locator( ".history-action-buttons .delete-btn" )
        assert delete_buttons.count() >= 1, "Expected at least one prominent 🗑 Delete button on history cards"

        # And the small ✕ delete should NOT be present on history cards anymore
        # (Q1 fix 2026-04-26 — restricted the small-✕ gate to live buckets only)
        small_x_history = page.locator( "[id^='job-cancel-history-']" )
        assert small_x_history.count() == 0, (
            "History cards must NOT render the small ✕ delete button — "
            "that was removed to eliminate the double-delete UX (Q1 fix 2026-04-26). "
            f"Found {small_x_history.count()} unexpected small-✕ buttons."
        )

        # Auto-confirm the delete prompt
        page.on( "dialog", lambda dialog: dialog.accept() )

        # Click the prominent delete button and verify the API call goes to /api/job-history/
        with page.expect_response( lambda r: "/api/job-history/" in r.url and r.request.method == "DELETE" ) as response_info:
            delete_buttons.first.click()

        response = response_info.value
        assert response.ok, f"Expected successful DELETE /api/job-history/ — got {response.status}"

    def test_renderhistorycard_no_longer_sets_isHistory_flag( self, seeded_history_page ):
        """
        Sanity check: after Phase 2, the `_isHistory` flag is gone from the
        normalized object passed to renderJobCard. The history-pane
        distinction is carried by `queueName='history'` instead.

        We can't directly inspect the JS object, but we can confirm the DOM
        has the expected `history-` prefixed elements (which only appear when
        queueName === 'history' is correctly passed through).
        """
        page, records = seeded_history_page
        page.goto( f"{BASE_URL}/app/notifications?classic=1" )
        page.wait_for_load_state( "networkidle" )
        expand_history_section( page )

        # Two tell-tales of queueName='history' being threaded through correctly:
        #   1. The outer card DOM id is `job-card-history-{jobId}` (idKey logic
        #      at notifications.js:6891 namespaces by queueName).
        #   2. The status CSS class is `status-history` (statusClass at
        #      notifications.js:6835 derives from queueName directly).
        history_cards = page.locator( "[id^='job-card-history-']" )
        assert history_cards.count() >= 1, (
            "Expected at least one history-namespaced card DOM id "
            "(`job-card-history-{jobId}`) — this only renders when queueName='history' "
            "is correctly passed through renderJobCard."
        )

        # And every visible history card should carry the canonical status-history class
        first_card_classes = history_cards.first.get_attribute( "class" ) or ""
        assert "status-history" in first_card_classes, (
            f"Expected 'status-history' in card classes; got: {first_card_classes!r}. "
            "renderJobCard derives statusClass from queueName — the absence indicates "
            "queueName isn't 'history' on the renderer's side."
        )


class TestDeleteHandlerRouting:
    """
    Tests for the DELETE_HANDLERS lookup table that replaces the old
    `_isHistory` ternary. Validates that:
    - Live-bucket cards (todo/run/done/dead) → /api/queue/{queueName}/{id}
    - History cards → /api/job-history/{id}
    """

    def test_history_delete_routes_to_job_history_endpoint( self, seeded_history_page ):
        """
        Prominent 🗑 Delete button on a history card → DELETE /api/job-history/{id}
        (target the splice container .history-action-buttons .delete-btn —
        the small ✕ button is no longer rendered for history per Q1 fix 2026-04-26).
        """
        page, records = seeded_history_page
        page.goto( f"{BASE_URL}/app/notifications?classic=1" )
        page.wait_for_load_state( "networkidle" )
        expand_history_section( page )

        page.on( "dialog", lambda dialog: dialog.accept() )

        delete_btn = page.locator( ".history-action-buttons .delete-btn" ).first
        with page.expect_response( lambda r: "/api/job-history/" in r.url and r.request.method == "DELETE" ) as response_info:
            delete_btn.click()
        assert response_info.value.ok
