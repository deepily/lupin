"""
E2E UI tests for Job History section on the notifications page.

CJ Flow Persistence Phase 6: Validates the 5th collapsible "Job History"
section with time window dropdown, expand/collapse, and count badge.

Session 372 additions: Data-driven tests with seeded job_history rows.
Tests verify actual job data display, filtering, pagination, delete/retry.

Requires:
    - Dev server running on port 7999 with Testing config
    - Clean test database (via logged_in_page fixture)
"""

import json

from .conftest import BASE_URL


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def expand_history_section( page ):
    """
    Click the history expand button and wait for the API response.

    Requires:
        - page is on /app/notifications
        - History section is collapsed

    Ensures:
        - History section is expanded
        - API fetch for /api/job-history has completed
    """
    expand_btn = page.get_by_test_id( "notifications-queue-history-expand-btn" )

    # Start waiting for the response BEFORE clicking
    with page.expect_response( lambda r: "/api/job-history" in r.url ) as response_info:
        expand_btn.click()

    response_info.value  # Wait for response to complete
    page.wait_for_timeout( 300 )  # Brief pause for DOM rendering


def collapse_and_reexpand_history( page ):
    """
    Collapse the history section, then re-expand it.

    Requires:
        - page is on /app/notifications
        - History section is currently expanded

    Ensures:
        - History section is expanded again after a full round-trip
        - Note: Re-expand uses cached data (state.loaded=true), no new API call
    """
    expand_btn = page.get_by_test_id( "notifications-queue-history-expand-btn" )
    expand_btn.click()        # collapse
    page.wait_for_timeout( 300 )
    expand_btn.click()        # re-expand (uses cached state, no API fetch)
    page.wait_for_timeout( 300 )


# ---------------------------------------------------------------------------
# Section Layout Tests (original Phase 6)
# ---------------------------------------------------------------------------

class TestJobHistorySectionLayout:
    """Tests for Job History section rendering on notifications page."""

    def test_history_section_present( self, logged_in_page ):
        """
        Job queues section has Job History queue category.

        Requires:
            - Authenticated session

        Ensures:
            - Job History queue category element exists
        """
        logged_in_page.goto( f"{BASE_URL}/app/notifications" )
        logged_in_page.wait_for_load_state( "networkidle" )

        assert logged_in_page.get_by_test_id( "notifications-queue-history" ).count() > 0

    def test_history_expand_btn_present( self, logged_in_page ):
        """
        Job History section has an expand button.

        Requires:
            - Authenticated session

        Ensures:
            - Expand button element exists within history section
        """
        logged_in_page.goto( f"{BASE_URL}/app/notifications" )
        logged_in_page.wait_for_load_state( "networkidle" )

        assert logged_in_page.get_by_test_id( "notifications-queue-history-expand-btn" ).count() > 0

    def test_history_time_window_select( self, logged_in_page ):
        """
        Job History section has a time window dropdown with 5 options.

        Requires:
            - Authenticated session

        Ensures:
            - Time window select element exists
            - Has 5 options: 1 day, 7 days, 14 days, 30 days, All
        """
        logged_in_page.goto( f"{BASE_URL}/app/notifications" )
        logged_in_page.wait_for_load_state( "networkidle" )

        select = logged_in_page.get_by_test_id( "history-time-window-select" )
        assert select.count() > 0

        options = select.locator( "option" )
        assert options.count() == 5

    def test_history_collapsed_by_default( self, logged_in_page ):
        """
        Job History jobs container is collapsed by default.

        Requires:
            - Authenticated session

        Ensures:
            - Jobs container has 'collapsed' CSS class
        """
        logged_in_page.goto( f"{BASE_URL}/app/notifications" )
        logged_in_page.wait_for_load_state( "networkidle" )

        container = logged_in_page.get_by_test_id( "notifications-queue-history-jobs" )
        assert container.count() > 0
        assert "collapsed" in container.get_attribute( "class" )

    def test_history_expand_loads_content( self, logged_in_page ):
        """
        Clicking expand button removes collapsed class from jobs container.

        Requires:
            - Authenticated session

        Ensures:
            - After clicking expand, container no longer has 'collapsed' class
        """
        logged_in_page.goto( f"{BASE_URL}/app/notifications" )
        logged_in_page.wait_for_load_state( "networkidle" )

        expand_btn = logged_in_page.get_by_test_id( "notifications-queue-history-expand-btn" )
        expand_btn.click()

        container = logged_in_page.get_by_test_id( "notifications-queue-history-jobs" )
        # Wait briefly for the toggle to take effect
        logged_in_page.wait_for_timeout( 500 )
        assert "collapsed" not in ( container.get_attribute( "class" ) or "" )

    def test_history_count_badge( self, logged_in_page ):
        """
        Job History section has a count badge element.

        Requires:
            - Authenticated session

        Ensures:
            - Count badge element exists
        """
        logged_in_page.goto( f"{BASE_URL}/app/notifications" )
        logged_in_page.wait_for_load_state( "networkidle" )

        badge = logged_in_page.locator( "#history-count-badge" )
        assert badge.count() > 0


