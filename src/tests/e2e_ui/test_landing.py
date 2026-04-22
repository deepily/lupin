"""
E2E UI tests for the landing page.

Phase 4: Page Smoke Tests — validates landing page greeting, feature cards,
admin section visibility, stats display, and card navigation.

Requires:
    - Dev server running on port 7999 with Testing config
    - Clean test database (via clean_test_db fixture)
"""

from .conftest import BASE_URL


# ---------------------------------------------------------------------------
# Greeting & Layout
# ---------------------------------------------------------------------------

class TestLandingLayout:
    """Tests for landing page layout and greeting."""

    def test_landing_shows_greeting( self, logged_in_page ):
        """
        Landing page displays a greeting.

        Requires:
            - Authenticated session

        Ensures:
            - Greeting element is visible and non-empty
        """
        # Ensure user_data is in localStorage before navigating
        logged_in_page.wait_for_function(
            'localStorage.getItem( "user_data" ) !== null',
            timeout=5000
        )

        logged_in_page.goto( f"{BASE_URL}/app" )
        logged_in_page.wait_for_load_state( "networkidle" )

        greeting = logged_in_page.get_by_test_id( "landing-greeting" )
        greeting.wait_for( state="visible", timeout=5000 )

        assert greeting.text_content().strip() != ""

    def test_landing_shows_stats( self, logged_in_page ):
        """
        Landing page displays stats section.

        Requires:
            - Authenticated session

        Ensures:
            - Time saved and replays stats elements are present
        """
        logged_in_page.goto( f"{BASE_URL}/app" )
        logged_in_page.wait_for_load_state( "networkidle" )

        time_saved = logged_in_page.get_by_test_id( "landing-stat-time-saved" )
        replays    = logged_in_page.get_by_test_id( "landing-stat-replays" )

        assert time_saved.count() > 0, "Time saved stat not found"
        assert replays.count() > 0, "Replays stat not found"


# ---------------------------------------------------------------------------
# Feature Cards
# ---------------------------------------------------------------------------

class TestLandingCards:
    """Tests for landing page feature cards."""

    def test_notifications_card_visible( self, logged_in_page ):
        """
        Notifications card is visible on landing page.

        Requires:
            - Authenticated session

        Ensures:
            - Notifications card is visible
        """
        logged_in_page.goto( f"{BASE_URL}/app" )
        logged_in_page.wait_for_load_state( "networkidle" )

        card = logged_in_page.get_by_test_id( "landing-card-notifications" )
        card.wait_for( state="visible", timeout=5000 )

    def test_profile_card_visible( self, logged_in_page ):
        """
        Profile card is visible on landing page.

        Requires:
            - Authenticated session

        Ensures:
            - Profile card is visible
        """
        logged_in_page.goto( f"{BASE_URL}/app" )
        logged_in_page.wait_for_load_state( "networkidle" )

        card = logged_in_page.get_by_test_id( "landing-card-profile" )
        card.wait_for( state="visible", timeout=5000 )

    def test_notifications_card_navigates( self, logged_in_page ):
        """
        Clicking notifications card navigates to notifications page.

        Requires:
            - Authenticated session

        Ensures:
            - Card click navigates to /app/notifications
        """
        logged_in_page.goto( f"{BASE_URL}/app" )
        logged_in_page.wait_for_load_state( "networkidle" )

        card = logged_in_page.get_by_test_id( "landing-card-notifications" )
        card.wait_for( state="visible", timeout=5000 )
        card.click()

        logged_in_page.wait_for_url( "**/notifications**", timeout=5000 )
        assert "/notifications" in logged_in_page.url

    def test_profile_card_navigates( self, logged_in_page ):
        """
        Clicking profile card navigates to profile page.

        Requires:
            - Authenticated session

        Ensures:
            - Card click navigates to /app/auth/profile
        """
        logged_in_page.goto( f"{BASE_URL}/app" )
        logged_in_page.wait_for_load_state( "networkidle" )

        card = logged_in_page.get_by_test_id( "landing-card-profile" )
        card.wait_for( state="visible", timeout=5000 )
        card.click()

        logged_in_page.wait_for_url( "**/profile**", timeout=5000 )
        assert "/profile" in logged_in_page.url


# ---------------------------------------------------------------------------
# Admin Section
# ---------------------------------------------------------------------------

class TestLandingAdminSection:
    """Tests for admin-only section on landing page."""

    def test_regular_user_no_admin_section( self, logged_in_page ):
        """
        Regular user does not see admin section on landing page.

        Requires:
            - Authenticated as regular user

        Ensures:
            - Admin section is not visible
        """
        logged_in_page.goto( f"{BASE_URL}/app" )
        logged_in_page.wait_for_load_state( "networkidle" )
        logged_in_page.wait_for_timeout( 1000 )

        admin_section = logged_in_page.get_by_test_id( "landing-admin-section" )
        assert not admin_section.is_visible()

    def test_admin_user_sees_admin_section( self, admin_page ):
        """
        Admin user sees admin section with management cards.

        Requires:
            - Admin-authenticated session

        Ensures:
            - Admin section is visible
            - Admin cards are present
        """
        admin_page.goto( f"{BASE_URL}/app" )
        admin_page.wait_for_load_state( "networkidle" )

        admin_section = admin_page.get_by_test_id( "landing-admin-section" )
        admin_section.wait_for( state="visible", timeout=5000 )

        # Check admin cards
        assert admin_page.get_by_test_id( "landing-card-users" ).is_visible()
        assert admin_page.get_by_test_id( "landing-card-snapshots" ).is_visible()

    def test_admin_card_navigates_to_users( self, admin_page ):
        """
        Clicking users admin card navigates to user management.

        Requires:
            - Admin-authenticated session

        Ensures:
            - Card click navigates to /app/admin/users
        """
        admin_page.goto( f"{BASE_URL}/app" )
        admin_page.wait_for_load_state( "networkidle" )

        card = admin_page.get_by_test_id( "landing-card-users" )
        card.wait_for( state="visible", timeout=5000 )
        card.click()

        admin_page.wait_for_url( "**/users**", timeout=5000 )
        assert "/users" in admin_page.url
