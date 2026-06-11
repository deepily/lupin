"""
E2E UI tests for the doc viewer's directory listing extension.

Validates that `/app/docs?path=<project>/<directory>` renders a clickable
directory listing (per src/rnd/v0.1.7/2026.05.12-doc-viewer-directory-listing.md).
URL format is the post-2026-05-15 unified path-prefix scheme: `?path=lupin/<rel>`
for Lupin docs, `?path=io` for the io built-in scope. The legacy `?scope=` query
param is retired (see § Doc Viewer Scope in CLAUDE.md).

Auth note (updated 2026-05-12): the doc viewer's `/api/docs/file` and
`/api/io/file` endpoints now require JWT auth per multi-repo-doc-viewer.md
§3f, so all tests in this file use the `logged_in_page` fixture.

Venue: :8000 (scheduled monopolize-mode via /api/test-suite/submit).

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
    """Browser-rendered directory listing tests for the lupin docs subtree and the io built-in scope."""

    def test_docs_scope_directory_renders_listing( self, logged_in_page ):
        """Navigating to a whitelisted R&D directory renders the directory listing."""
        logged_in_page.goto( f"{BASE_URL}/app/docs?path=lupin/src/rnd/v0.1.7" )
        logged_in_page.wait_for_load_state( "networkidle" )

        # The .doc-dir-listing UL is the canonical directory-mode marker
        listing = logged_in_page.locator( ".doc-dir-listing" )
        assert listing.count() == 1, "expected exactly one .doc-dir-listing element"

        # Breadcrumb is rendered
        breadcrumb = logged_in_page.locator( ".doc-dir-breadcrumb" )
        assert breadcrumb.count() == 1
        # Breadcrumb should contain at least one anchor and the final segment as .current
        assert breadcrumb.locator( "a" ).count() >= 1
        assert breadcrumb.locator( ".current" ).count() == 1

        # At least one entry is present
        entries = logged_in_page.locator( ".doc-dir-entry" )
        assert entries.count() > 0, "directory listing has no entries"

    def test_docs_scope_entry_links_back_to_doc_viewer( self, logged_in_page ):
        """Each entry's <a href> points back into the doc viewer at the deeper path."""
        logged_in_page.goto( f"{BASE_URL}/app/docs?path=lupin/src/rnd/v0.1.7" )
        logged_in_page.wait_for_load_state( "networkidle" )

        first_entry_link = logged_in_page.locator( ".doc-dir-entry a" ).first
        href = first_entry_link.get_attribute( "href" )
        assert href, "first entry has no href"
        assert href.startswith( "/app/docs?path=" )
        # Post-unification (2026-05-15): hrefs are project-prefixed path-only —
        # no retired ?scope= param. Entry stays inside the lupin scope.
        assert "path=lupin" in href, f"entry href should carry the lupin path-prefix; got {href!r}"

    def test_docs_scope_bare_prefix_root_renders( self, logged_in_page ):
        """Q2: bare `src/rnd` (no trailing slash) renders a listing."""
        logged_in_page.goto( f"{BASE_URL}/app/docs?path=lupin/src/rnd" )
        logged_in_page.wait_for_load_state( "networkidle" )
        assert logged_in_page.locator( ".doc-dir-listing" ).count() == 1

    def test_io_scope_directory_renders_listing( self, logged_in_page ):
        """Navigating to the io root renders a listing with io path-prefix URLs."""
        logged_in_page.goto( f"{BASE_URL}/app/docs?path=io" )
        logged_in_page.wait_for_load_state( "networkidle" )

        listing = logged_in_page.locator( ".doc-dir-listing" )
        assert listing.count() == 1, "expected exactly one .doc-dir-listing element"

        # At least one entry exists
        assert logged_in_page.locator( ".doc-dir-entry" ).count() > 0

    def test_io_scope_mp3_entry_links_to_audio_player( self, logged_in_page ):
        """Q1: mp3 entries in the io scope route to /app/audio (NOT /api/io/file?download)."""
        logged_in_page.goto( f"{BASE_URL}/app/docs?path=io" )
        logged_in_page.wait_for_load_state( "networkidle" )

        # Find any anchor href that points at the audio player — proves an mp3 routed correctly
        audio_links = logged_in_page.locator( '.doc-dir-entry a[href^="/app/audio?path="]' )
        if audio_links.count() == 0:
            # If io root has no mp3s in this environment, the test is informational, not a hard fail
            import pytest
            pytest.skip( "no mp3 files at io root in this test environment" )
        else:
            assert audio_links.count() >= 1

    def test_docs_scope_file_regression_still_renders_markdown( self, logged_in_page ):
        """File-mode (existing behavior) still works — no Content-Type regression."""
        logged_in_page.goto(
            f"{BASE_URL}/app/docs"
            f"?path=lupin/src/rnd/v0.1.7/2026.04.24-cosa-voice-nested-repo-detection-fix.md"
        )
        logged_in_page.wait_for_load_state( "networkidle" )

        # File mode → markdown rendered → no .doc-dir-listing; .doc-viewer-content present
        assert logged_in_page.locator( ".doc-dir-listing" ).count() == 0
        assert logged_in_page.locator( ".doc-viewer-content" ).count() == 1


class TestDocViewerDirectoryVisual:
    """Visual regression snapshots for the directory-listing UI."""

    def test_visual_docs_scope_listing( self, logged_in_page, assert_snapshot ):
        """Visual regression for the lupin docs directory listing."""
        logged_in_page.goto( f"{BASE_URL}/app/docs?path=lupin/src/rnd/v0.1.7" )
        logged_in_page.wait_for_load_state( "networkidle" )
        # Snapshot the listing container (not the whole page — keeps snapshot
        # stable across nav bar / header chrome changes)
        listing_container = logged_in_page.locator( ".doc-viewer-container" )
        assert_snapshot( listing_container, name="doc_viewer_directory_listing_docs.png" )

    # Frozen fixture served via the lupin scope (its .docview.yml whitelists src/).
    _FIXTURE_PATH = "lupin/src/tests/e2e_ui/fixtures/docview_listing_fixture_io"

    def test_visual_directory_listing_frozen_fixture( self, logged_in_page, assert_snapshot ):
        """Visual regression for the directory-listing chrome via a FROZEN fixture.

        ts-127620e1 fix: replaces the former `?path=io` snapshot, which was
        unstable-by-construction — the io scope grows every run (the harness writes
        its own results into io/), so the listing height changed between baseline
        capture and run (ValueError: Image sizes do not match). The renderer is
        scope-agnostic; the frozen fixture exercises the same chrome. Functional
        coverage of the real io scope stays in TestDocViewerDirectoryListing above.
        """
        logged_in_page.goto( f"{BASE_URL}/app/docs?path={self._FIXTURE_PATH}" )
        logged_in_page.wait_for_load_state( "networkidle" )
        listing_container = logged_in_page.locator( ".doc-viewer-container" )
        assert_snapshot( listing_container, name="doc_viewer_directory_listing_frozen.png" )
