"""
E2E UI visual regression tests for all Lupin pages.

Phase 8: Visual Regression — parametrized screenshot comparison for all 12 pages.
Uses pytest-playwright-visual-snapshot to capture and compare baseline screenshots.

Dynamic elements (clocks, session IDs, WS status indicators) are masked globally
via pytest.ini playwright_visual_snapshot_masks configuration.

Requires:
    - Dev server running on port 7999 with Testing config
    - Clean test database (via clean_test_db fixture)
    - Baseline snapshots in src/tests/e2e_ui/__snapshots__/
      (auto-created on first run, update with --update-snapshots)
"""

import pytest

from .conftest import (
    BASE_URL, PAGE_URLS,
    PUBLIC_PAGES, AUTH_PAGES, ADMIN_PAGES, HYBRID_PAGES,
    fill_login_form, fill_register_form,
)


# ---------------------------------------------------------------------------
# Dynamic Content Normalization
# ---------------------------------------------------------------------------

# JavaScript to replace dynamic text content with stable placeholders.
# This is more reliable than Playwright mask overlays, which can produce
# subpixel rendering differences between runs (mask box size follows
# element dimensions, and dynamic text like UUIDs change width).
NORMALIZE_DYNAMIC_CONTENT_JS = """
() => {
    const replacements = [
        { sel: '[data-testid="profile-user-id"]', text: '00000000-0000-0000-0000-000000000000' },
        { sel: '[data-testid="session-id"]',      text: 'stable-session' },
        { sel: '[data-testid="current-time"]',     text: '12:00:00' },
        { sel: '#clock-display',                   text: '12:00' },
        { sel: '#time-display',                    text: '12:00' },
        { sel: '#queue-ws-status',                 text: 'Connected' },
        { sel: '#audio-ws-status',                 text: 'Connected' },
        { sel: '#auth-status',                     text: 'Authenticated' },
    ];
    for ( const { sel, text } of replacements ) {
        const el = document.querySelector( sel );
        if ( el ) el.textContent = text;
    }
    // Admin users table: Created (td:nth-child(6)) and Last Login (td:nth-child(7))
    // columns render via formatDate() which returns relative times ("Just now",
    // "3 hours ago") that drift every test run. Normalize both columns so the
    // visual snapshot is stable across runs regardless of when users were seeded
    // or when the admin test fixture logged in.
    const rows = document.querySelectorAll( '#users-tbody tr' );
    rows.forEach( ( row ) => {
        const tds = row.children;
        if ( tds.length >= 7 ) {
            tds[ 5 ].textContent = '1/1/2026';  // Created column
            tds[ 6 ].textContent = 'Never';     // Last Login column
        }
    } );
}
"""


# ---------------------------------------------------------------------------
# Page Definitions for Parametrization
# ---------------------------------------------------------------------------

# Each entry: ( page_name, fixture_type )
# fixture_type determines which auth fixture to use:
#   "public"  — no auth (raw page fixture)
#   "auth"    — logged_in_page fixture
#   "admin"   — admin_page fixture

VISUAL_PAGES = (
    [ ( name, "public" ) for name in PUBLIC_PAGES ] +
    [ ( name, "auth" )   for name in AUTH_PAGES + HYBRID_PAGES ] +
    [ ( name, "admin" )  for name in ADMIN_PAGES ]
)


# ---------------------------------------------------------------------------
# Visual Regression Tests
# ---------------------------------------------------------------------------

class TestVisualRegression:
    """Full-page screenshot comparison for all Lupin pages."""

    @pytest.mark.parametrize(
        "page_name,fixture_type",
        VISUAL_PAGES,
        ids=[ name for name, _ in VISUAL_PAGES ],
    )
    def test_visual_page( self, request, clean_test_db, assert_snapshot, page_name, fixture_type ):
        """
        Capture full-page screenshot and compare against baseline.

        Requires:
            - page_name is a valid key in PAGE_URLS
            - fixture_type is one of: public, auth, admin
            - assert_snapshot fixture from pytest-playwright-visual-snapshot

        Ensures:
            - Page loads successfully (200 status)
            - Screenshot matches baseline within configured threshold
            - Dynamic elements are masked (clocks, session IDs, WS status)
        """
        # Get the appropriate page fixture based on auth requirements
        if fixture_type == "admin":
            browser_page = request.getfixturevalue( "admin_page" )
        elif fixture_type == "auth":
            browser_page = request.getfixturevalue( "logged_in_page" )
        else:
            browser_page = request.getfixturevalue( "page" )

        url      = f"{BASE_URL}{PAGE_URLS[ page_name ]}"
        response = browser_page.goto( url )
        browser_page.wait_for_load_state( "networkidle" )

        assert response.status == 200, f"{page_name}: HTTP {response.status}"

        # Normalize dynamic content (UUIDs, timestamps, WS status) to stable
        # placeholders before screenshotting. More reliable than Playwright mask
        # overlays which produce subpixel rendering differences between runs.
        browser_page.evaluate( NORMALIZE_DYNAMIC_CONTENT_JS )

        # fonts.ready + 2 RAFs so any NotoColorEmoji glyphs (persona/status icons
        # on the notifications/multiplexer/etc. full-page captures) are loaded
        # before the pixel snapshot — the emoji font-race the Gate D fix closed
        # (3c7e0aab / task_editing.py). No-op on the non-emoji pages.
        browser_page.evaluate( "() => document.fonts.ready" )
        browser_page.evaluate( "() => new Promise( resolve => requestAnimationFrame( () => requestAnimationFrame( resolve ) ) )" )

        # Take screenshot and compare against baseline.
        # The name parameter creates human-readable snapshot filenames.
        assert_snapshot(
            browser_page,
            name=f"{page_name}.png",
        )

        print( f"✓ {page_name}: visual snapshot compared" )