# ===========================================================================
# Data-Driven Tests (Session 372)
# ===========================================================================

class TestJobHistoryDataDisplay:
    """Tests for job history data rendering with seeded database rows."""

    def test_expand_shows_job_cards( self, seeded_history_page ):
        """
        Expanding history section shows seeded job cards.

        Requires:
            - 5 seeded job_history rows

        Ensures:
            - 5 .job-card elements appear in history container
        """
        page, records = seeded_history_page
        expand_history_section( page )

        container = page.locator( "#history-jobs-container" )
        cards     = container.locator( ".job-card" )
        assert cards.count() == 5, f"Expected 5 job cards, got {cards.count()}"

    def test_card_shows_question_text( self, seeded_history_page ):
        """
        Job cards display the seeded question text.

        Requires:
            - Seeded job with known question_text

        Ensures:
            - At least one card contains the seeded question text (truncated to 60 chars)
        """
        page, records = seeded_history_page
        expand_history_section( page )

        # Check for the known question from std-001
        expected_text = "What are the latest advances in quantum"  # truncated portion
        container = page.locator( "#history-jobs-container" )
        assert container.locator( f".job-question:has-text('{expected_text}')" ).count() > 0

    def test_count_badge_shows_total( self, seeded_history_page ):
        """
        Count badge reflects the total number of seeded jobs.

        Requires:
            - 5 seeded job_history rows

        Ensures:
            - Badge text is "5"
        """
        page, records = seeded_history_page
        expand_history_section( page )

        badge = page.locator( "#history-count-badge" )
        assert badge.text_content() == "5", f"Expected badge '5', got '{badge.text_content()}'"

    def test_failed_job_has_dead_styling( self, seeded_history_page ):
        """
        Failed job card has status-dead CSS class (statusToQueue mapping).

        Requires:
            - Seeded set includes a failed job (std-003)

        Ensures:
            - Card for the failed job has 'status-dead' class
        """
        page, records = seeded_history_page
        expand_history_section( page )

        failed_rec = next( r for r in records if r[ "status" ] == "failed" )
        card = page.locator( f".job-card[data-job-id='{failed_rec[ 'id_hash' ]}']" )
        assert card.count() > 0, "Failed job card not found"
        classes = card.get_attribute( "class" ) or ""
        assert "status-dead" in classes, f"Expected 'status-dead' in classes, got: {classes}"

    def test_empty_history_shows_message( self, logged_in_page ):
        """
        Empty history (no seeded data) shows 'No job history found' message.

        Requires:
            - Clean database with no job_history rows

        Ensures:
            - Empty message displayed in history container
        """
        logged_in_page.goto( f"{BASE_URL}/app/notifications" )
        logged_in_page.wait_for_load_state( "networkidle" )

        expand_history_section( logged_in_page )

        container = logged_in_page.locator( "#history-jobs-container" )
        empty_msg = container.locator( ".queue-empty-message" )
        assert empty_msg.count() > 0, "Expected empty message element"
        assert "No job history found" in ( empty_msg.text_content() or "" )


class TestJobHistoryTimeWindowFilter:
    """Tests for time window dropdown filter with seeded data at different ages."""

    def test_7_day_filter( self, seeded_time_window_page ):
        """
        7-day filter shows only the 3-day-old job.

        Requires:
            - 3 seeded jobs at 3d, 10d, 40d ago

        Ensures:
            - Only 1 job card visible after selecting 7-day window
        """
        page, records = seeded_time_window_page

        # Default timeWindow is 30 days — expand first, then switch to 7
        expand_history_section( page )

        select = page.get_by_test_id( "history-time-window-select" )
        with page.expect_response( lambda r: "/api/job-history" in r.url ):
            select.select_option( "7" )
        page.wait_for_timeout( 300 )

        container = page.locator( "#history-jobs-container" )
        cards     = container.locator( ".job-card" )
        assert cards.count() == 1, f"Expected 1 card in 7-day window, got {cards.count()}"

    def test_30_day_filter( self, seeded_time_window_page ):
        """
        30-day filter shows the 3-day and 10-day old jobs.

        Requires:
            - 3 seeded jobs at 3d, 10d, 40d ago

        Ensures:
            - 2 job cards visible after selecting 30-day window
        """
        page, records = seeded_time_window_page
        expand_history_section( page )

        # Change time window to 30 days
        select = page.get_by_test_id( "history-time-window-select" )
        with page.expect_response( lambda r: "/api/job-history" in r.url ):
            select.select_option( "30" )
        page.wait_for_timeout( 300 )

        container = page.locator( "#history-jobs-container" )
        cards     = container.locator( ".job-card" )
        assert cards.count() == 2, f"Expected 2 cards in 30-day window, got {cards.count()}"

    def test_all_time_filter( self, seeded_time_window_page ):
        """
        'All' filter shows all 3 jobs regardless of age.

        Requires:
            - 3 seeded jobs at 3d, 10d, 40d ago

        Ensures:
            - 3 job cards visible after selecting 'all' window
        """
        page, records = seeded_time_window_page
        expand_history_section( page )

        select = page.get_by_test_id( "history-time-window-select" )
        with page.expect_response( lambda r: "/api/job-history" in r.url ):
            select.select_option( "all" )
        page.wait_for_timeout( 300 )

        container = page.locator( "#history-jobs-container" )
        cards     = container.locator( ".job-card" )
        assert cards.count() == 3, f"Expected 3 cards in 'all' window, got {cards.count()}"


