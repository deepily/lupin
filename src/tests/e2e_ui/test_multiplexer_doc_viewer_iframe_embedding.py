"""
E2E UI smoke — multiplexer doc-viewer iframe embedding (Lane C WP4, 2026-06-10).

Complements the server-header smoke `test_doc_viewer_iframe_embedding.py`
(which proves `/app/docs` serves `X-Frame-Options: SAMEORIGIN`) with the
multiplexer DOM half: opening a doc-link in the Reading Pane embeds an
`<iframe src="/app/docs?path=...">` inside `#content-pane-body`, sized to fill
the pane (the legacy "postage stamp" regression — `.content-pane` definite
height + `.content-pane-body:has(iframe)` zero-gutter). Loopback host prefixes
are normalized off the src so the doc resolves when reached from a remote host.

Driven via the boot test hook + a real doc-link click (document-level
delegation). Does NOT assert the doc CONTENT renders (cross-origin/auth timing);
the iframe element + src + geometry are the smoke surface.

Venue: :8000 (scheduled monopolize-mode via /api/test-suite/submit). Submit via:

    POST /api/test-suite/submit
    {
        "test_types"         : "e2e_ui",
        "pytest_args"        : "-k test_multiplexer_doc_viewer_iframe_embedding",
        "scheduled_at"       : "<slot>",
        "auto_fix_on_failure": false
    }
"""

from __future__ import annotations

from .conftest import BASE_URL

DOC_HREF = "/app/docs?path=lupin/README.md"


def _open_multiplexer( page ):
    page.goto( f"{BASE_URL}/app/multiplexer" )
    page.wait_for_load_state( "networkidle" )
    page.wait_for_function(
        "() => window.__multiplexerTestHook"
        " && window.__multiplexerTestHook.stores"
        " && window.__multiplexerTestHook.stores.readingPane",
        timeout=15000,
    )


def _click_layout_toggle( page ):
    page.locator( "#layout-mode-toggle" ).click()
    page.wait_for_timeout( 100 )


def _iframe_info( page ):
    return page.evaluate(
        """() => {
            const body  = document.getElementById( 'content-pane-body' );
            const frame = body ? body.querySelector( 'iframe' ) : null;
            if ( !frame ) return { present: false };
            const r = frame.getBoundingClientRect();
            return {
                present: true,
                src    : frame.getAttribute( 'src' ),
                width  : r.width,
                height : r.height,
            };
        }"""
    )


class TestMultiplexerDocViewerIframeEmbedding:
    """Opening a doc-link embeds a pane-filling same-origin iframe."""

    def test_doc_link_click_embeds_iframe_in_pane( self, logged_in_page ):
        page = logged_in_page
        _open_multiplexer( page )
        _click_layout_toggle( page )   # → horizontal

        # Inject a real doc-link anchor into the center column; the document-level
        # delegation routes the click into the pane as a doc entry.
        page.evaluate(
            """( href ) => {
                const container = document.querySelector( '.left-column .container' ) || document.body;
                const a = document.createElement( 'a' );
                a.setAttribute( 'href', href );
                a.textContent = 'Open README';
                a.dataset.testDoc = '1';
                container.appendChild( a );
                return true;
            }""",
            DOC_HREF,
        )
        page.locator( "a[data-test-doc='1']" ).click()
        page.wait_for_timeout( 200 )

        info = _iframe_info( page )
        assert info[ "present" ] is True, "doc-link click must embed an iframe in #content-pane-body"
        assert info[ "src" ] == DOC_HREF, f"iframe src must be the doc href; got {info.get('src')!r}"
        # Fills the pane (not the ~150px postage-stamp): well over 200px tall.
        assert info[ "height" ] > 200, \
            f"iframe must fill the pane height (definite .content-pane height); got {info['height']:.0f}px"

    def test_loopback_prefix_normalized_off_src( self, logged_in_page ):
        page = logged_in_page
        _open_multiplexer( page )
        _click_layout_toggle( page )   # → horizontal
        # Open a doc whose href carries an absolute loopback prefix; the renderer
        # strips it so the src resolves from any host.
        page.evaluate(
            "( href ) => window.__multiplexerTestHook.stores.readingPane.open( 'doc', href, 'Doc' )",
            f"http://localhost:7999{DOC_HREF}",
        )
        page.wait_for_timeout( 150 )
        info = _iframe_info( page )
        assert info[ "present" ] is True
        assert info[ "src" ] == DOC_HREF, \
            f"loopback host prefix must be stripped from the iframe src; got {info.get('src')!r}"
