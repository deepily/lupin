"""
Trivial verification test for Playwright E2E UI infrastructure.

Phase 1 sanity check: confirms Playwright can launch a browser,
navigate to the login page, and assert basic page properties.

This test validates:
- Playwright is installed and configured correctly
- Browser can connect to the dev server
- Login page renders with expected title
- pytest-playwright fixtures work (page, browser)
"""

from .conftest import BASE_URL


def test_login_page_loads( page ):
    """
    Navigate to the login page and verify it renders.

    Requires:
        - Dev server running on port 7999
        - Server hot-swapped to Testing config

    Ensures:
        - Login page loads without errors
        - Page title contains 'Lupin' or 'Login'
        - Login form heading is visible
    """
    page.goto( f"{BASE_URL}/app/auth/login" )

    # Verify page loaded — check title
    title = page.title()
    assert "lupin" in title.lower() or "login" in title.lower(), \
        f"Unexpected page title: {title}"

    # Verify login form is present — use the h1 heading
    heading = page.locator( "h1" ).first
    heading.wait_for( state="visible", timeout=5000 )
    heading_text = heading.text_content()
    assert "lupin" in heading_text.lower(), f"Unexpected heading: {heading_text}"

    print( f"✓ Login page loaded — title: '{title}', heading: '{heading_text}'" )