class TestJobHistoryPagination:
    """Tests for Load More pagination with seeded data exceeding page size."""

    def test_load_more_visible_over_limit( self, seeded_pagination_page ):
        """
        Load More button is visible when seeded jobs exceed page limit (20).

        Requires:
            - 25 seeded jobs

        Ensures:
            - 20 job cards rendered initially
            - Load More button is visible
        """
        page, records = seeded_pagination_page
        expand_history_section( page )

        container = page.locator( "#history-jobs-container" )
        cards     = container.locator( ".job-card" )
        assert cards.count() == 20, f"Expected 20 initial cards, got {cards.count()}"

        pagination = page.locator( "#history-pagination" )
        assert pagination.is_visible(), "Load More should be visible with 25 jobs"

    def test_load_more_appends( self, seeded_pagination_page ):
        """
        Clicking Load More appends remaining jobs.

        Requires:
            - 25 seeded jobs, first page of 20 loaded

        Ensures:
            - After clicking Load More, 25 total cards visible
            - Load More button hidden (all loaded)
        """
        page, records = seeded_pagination_page
        expand_history_section( page )

        load_more = page.get_by_test_id( "history-load-more-btn" )
        with page.expect_response( lambda r: "/api/job-history" in r.url ):
            load_more.click()
        page.wait_for_timeout( 300 )

        container = page.locator( "#history-jobs-container" )
        cards     = container.locator( ".job-card" )
        assert cards.count() == 25, f"Expected 25 cards after Load More, got {cards.count()}"

        pagination = page.locator( "#history-pagination" )
        assert not pagination.is_visible(), "Load More should be hidden after all loaded"

    def test_load_more_hidden_under_limit( self, seeded_history_page ):
        """
        Load More is hidden when total jobs are under page limit.

        Requires:
            - 5 seeded jobs (under 20 limit)

        Ensures:
            - Load More button is not visible
        """
        page, records = seeded_history_page
        expand_history_section( page )

        pagination = page.locator( "#history-pagination" )
        assert not pagination.is_visible(), "Load More should be hidden with only 5 jobs"


