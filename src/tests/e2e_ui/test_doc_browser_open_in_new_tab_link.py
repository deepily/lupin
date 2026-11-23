"""
E2E UI: the doc file browser's ↗ "open in a new tab" link, in both clients.

A folder listing shows a ↗ link beside every viewable file and beside no folder.
Clicking the file name still renders the file in the Reading Pane.
Clicking the ↗ opens the same document in a new browser tab.
That tab's URL is the one the pane's "push into another tab" button opens, and the pane is left as it was.

The listing is one page, `document-viewer.html`, shown in the pane's iframe by the multiplexer and by the
classic notifications page. Each client intercepts clicks on `/app/docs?path=` links inside that iframe.
So the pane tests, one per client, are what prove the ↗ link escapes that interception.
The standalone test proves the markup: the glyph, the attributes and the keyboard reach.

Venue: :8000, scheduled. Read-only: nothing is seeded.
It lives in half B, so the suite is `e2e_b`. Select it with `-k doc_browser_open_in_new_tab`.
"""

from urllib.parse import quote

from .conftest import BASE_URL

FOLDER      = "lupin/src/rnd/v0.1.7"
FOLDER_HREF = f"/app/docs?path={quote( FOLDER, safe='' )}"
TIMEOUT_MS  = 20_000


def _open_listing_in_pane_multiplexer( page ):
    page.goto( f"{BASE_URL}/app/multiplexer" )
    page.wait_for_load_state( "networkidle" )
    page.wait_for_function(
        "() => window.__multiplexerTestHook && window.__multiplexerTestHook.stores"
        " && window.__multiplexerTestHook.stores.readingPane",
        timeout=15000,
    )
    page.locator( "#layout-mode-toggle" ).click()   # → horizontal, where the pane is
    page.evaluate( "( href ) => window.__multiplexerTestHook.stores.readingPane.open( 'doc', href, 'Folder' )", FOLDER_HREF )


def _open_listing_in_pane_legacy( page ):
    page.goto( f"{BASE_URL}/app/notifications?classic=1" )
    page.wait_for_load_state( "networkidle" )
    if page.evaluate( "() => document.body.getAttribute( 'data-layout-mode' )" ) != "horizontal":
        page.locator( "#layout-mode-toggle" ).click()
    page.evaluate(
        """( href ) => {
            const a = document.createElement( 'a' );
            a.setAttribute( 'href', href );
            a.textContent = 'Folder';
            a.dataset.testFolder = '1';
            document.body.appendChild( a );
        }""",
        FOLDER_HREF,
    )
    page.locator( "a[data-test-folder='1']" ).click()


def _pane_frame_src( page ):
    return page.evaluate( "() => document.querySelector( '#content-pane-body iframe' ).getAttribute( 'src' )" )


def _listing( frame ):
    frame.locator( ".doc-dir-listing" ).wait_for( timeout=TIMEOUT_MS )
    frame.locator( ".doc-dir-entry" ).first.wait_for( timeout=TIMEOUT_MS )
    return frame


def _prove_glyph_behaviour( page, context ):
    frame = _listing( page.frame_locator( "#content-pane-body iframe" ) )
    entries = frame.locator( ".doc-dir-entry" )
    files   = [ e for e in range( entries.count() ) if entries.nth( e ).locator( ".doc-dir-icon" ).inner_text() != "📁" ]
    assert files, f"{FOLDER} must list at least one file for this test to mean anything"

    # ↗ beside every file, beside no folder.
    for i in range( entries.count() ):
        glyphs = entries.nth( i ).locator( "a.doc-dir-newtab" ).count()
        assert glyphs == ( 1 if i in files else 0 ), f"entry {i}: expected {1 if i in files else 0} glyph, got {glyphs}"

    entry = entries.nth( files[ 0 ] )
    name  = entry.locator( ".doc-dir-name" ).inner_text()
    name_href = entry.locator( "a" ).first.get_attribute( "href" )
    glyph = entry.locator( "a.doc-dir-newtab" )
    assert glyph.get_attribute( "aria-label" ) == f"Open {name} in a new tab"
    assert glyph.get_attribute( "title" ) == f"Open {name} in a new tab"
    assert glyph.get_attribute( "target" ) == "_blank"
    assert glyph.get_attribute( "rel" ) == "noopener"
    assert glyph.get_attribute( "href" ) == name_href, "↗ must open the document the name link renders"

    # Keyboard reach: the glyph is a real link, so Tab lands on it after the name link.
    entry.locator( "a" ).first.focus()
    page.keyboard.press( "Tab" )
    assert frame.locator( "a.doc-dir-newtab:focus" ).count() == 1, "Tab from the name link must reach the ↗ link"

    # ↗ opens a new tab at the file's URL and leaves the pane showing the folder.
    pane_before = _pane_frame_src( page )
    with context.expect_page() as popup:
        glyph.click()
    new_tab = popup.value
    new_tab.wait_for_load_state()
    assert new_tab.url.endswith( name_href ), f"new tab opened {new_tab.url!r}, expected …{name_href!r}"
    new_tab.close()
    assert _pane_frame_src( page ) == pane_before, "the ↗ click must not touch the Reading Pane"

    # The name still renders the file in the pane, in no new tab.
    pages_before = len( context.pages )
    entry.locator( "a" ).first.click()
    page.wait_for_function(
        "( was ) => document.querySelector( '#content-pane-body iframe' ).getAttribute( 'src' ) !== was",
        arg=pane_before, timeout=TIMEOUT_MS,
    )
    assert _pane_frame_src( page ) == name_href
    assert len( context.pages ) == pages_before, "the name link must not open a tab"


class TestDocBrowserOpenInNewTabLink:
    """The ↗ link in the folder listing, standalone and in each client's Reading Pane."""

    def test_standalone_listing_has_glyph_on_files_only( self, logged_in_page ):
        page = logged_in_page
        page.goto( f"{BASE_URL}{FOLDER_HREF}" )
        page.wait_for_load_state( "networkidle" )
        _listing( page )
        entries = page.locator( ".doc-dir-entry" )
        assert page.locator( "a.doc-dir-newtab" ).count() == sum(
            1 for i in range( entries.count() ) if entries.nth( i ).locator( ".doc-dir-icon" ).inner_text() != "📁"
        )
        glyph = page.locator( "a.doc-dir-newtab" ).first
        assert glyph.inner_text() == "↗"
        assert glyph.get_attribute( "target" ) == "_blank"

    def test_multiplexer_pane_glyph_opens_a_tab_and_name_renders_in_pane( self, logged_in_page ):
        _open_listing_in_pane_multiplexer( logged_in_page )
        _prove_glyph_behaviour( logged_in_page, logged_in_page.context )

    def test_legacy_pane_glyph_opens_a_tab_and_name_renders_in_pane( self, logged_in_page ):
        _open_listing_in_pane_legacy( logged_in_page )
        _prove_glyph_behaviour( logged_in_page, logged_in_page.context )
