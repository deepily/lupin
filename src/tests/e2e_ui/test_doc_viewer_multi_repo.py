"""
E2E UI tests for the multi-repo doc viewer's external-scope handling.

Validates that `/app/docs?path=...&scope=<external>` browses files in
externally-mounted repos (claude-plans, lupin, planning-is-prompting, etc.)
beyond the legacy `docs` / `io` built-ins.

Auth note: /api/docs/file is JWT-gated; an unauthenticated visit must
redirect to `/app/login?next=<original-url>`.

Venue: :8000 (scheduled monopolize-mode via /api/test-suite/submit).

Design doc: src/rnd/v0.1.7/2026.05.12-multi-repo-doc-viewer.md §5 (E2E)

Run:
    Manual: pytest src/tests/e2e_ui/test_doc_viewer_multi_repo.py -v
    Scheduled: POST /api/test-suite/submit with test_types="e2e" + pytest_args="-k doc_viewer_multi_repo"
"""

from .conftest import BASE_URL


class TestExternalScopeRendering:
    """Each registered external scope renders a clickable listing."""

    def test_claude_plans_root_lists_plans( self, logged_in_page ):
        """Browse ?scope=claude-plans → directory listing with multiple plan files."""
        logged_in_page.goto( f"{BASE_URL}/app/docs?path=&scope=claude-plans" )
        logged_in_page.wait_for_load_state( "networkidle" )

        listing = logged_in_page.locator( ".doc-dir-listing" )
        assert listing.count() == 1, "expected one .doc-dir-listing"

        entries = logged_in_page.locator( ".doc-dir-entry" )
        # claude-plans directory has dozens of .md plan files in production,
        # but tests use whatever's mounted — assert ≥1 to confirm the scope works.
        assert entries.count() >= 1, "claude-plans listing was empty"

    def test_lupin_scope_lists_src_subtree( self, logged_in_page ):
        """Browse ?scope=lupin&path=src/rnd → listing renders inside lupin scope."""
        logged_in_page.goto( f"{BASE_URL}/app/docs?path=src/rnd&scope=lupin" )
        logged_in_page.wait_for_load_state( "networkidle" )
        assert logged_in_page.locator( ".doc-dir-listing" ).count() == 1
        assert logged_in_page.locator( ".doc-dir-entry" ).count() >= 1

    def test_external_scope_entry_href_carries_scope( self, logged_in_page ):
        """Each entry's href preserves &scope=<external> so navigation stays in-scope."""
        logged_in_page.goto( f"{BASE_URL}/app/docs?path=&scope=claude-plans" )
        logged_in_page.wait_for_load_state( "networkidle" )

        first_entry = logged_in_page.locator( ".doc-dir-entry a" ).first
        href = first_entry.get_attribute( "href" )
        assert href is not None, "first entry has no href"
        # Either an in-viewer link (for .md files) or a same-scope dir navigation
        assert "scope=claude-plans" in href, f"href lost scope: {href!r}"


class TestExternalScopeFileRendering:
    """Clicking a file in an external scope renders its content."""

    def test_external_markdown_file_renders( self, logged_in_page ):
        """An .md file in claude-plans renders as markdown content."""
        # Navigate to listing first to find a real file (avoids hardcoding a filename)
        logged_in_page.goto( f"{BASE_URL}/app/docs?path=&scope=claude-plans" )
        logged_in_page.wait_for_load_state( "networkidle" )

        md_entry = logged_in_page.locator(
            '.doc-dir-entry a[href*="scope=claude-plans"]'
        ).first
        if md_entry.count() == 0:
            import pytest
            pytest.skip( "no entries in claude-plans listing" )

        href = md_entry.get_attribute( "href" )
        logged_in_page.goto( f"{BASE_URL}{href}" )
        logged_in_page.wait_for_load_state( "networkidle" )

        # File mode → no directory listing; .doc-viewer-content rendered
        assert logged_in_page.locator( ".doc-dir-listing" ).count() == 0
        assert logged_in_page.locator( ".doc-viewer-content" ).count() == 1

    def test_external_python_file_renders_as_pre( self, logged_in_page ):
        """A .py file in the lupin scope renders as plain <pre> (Phase 2.5 deferred syntax highlighting)."""
        logged_in_page.goto(
            f"{BASE_URL}/app/docs"
            f"?path=src/cosa/rest/routers/_scope_registry.py"
            f"&scope=lupin"
        )
        logged_in_page.wait_for_load_state( "networkidle" )

        # Plain-text renderer uses <pre class="doc-code-content">
        assert logged_in_page.locator( "pre.doc-code-content" ).count() == 1
        # Content includes module-level identifier
        pre = logged_in_page.locator( "pre.doc-code-content" )
        text = pre.inner_text()
        assert "ScopeConfig" in text, "expected ScopeConfig in rendered Python source"


class TestAuthGateRedirect:
    """Unauthenticated visits get redirected to /app/login?next=..."""

    def test_no_auth_redirects_to_login( self, page ):
        """Visiting /app/docs with no auth token in localStorage → redirected to login."""
        # Ensure no token in localStorage before the visit
        page.goto( f"{BASE_URL}/app/login" )
        page.evaluate( 'localStorage.removeItem( "lupin_access_token" )' )

        target = f"{BASE_URL}/app/docs?path=&scope=claude-plans"
        page.goto( target )
        page.wait_for_load_state( "networkidle" )

        # The viewer JS sees 401 and redirects to /app/login?next=<encoded-original>
        current = page.url
        assert "/app/login" in current, f"expected login redirect, got {current}"
        # The `next=` query carries the original URL
        assert "next=" in current, f"login URL missing next= param: {current}"


class TestExternalScopeVisual:
    """Visual regression for the new external-scope listing chrome."""

    def test_visual_claude_plans_listing( self, logged_in_page, assert_snapshot ):
        """Snapshot the claude-plans listing for visual regression."""
        logged_in_page.goto( f"{BASE_URL}/app/docs?path=&scope=claude-plans" )
        logged_in_page.wait_for_load_state( "networkidle" )
        listing_container = logged_in_page.locator( ".doc-viewer-container" )
        assert_snapshot(
            listing_container,
            name = "doc_viewer_multi_repo_claude_plans_listing.png",
        )