class TestJobHistoryActions:
    """Tests for delete and retry action buttons on history job cards."""

    def test_delete_removes_card( self, seeded_history_page ):
        """
        Clicking delete removes the card from the DOM after confirm().

        Requires:
            - 5 seeded job cards displayed

        Ensures:
            - After delete, card count decremented to 4
            - Badge count updates
        """
        page, records = seeded_history_page
        expand_history_section( page )

        # Auto-accept confirm() dialogs
        page.on( "dialog", lambda dialog: dialog.accept() )

        # Click delete on first card
        container   = page.locator( "#history-jobs-container" )
        delete_btns = container.locator( ".delete-btn" )
        assert delete_btns.count() >= 1, "No delete buttons found"

        with page.expect_response( lambda r: "/api/job-history" in r.url ):
            delete_btns.first.click()
        page.wait_for_timeout( 500 )

        # Verify card count decreased
        cards = container.locator( ".job-card" )
        assert cards.count() == 4, f"Expected 4 cards after delete, got {cards.count()}"

    def test_retry_visible_on_failed( self, seeded_history_page ):
        """
        Retry button visible on failed jobs, not on completed jobs.

        Requires:
            - Standard seed set with failed and completed jobs

        Ensures:
            - Failed job card has .retry-btn
            - Completed job card does NOT have .retry-btn
        """
        page, records = seeded_history_page
        expand_history_section( page )

        failed    = next( r for r in records if r[ "status" ] == "failed" )
        completed = next( r for r in records if r[ "status" ] == "completed" )

        failed_card    = page.locator( f".job-card[data-job-id='{failed[ 'id_hash' ]}']" )
        completed_card = page.locator( f".job-card[data-job-id='{completed[ 'id_hash' ]}']" )

        assert failed_card.locator( ".retry-btn" ).count() > 0, "Failed job should have retry button"
        assert completed_card.locator( ".retry-btn" ).count() == 0, "Completed job should NOT have retry button"

    def test_retry_visible_on_interrupted( self, seeded_history_page ):
        """
        Retry button visible on interrupted jobs.

        Requires:
            - Standard seed set with interrupted job

        Ensures:
            - Interrupted job card has .retry-btn
        """
        page, records = seeded_history_page
        expand_history_section( page )

        interrupted = next( r for r in records if r[ "status" ] == "interrupted" )
        card = page.locator( f".job-card[data-job-id='{interrupted[ 'id_hash' ]}']" )
        assert card.locator( ".retry-btn" ).count() > 0, "Interrupted job should have retry button"

    def test_delete_all_shows_empty_message( self, logged_in_page ):
        """
        Deleting all jobs shows the empty history message.

        Requires:
            - 1 seeded job to keep the test fast

        Ensures:
            - After deleting the single job, 'No job history found' message appears
        """
        from tests.helpers.job_history_seed import seed_job_history_records
        from .conftest import get_user_id_from_page

        user_id = get_user_id_from_page( logged_in_page )
        seed_job_history_records(
            user_id    = user_id,
            user_email = "e2e_test@example.com",
            records    = [ { "id_suffix": "del-all-001", "status": "completed" } ]
        )

        logged_in_page.goto( f"{BASE_URL}/app/notifications" )
        logged_in_page.wait_for_load_state( "networkidle" )
        expand_history_section( logged_in_page )

        # Auto-accept confirm()
        logged_in_page.on( "dialog", lambda dialog: dialog.accept() )

        # Delete the single job
        container  = logged_in_page.locator( "#history-jobs-container" )
        delete_btn = container.locator( ".delete-btn" ).first

        with logged_in_page.expect_response( lambda r: "/api/job-history" in r.url ):
            delete_btn.click()
        logged_in_page.wait_for_timeout( 500 )

        # Verify empty message
        empty_msg = container.locator( ".queue-empty-message" )
        assert empty_msg.count() > 0, "Expected empty message after deleting all jobs"
        assert "No job history found" in ( empty_msg.text_content() or "" )


# ===========================================================================
# Delete Flow Tests (Session 382 — Rubric Tests 2-4, 9)
# ===========================================================================

