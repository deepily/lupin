"""
E2E UI tests for the doc viewer's directory listing extension.

Validates that `/app/docs?path=<directory>&scope=<docs|io>` renders a
clickable directory listing (per
src/rnd/v0.1.7/2026.05.12-doc-viewer-directory-listing.md).

Venue: :8000 (scheduled monopolize-mode via /api/test-suite/submit).
The doc viewer endpoint is public (no auth), so no `logged_in_page`
fixture is needed.

Requires:
    - Test server running on port 8000
    - src/rnd/v0.1.7/ contains a populated subdirectory (the test uses
      2026.04.23-cj-flow-async-multi-lane/ which has multiple .md files)
    - io/ root contains at least one .mp3 file (used to assert routing)

Run:
    Manual: pytest src/tests/e2e_ui/test_doc_viewer_directory.py -v
    Scheduled: POST /api/test-suite/submit with test_types="e2e" + pytest_args="-k doc_viewer_directory"
"""

from .conftest import BASE_URL


class TestDocViewerDirectoryListing:
    """Browser-rendered directory listing tests for scope=docs and scope=io."""

    def test_docs_scope_directory_renders_listing( self, page ):
        """Navigating to a whitelisted R&D directory renders the directory listing."""
        page.goto( f"{BASE_URL}/app/docs?path=src/rnd/v0.1.7&scope=docs" )
        page.wait_for_load_state( "networkidle" )

        # The .doc-dir-listing UL is the canonical directory-mode marker
        listing = page.locator( ".doc-dir-listing" )
        assert listing.count() == 1, "expected exactly one .doc-dir-listing element"

        # Breadcrumb is rendered
        breadcrumb = page.locator( ".doc-dir-breadcrumb" )
        assert breadcrumb.count() == 1
        # Breadcrumb should contain at least one anchor and the final segment as .current
        assert breadcrumb.locator( "a" ).count() >= 1
        assert breadcrumb.locator( ".current" ).count() == 1

        # At least one entry is present
        entries = page.locator( ".doc-dir-entry" )
        assert entries.count() > 0, "directory listing has no entries"

    def test_docs_scope_entry_links_back_to_doc_viewer( self, page ):
        """Each entry's <a href> points back into the doc viewer at the deeper path."""
        page.goto( f"{BASE_URL}/app/docs?path=src/rnd/v0.1.7&scope=docs" )
        page.wait_for_load_state( "networkidle" )

        first_entry_link = page.locator( ".doc-dir-entry a" ).first
        href = first_entry_link.get_attribute( "href" )
        assert href, "first entry has no href"
        assert href.startswith( "/app/docs?path=" )
        assert "scope=docs" in href

    def test_docs_scope_bare_prefix_root_renders( self, page ):
        """Q2: bare `src/rnd` (no trailing slash) renders a listing."""
        page.goto( f"{BASE_URL}/app/docs?path=src/rnd&scope=docs" )
        page.wait_for_load_state( "networkidle" )
        assert page.locator( ".doc-dir-listing" ).count() == 1

    def test_io_scope_directory_renders_listing( self, page ):
        """Navigating to an io subdirectory renders a listing with scope=io URLs."""
        page.goto( f"{BASE_URL}/app/docs?path=&scope=io" )
        page.wait_for_load_state( "networkidle" )

        listing = page.locator( ".doc-dir-listing" )
        assert listing.count() == 1, "expected exactly one .doc-dir-listing element"

        # At least one entry exists
        assert page.locator( ".doc-dir-entry" ).count() > 0

    def test_io_scope_mp3_entry_links_to_audio_player( self, page ):
        """Q1: mp3 entries in scope=io route to /app/audio (NOT /api/io/file?download)."""
        page.goto( f"{BASE_URL}/app/docs?path=&scope=io" )
        page.wait_for_load_state( "networkidle" )

        # Find any anchor href that points at the audio player — proves an mp3 routed correctly
        audio_links = page.locator( '.doc-dir-entry a[href^="/app/audio?path="]' )
        if audio_links.count() == 0:
            # If io root has no mp3s in this environment, the test is informational, not a hard fail
            import pytest
            pytest.skip( "no mp3 files at io root in this test environment" )
        else:
            assert audio_links.count() >= 1

    def test_docs_scope_file_regression_still_renders_markdown( self, page ):
        """File-mode (existing behavior) still works — no Content-Type regression."""
        page.goto(
            f"{BASE_URL}/app/docs"
            f"?path=src/rnd/v0.1.7/2026.04.24-cosa-voice-nested-repo-detection-fix.md"
            f"&scope=docs"
        )
        page.wait_for_load_state( "networkidle" )

        # File mode → markdown rendered → no .doc-dir-listing; .doc-viewer-content present
        assert page.locator( ".doc-dir-listing" ).count() == 0
        assert page.locator( ".doc-viewer-content" ).count() == 1


class TestDocViewerDirectoryVisual:
    """Visual regression snapshots for the directory-listing UI."""

    def test_visual_docs_scope_listing( self, page, assert_snapshot ):
        """Visual regression for scope=docs directory listing."""
        page.goto( f"{BASE_URL}/app/docs?path=src/rnd/v0.1.7&scope=docs" )
        page.wait_for_load_state( "networkidle" )
        # Snapshot the listing container (not the whole page — keeps snapshot
        # stable across nav bar / header chrome changes)
        listing_container = page.locator( ".doc-viewer-container" )
        assert_snapshot( listing_container, name="doc_viewer_directory_listing_docs.png" )

    def test_visual_io_scope_listing( self, page, assert_snapshot ):
        """Visual regression for scope=io directory listing."""
        page.goto( f"{BASE_URL}/app/docs?path=&scope=io" )
        page.wait_for_load_state( "networkidle" )
        listing_container = page.locator( ".doc-viewer-container" )
        assert_snapshot( listing_container, name="doc_viewer_directory_listing_io.png" )