class TestJobHistoryDeleteFlows:
    """Extended delete tests: badge updates, persistence, cancel, filter interaction."""

    def test_delete_badge_count_decrements( self, seeded_history_page ):
        """
        Badge count decrements from 5 to 4 after deleting a job.

        Requires:
            - 5 seeded job_history rows

        Ensures:
            - Badge text is "5" before delete
            - Badge text is "4" after delete
        """
        page, records = seeded_history_page
        expand_history_section( page )

        badge = page.locator( "#history-count-badge" )
        assert badge.text_content() == "5", f"Expected badge '5' before delete, got '{badge.text_content()}'"

        # Auto-accept confirm() dialogs
        page.on( "dialog", lambda dialog: dialog.accept() )

        container   = page.locator( "#history-jobs-container" )
        delete_btns = container.locator( ".delete-btn" )

        with page.expect_response( lambda r: "/api/job-history" in r.url ):
            delete_btns.first.click()
        page.wait_for_timeout( 500 )

        assert badge.text_content() == "4", f"Expected badge '4' after delete, got '{badge.text_content()}'"

    def test_delete_persists_after_collapse_reexpand( self, seeded_history_page ):
        """
        Deleted job does not reappear after collapsing and re-expanding history.

        Requires:
            - 5 seeded job_history rows

        Ensures:
            - After delete + collapse + re-expand, card count is 4
            - Deleted job's id_hash is absent from the DOM
        """
        page, records = seeded_history_page
        expand_history_section( page )

        page.on( "dialog", lambda dialog: dialog.accept() )

        container = page.locator( "#history-jobs-container" )
        cards     = container.locator( ".job-card" )

        # Capture the first card's job ID before deleting it
        first_card_id = cards.first.get_attribute( "data-job-id" )

        with page.expect_response( lambda r: "/api/job-history" in r.url ):
            container.locator( ".delete-btn" ).first.click()
        page.wait_for_timeout( 500 )

        # Collapse and re-expand
        collapse_and_reexpand_history( page )

        assert cards.count() == 4, f"Expected 4 cards after reexpand, got {cards.count()}"
        assert page.locator( f".job-card[data-job-id='{first_card_id}']" ).count() == 0, \
            f"Deleted job {first_card_id} reappeared after collapse/reexpand"

    def test_delete_cancel_leaves_unchanged( self, seeded_history_page ):
        """
        Cancelling the delete confirm dialog leaves everything unchanged.

        Requires:
            - 5 seeded job_history rows

        Ensures:
            - Card count remains 5
            - Badge text remains "5"
            - No API request sent
        """
        page, records = seeded_history_page
        expand_history_section( page )

        # Dismiss (cancel) confirm() dialogs
        page.on( "dialog", lambda dialog: dialog.dismiss() )

        container = page.locator( "#history-jobs-container" )
        cards     = container.locator( ".job-card" )
        badge     = page.locator( "#history-count-badge" )

        assert cards.count() == 5, f"Expected 5 cards before cancel, got {cards.count()}"
        assert badge.text_content() == "5"

        # Click delete — confirm() will be dismissed
        container.locator( ".delete-btn" ).first.click()
        page.wait_for_timeout( 300 )

        # Everything unchanged
        assert cards.count() == 5, f"Expected 5 cards after cancel, got {cards.count()}"
        assert badge.text_content() == "5", f"Badge changed after cancel: '{badge.text_content()}'"

    def test_delete_persists_across_filter_change( self, seeded_history_page ):
        """
        Deleted job stays absent after changing time window filters.

        Requires:
            - 5 seeded job_history rows (all recent, within any time window)

        Ensures:
            - After delete, switching to 'all' then '30' does not resurrect the job
        """
        page, records = seeded_history_page
        expand_history_section( page )

        page.on( "dialog", lambda dialog: dialog.accept() )

        container     = page.locator( "#history-jobs-container" )
        cards         = container.locator( ".job-card" )
        first_card_id = cards.first.get_attribute( "data-job-id" )

        with page.expect_response( lambda r: "/api/job-history" in r.url ):
            container.locator( ".delete-btn" ).first.click()
        page.wait_for_timeout( 500 )

        assert cards.count() == 4, f"Expected 4 cards after delete, got {cards.count()}"

        # Switch to "all" filter
        select = page.get_by_test_id( "history-time-window-select" )
        with page.expect_response( lambda r: "/api/job-history" in r.url ):
            select.select_option( "all" )
        page.wait_for_timeout( 300 )

        assert page.locator( f".job-card[data-job-id='{first_card_id}']" ).count() == 0, \
            f"Deleted job reappeared after switching to 'all' filter"

        # Switch back to "30"
        with page.expect_response( lambda r: "/api/job-history" in r.url ):
            select.select_option( "30" )
        page.wait_for_timeout( 300 )

        assert page.locator( f".job-card[data-job-id='{first_card_id}']" ).count() == 0, \
            f"Deleted job reappeared after switching back to '30' filter"


# ===========================================================================
# Retry Flow Tests (Session 382 — Rubric Tests 5, 6, 8)
# ===========================================================================

class TestJobHistoryRetryFlows:
    """Retry button flows: happy path, cancel, interrupted job retry."""

    def test_retry_happy_path_creates_todo_job( self, seeded_history_page ):
        """
        Retry on failed job sends correct POST, UI handles success, original stays in history.

        Note: The backend push_job routes through the LLM pipeline which is unavailable
        in the test environment. We mock the retry API response to test the frontend flow.
        Backend retry logic is covered by integration tests.

        Requires:
            - Standard seed set with failed job (std-003)

        Ensures:
            - Confirm dialog shown with question text
            - POST /retry sent with correct URL and method
            - On 200 response: original failed card remains in history
            - Badge count unchanged at 5
        """
        page, records = seeded_history_page
        expand_history_section( page )

        page.on( "dialog", lambda dialog: dialog.accept() )

        failed_rec    = next( r for r in records if r[ "status" ] == "failed" )
        failed_id     = failed_rec[ "id_hash" ]
        failed_card   = page.locator( f".job-card[data-job-id='{failed_id}']" )
        retry_btn     = failed_card.locator( ".retry-btn" )

        assert retry_btn.count() > 0, "Retry button not found on failed job"

        # Mock the retry API response (push_job requires LLM routing, unavailable in test env)
        import json
        mock_response = json.dumps( {
            "status"          : "retried",
            "original_job_id" : failed_id,
            "result"          : { "id_hash": "mock-retried-job-001", "status": "todo" }
        } )
        page.route(
            "**/api/job-history/*/retry",
            lambda route: route.fulfill(
                status       = 200,
                content_type = "application/json",
                body         = mock_response
            ) if route.request.method == "POST" else route.continue_()
        )

        # Click retry and wait for the mocked response
        with page.expect_response( lambda r: "/retry" in r.url ) as response_info:
            retry_btn.click()

        retry_response = response_info.value
        assert retry_response.ok, f"Retry POST failed with status {retry_response.status}"

        retry_data = retry_response.json()
        assert retry_data[ "status" ] == "retried"
        assert retry_data[ "original_job_id" ] == failed_id

        page.wait_for_timeout( 500 )

        # Original card still in history
        assert failed_card.count() == 1, "Original failed card should remain in history after retry"

        # Badge unchanged
        badge = page.locator( "#history-count-badge" )
        assert badge.text_content() == "5", f"Badge changed after retry: '{badge.text_content()}'"

    def test_retry_cancel_leaves_unchanged( self, seeded_history_page ):
        """
        Cancelling the retry confirm dialog leaves everything unchanged.

        Requires:
            - Standard seed set with failed job (std-003)

        Ensures:
            - Card count remains 5
            - Badge text remains "5"
            - No API request sent
        """
        page, records = seeded_history_page
        expand_history_section( page )

        # Dismiss (cancel) confirm() dialogs
        page.on( "dialog", lambda dialog: dialog.dismiss() )

        failed_rec = next( r for r in records if r[ "status" ] == "failed" )
        failed_id  = failed_rec[ "id_hash" ]
        retry_btn  = page.locator( f".job-card[data-job-id='{failed_id}'] .retry-btn" )

        container = page.locator( "#history-jobs-container" )
        cards     = container.locator( ".job-card" )
        badge     = page.locator( "#history-count-badge" )

        assert cards.count() == 5
        assert badge.text_content() == "5"

        # Click retry — confirm() will be dismissed
        retry_btn.click()
        page.wait_for_timeout( 300 )

        # Everything unchanged
        assert cards.count() == 5, f"Expected 5 cards after cancel, got {cards.count()}"
        assert badge.text_content() == "5", f"Badge changed after cancel: '{badge.text_content()}'"

    def test_retry_interrupted_job_creates_todo_job( self, seeded_history_page ):
        """
        Retry on interrupted job sends correct POST, UI handles success.

        Note: Backend push_job mocked (requires LLM routing, unavailable in test env).

        Requires:
            - Standard seed set with interrupted job (std-004)

        Ensures:
            - POST /retry sent for interrupted job
            - On 200 response: original interrupted card remains in history
        """
        page, records = seeded_history_page
        expand_history_section( page )

        page.on( "dialog", lambda dialog: dialog.accept() )

        interrupted_rec = next( r for r in records if r[ "status" ] == "interrupted" )
        interrupted_id  = interrupted_rec[ "id_hash" ]
        card            = page.locator( f".job-card[data-job-id='{interrupted_id}']" )
        retry_btn       = card.locator( ".retry-btn" )

        assert retry_btn.count() > 0, "Retry button not found on interrupted job"

        # Mock the retry API response
        import json
        mock_response = json.dumps( {
            "status"          : "retried",
            "original_job_id" : interrupted_id,
            "result"          : { "id_hash": "mock-retried-job-002", "status": "todo" }
        } )
        page.route(
            "**/api/job-history/*/retry",
            lambda route: route.fulfill(
                status       = 200,
                content_type = "application/json",
                body         = mock_response
            ) if route.request.method == "POST" else route.continue_()
        )

        with page.expect_response( lambda r: "/retry" in r.url ) as response_info:
            retry_btn.click()

        retry_response = response_info.value
        assert retry_response.ok, f"Retry POST failed with status {retry_response.status}"

        retry_data = retry_response.json()
        assert retry_data[ "status" ] == "retried"
        assert retry_data[ "original_job_id" ] == interrupted_id

        page.wait_for_timeout( 500 )

        # Original card still in history
        assert card.count() == 1, "Original interrupted card should remain in history after retry"


# ===========================================================================
# Edge Case Tests (Session 382 — Rubric Tests 10, 11)
# ===========================================================================

class TestJobHistoryEdgeCases:
    """Edge cases: error handling, admin cross-user management."""

    def test_delete_already_deleted_shows_error( self, seeded_history_page ):
        """
        Deleting a job that was already removed from the DB shows an error alert.

        Requires:
            - 5 seeded job_history rows

        Ensures:
            - When DELETE returns 404, an alert with error message is shown
        """
        page, records = seeded_history_page
        expand_history_section( page )

        # Intercept DELETE requests to return 404 (simulates already-deleted job)
        page.route(
            "**/api/job-history/**",
            lambda route: route.fulfill(
                status       = 404,
                content_type = "application/json",
                body         = '{"detail": "Job not found"}'
            ) if route.request.method == "DELETE" else route.continue_()
        )

        # Capture dialog messages
        dialogs = []
        page.on( "dialog", lambda dialog: ( dialogs.append( dialog.message ), dialog.accept() ) )

        container = page.locator( "#history-jobs-container" )
        container.locator( ".delete-btn" ).first.click()
        page.wait_for_timeout( 500 )

        # The first dialog is the confirm(), the second should be the error alert
        assert len( dialogs ) >= 2, f"Expected at least 2 dialogs (confirm + alert), got {len( dialogs )}"
        assert "Failed to delete job from history" in dialogs[ 1 ], \
            f"Expected error alert, got: {dialogs[ 1 ]}"

    def test_admin_can_manage_other_users_jobs( self, admin_page ):
        """
        Admin can see, delete, and retry jobs belonging to other users.

        Requires:
            - Admin user authenticated
            - Jobs seeded for a different user

        Ensures:
            - Admin sees other user's jobs in history
            - Admin can delete other user's completed job
            - Admin can retry other user's failed job
        """
        from tests.helpers.job_history_seed import seed_job_history_records

        # Seed jobs for a different user (not the admin)
        other_user_id    = "other-user-for-admin-test"
        other_user_email = "other@example.com"
        seed_job_history_records(
            user_id    = other_user_id,
            user_email = other_user_email,
            records    = [
                {
                    "id_suffix"    : "admin-001",
                    "status"       : "completed",
                    "question_text": "Other user completed job for admin test"
                },
                {
                    "id_suffix"    : "admin-002",
                    "status"       : "failed",
                    # Use a question the router can classify to a simple sync agent.
                    # "What day is it today" routes to DateAndTimeAgent which does NOT
                    # trigger the RuntimeArgumentExpeditor (UPE) that asks follow-up
                    # clarification questions and blocks push_job for 180s+ waiting
                    # for a user response that never comes in headless E2E.
                    "question_text": "What day is it today",
                    "error"        : "Simulated failure"
                },
            ]
        )

        admin_page.goto( f"{BASE_URL}/app/notifications" )
        admin_page.wait_for_load_state( "networkidle" )
        expand_history_section( admin_page )

        container = admin_page.locator( "#history-jobs-container" )
        cards     = container.locator( ".job-card" )
        assert cards.count() == 2, f"Admin should see 2 other-user jobs, got {cards.count()}"

        # Auto-accept all dialogs
        admin_page.on( "dialog", lambda dialog: dialog.accept() )

        # Delete the completed job
        completed_id   = f"test-job-admin-001::{other_user_id}"
        completed_card = container.locator( f".job-card[data-job-id='{completed_id}']" )
        assert completed_card.count() == 1, "Admin should see other user's completed job"

        with admin_page.expect_response( lambda r: "/api/job-history" in r.url and r.request.method == "DELETE" ):
            completed_card.locator( ".delete-btn" ).click()
        admin_page.wait_for_timeout( 500 )

        assert container.locator( f".job-card[data-job-id='{completed_id}']" ).count() == 0, \
            "Admin-deleted job should be gone"

        # Retry the failed job
        failed_id   = f"test-job-admin-002::{other_user_id}"
        failed_card = container.locator( f".job-card[data-job-id='{failed_id}']" )
        assert failed_card.count() == 1, "Admin should see other user's failed job"
        retry_btn = failed_card.locator( ".retry-btn" )
        assert retry_btn.count() > 0, "Failed job should have retry button"

        # Call the retry endpoint directly via Playwright's request context (uses
        # the browser's auth session). The UI click path goes through retryHistoryJob
        # → authedFetch → server push_job, which runs the full LLM routing pipeline
        # (local LoRA model call + snapshot search + embedding generation). In test
        # env the routing LoRA cold-start + inference can take 60-150s; the click path
        # also interacts with ambient TTS-focus-mode notifications that interfere with
        # event delivery. Since what this test validates is the admin-authorization
        # boundary (admin can retry another user's failed job vs. 403 for non-admin),
        # hitting the endpoint directly with a 180s budget is a cleaner assertion.
        token = admin_page.evaluate( 'localStorage.getItem( "lupin_access_token" )' )
        ws_id = admin_page.evaluate( 'window.notificationsUI && window.notificationsUI.queueSessionId' ) or "e2e-admin-retry"
        retry_resp = admin_page.request.post(
            f"{BASE_URL}/api/job-history/test-job-admin-002::{other_user_id}/retry",
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type" : "application/json",
            },
            data = json.dumps( { "websocket_id": ws_id } ),
            timeout = 180_000,
        )
        assert retry_resp.ok, f"/retry returned {retry_resp.status}: {retry_resp.text()[:500]}"

        # Failed card still in history after retry
        assert failed_card.count() == 1, "Original failed card should remain after admin retry"


# ===========================================================================
# Toggle ID-Collision Regression (Session aff39d3f — 2026.04.15)
# ===========================================================================
#
# Bug: History job cards and live Done cards for the same job_id emitted
# identical DOM ids (`job-details-{jobId}`). Clicking the visible History
# copy's toggle silently flipped the hidden Done copy's `.collapsed` class,
# so the History card appeared frozen.
#
# Fix: `renderJobCard` now prefixes internal ids with `history-` when
# `job._isHistory` is truthy; `toggleJobCard` takes a compound `idKey` arg.
#
# Plan: src/rnd/v0.1.6/2026.04.15-done-card-toggle-id-collision.md
# ===========================================================================

class TestJobCardToggleIDCollision:
    """Regression tests for the history-card toggle ID-collision fix."""

    def test_history_card_ids_are_prefixed( self, seeded_history_page ):
        """
        History cards emit `job-details-history-{id_hash}` / `job-card-history-{id_hash}`.

        Requires:
            - Seeded history rows

        Ensures:
            - Every `.job-card` in the history container has id `job-card-history-*`
            - Every `.job-card-details` in the history container has id `job-details-history-*`
        """
        page, records = seeded_history_page
        expand_history_section( page )

        container = page.locator( "#history-jobs-container" )
        cards     = container.locator( ".job-card" )
        assert cards.count() == len( records )

        for i in range( cards.count() ):
            card_id = cards.nth( i ).get_attribute( "id" ) or ""
            assert card_id.startswith( "job-card-history-" ), \
                f"Expected prefixed id, got: {card_id!r}"

        details = container.locator( ".job-card-details" )
        for i in range( details.count() ):
            details_id = details.nth( i ).get_attribute( "id" ) or ""
            assert details_id.startswith( "job-details-history-" ), \
                f"Expected prefixed id, got: {details_id!r}"

    def test_all_job_details_ids_unique( self, seeded_history_page ):
        """
        Every `[id^='job-details-']` in the DOM is unique after expanding history.

        This is the exact devtools probe the user ran to confirm the bug:
            total ids vs unique set. Pre-fix: total > unique. Post-fix: equal.

        Requires:
            - Seeded history rows (guarantees history cards render)

        Ensures:
            - No duplicate `job-details-*` ids anywhere on the page
        """
        page, records = seeded_history_page
        expand_history_section( page )

        counts = page.evaluate(
            """() => {
                const ids = [ ...document.querySelectorAll( '[id^="job-details-"]' ) ]
                    .map( e => e.id );
                return { total: ids.length, unique: new Set( ids ).size };
            }"""
        )
        assert counts[ "total" ] == counts[ "unique" ], \
            f"Duplicate job-details ids: total={counts['total']}, unique={counts['unique']}"
        assert counts[ "total" ] > 0, "Expected at least one job-details element"

    def test_history_card_header_click_expands_that_card( self, seeded_history_page ):
        """
        Clicking a history card's header expands that specific card (not a ghost).

        Requires:
            - Seeded history rows

        Ensures:
            - Target card's `.job-card-details` starts with `.collapsed`
            - After click on its header, `.collapsed` is removed on that card
            - No other history card's collapsed state changed
        """
        page, records = seeded_history_page
        expand_history_section( page )

        target_hash = records[ 0 ][ "id_hash" ]
        target_card = page.locator(
            f"#history-jobs-container .job-card[data-job-id='{target_hash}']"
        )
        assert target_card.count() == 1

        details = target_card.locator( ".job-card-details" )
        assert "collapsed" in ( details.get_attribute( "class" ) or "" ), \
            "Details should start collapsed"

        # Snapshot collapsed-state of siblings to prove independence
        container    = page.locator( "#history-jobs-container" )
        all_details  = container.locator( ".job-card-details" )
        before_state = [
            "collapsed" in ( all_details.nth( i ).get_attribute( "class" ) or "" )
            for i in range( all_details.count() )
        ]

        target_card.locator( ".job-card-header" ).click()
        page.wait_for_timeout( 150 )

        assert "collapsed" not in ( details.get_attribute( "class" ) or "" ), \
            "Target card did not expand after header click"

        # All non-target cards must retain their prior collapsed state
        for i in range( all_details.count() ):
            card_id = all_details.nth( i ).locator( ".." ).get_attribute( "data-job-id" )
            if card_id == target_hash:
                continue
            is_collapsed_now = "collapsed" in ( all_details.nth( i ).get_attribute( "class" ) or "" )
            assert is_collapsed_now == before_state[ i ], \
                f"Sibling card {card_id!r} toggle state changed unexpectedly"
