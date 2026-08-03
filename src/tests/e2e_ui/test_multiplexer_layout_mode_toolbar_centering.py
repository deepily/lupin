"""
E2E UI — multiplexer layout-mode toolbar centering (Lane C WP4, 2026-06-10).

Mirrors the JS-client `test_layout_mode_toolbar_centering.py` against the
multiplexer's ReadingPaneRenderer. In horizontal layout the floating
`.reading-pane-toolbar` centers itself via the `--toolbar-center-x` CSS variable
(with `transform: translateX(-50%)`). `updateToolbarPosition()` is pane-aware:
50% when the pane is closed (full-width container), `ratio/2 * 100%` when open
(centered over the narrower left column); the variable is removed entirely in
vertical mode.

Driven via the boot test hook `window.__multiplexerTestHook.stores.readingPane`
(open/close) + the real `#layout-mode-toggle` click (toggle), exercising the
renderer's DOM wiring end-to-end.

Venue: :8000 (scheduled monopolize-mode via /api/test-suite/submit). NEVER run
side-door (ad-hoc curl / direct queue push / in-process). Submit via:

    POST /api/test-suite/submit
    {
        "test_types"         : "e2e_ui",
        "pytest_args"        : "-k test_multiplexer_layout_mode_toolbar_centering",
        "scheduled_at"       : "<user-confirmed slot>",
        "auto_fix_on_failure": false
    }
"""

from __future__ import annotations

from .conftest import BASE_URL


def _open_multiplexer( page ):
    """Navigate to the multiplexer + wait for the boot test hook (post boot_complete)."""
    page.goto( f"{BASE_URL}/app/multiplexer" )
    page.wait_for_load_state( "networkidle" )
    page.wait_for_function(
        "() => window.__multiplexerTestHook"
        " && window.__multiplexerTestHook.stores"
        " && window.__multiplexerTestHook.stores.readingPane",
        timeout=15000,
    )


def _toolbar_center_var( page ):
    """Inline value of --toolbar-center-x on <html> ('' when removed)."""
    return page.evaluate(
        "() => document.documentElement.style.getPropertyValue( '--toolbar-center-x' ).trim()"
    )


def _click_layout_toggle( page ):
    page.locator( "#layout-mode-toggle" ).click()
    page.wait_for_timeout( 100 )


def _open_abstract( page, md="# Heading\n\nSome body text.", title="Test" ):
    """Open an abstract in the pane via the store (renderer repaints on emit)."""
    page.evaluate(
        "( args ) => window.__multiplexerTestHook.stores.readingPane.open( 'abstract', args.md, args.title )",
        { "md": md, "title": title },
    )
    page.wait_for_timeout( 100 )


class TestMultiplexerLayoutModeToolbarCentering:
    """The reading-pane toolbar centers over its column in horizontal mode."""

    def test_vertical_mode_clears_center_var( self, logged_in_page ):
        page = logged_in_page
        _open_multiplexer( page )
        # Default load is vertical → --toolbar-center-x must be absent.
        assert page.evaluate( "() => document.body.getAttribute( 'data-layout-mode' )" ) == "vertical"
        assert _toolbar_center_var( page ) == "", \
            "Vertical mode must not set --toolbar-center-x"

    def test_horizontal_pane_closed_centers_at_50pct( self, logged_in_page ):
        page = logged_in_page
        _open_multiplexer( page )
        _click_layout_toggle( page )   # → horizontal, pane closed (default)
        assert page.evaluate( "() => document.body.getAttribute( 'data-layout-mode' )" ) == "horizontal"
        assert _toolbar_center_var( page ) == "50.00%", \
            "Pane-closed horizontal mode must center the toolbar at 50% of the viewport"

    def test_toolbar_geometrically_centered_over_container( self, logged_in_page ):
        page = logged_in_page
        _open_multiplexer( page )
        _click_layout_toggle( page )   # → horizontal, pane closed
        geo = page.evaluate(
            """() => {
                const tb = document.querySelector( '.reading-pane-toolbar' ).getBoundingClientRect();
                const ct = document.querySelector( '.container' ).getBoundingClientRect();
                return {
                    toolbarCenter:   tb.left + tb.width  / 2,
                    containerCenter: ct.left + ct.width  / 2
                };
            }"""
        )
        delta = abs( geo[ "toolbarCenter" ] - geo[ "containerCenter" ] )
        assert delta < 30, (
            f"Toolbar must sit over the container center; off by {delta:.1f}px "
            f"(toolbar={geo['toolbarCenter']:.1f}, container={geo['containerCenter']:.1f})"
        )

    def test_open_pane_recenters_to_left_column( self, logged_in_page ):
        page = logged_in_page
        _open_multiplexer( page )
        _click_layout_toggle( page )   # → horizontal, pane closed
        # Open the Reading Pane → left column shrinks to `ratio`; the toolbar must
        # re-center over that narrower column (ratio/2*100).
        expected = page.evaluate(
            """() => {
                const rp = window.__multiplexerTestHook.stores.readingPane;
                rp.open( 'abstract', '# Heading\\n\\nSome body text.', 'Test' );
                return ( rp.getSplitRatio() / 2 * 100 ).toFixed( 2 ) + '%';
            }"""
        )
        page.wait_for_timeout( 100 )
        assert _toolbar_center_var( page ) == expected, \
            f"Pane-open horizontal mode must center over the left column ({expected})"

    def test_close_pane_recenters_to_50pct( self, logged_in_page ):
        page = logged_in_page
        _open_multiplexer( page )
        _click_layout_toggle( page )   # → horizontal
        _open_abstract( page )
        page.evaluate( "() => window.__multiplexerTestHook.stores.readingPane.close()" )
        page.wait_for_timeout( 80 )
        assert _toolbar_center_var( page ) == "50.00%", \
            "Closing the pane must re-center the toolbar at 50% (full-width container)"

    def test_toggle_back_to_vertical_clears_var( self, logged_in_page ):
        page = logged_in_page
        _open_multiplexer( page )
        _click_layout_toggle( page )   # → horizontal
        _click_layout_toggle( page )   # → vertical
        assert page.evaluate( "() => document.body.getAttribute( 'data-layout-mode' )" ) == "vertical"
        assert _toolbar_center_var( page ) == "", \
            "Returning to vertical mode must remove --toolbar-center-x"


def _container_padding_top( page ):
    """Computed padding-top of .container (px string, e.g. '52px')."""
    return page.evaluate(
        "() => getComputedStyle( document.querySelector( '.container' ) ).paddingTop"
    )


class TestMultiplexerLayoutModeContainerReflow:
    """Lane 0b (F-Clay-A1) — horizontal mode reflows the container immediately on
    toggle, WITHOUT waiting for a pane to open.

    The `.reading-pane-toolbar` floats `position:fixed` in horizontal mode
    regardless of pane state, so `.container` must gain the 52px top padding that
    clears it whenever horizontal — un-gated on `.content-shell.pane-open`. This
    is byte-faithful to the legacy un-gated rule (notifications.css :5632) and was
    confirmed at runtime against the legacy client at /app/notifications (vertical
    20px → horizontal 52px, pane closed). Before the fix the mux gated the padding
    on pane-open, so toggling to horizontal with no pane open produced no visible
    reflow — the Lane 0b defect. Per-mode computed-style assertions are the CSS
    branch-coverage vehicle (c8 covers TS only — see F-Sam-A1).
    """

    def test_vertical_mode_baseline_padding( self, logged_in_page ):
        page = logged_in_page
        _open_multiplexer( page )
        assert page.evaluate( "() => document.body.getAttribute( 'data-layout-mode' )" ) == "vertical"
        assert _container_padding_top( page ) == "20px", \
            "Vertical mode keeps the base container padding (no toolbar to clear)"

    def test_horizontal_pane_closed_reflows_container( self, logged_in_page ):
        page = logged_in_page
        _open_multiplexer( page )
        _click_layout_toggle( page )   # → horizontal, pane CLOSED (default)
        assert page.evaluate( "() => document.body.getAttribute( 'data-layout-mode' )" ) == "horizontal"
        assert page.evaluate(
            "() => document.querySelector( '.content-shell' ).classList.contains( 'pane-open' )"
        ) is False, "Precondition: the pane must be closed for the un-gated reflow assertion"
        assert _container_padding_top( page ) == "52px", (
            "Horizontal mode (pane closed) must reflow the container to 52px top "
            "padding to clear the floating toolbar — the un-gated Lane 0b fix"
        )

    def test_horizontal_pane_open_keeps_padding( self, logged_in_page ):
        page = logged_in_page
        _open_multiplexer( page )
        _click_layout_toggle( page )   # → horizontal
        _open_abstract( page )         # open the Reading Pane → pane-open split
        assert page.evaluate(
            "() => document.querySelector( '.content-shell' ).classList.contains( 'pane-open' )"
        ) is True
        assert _container_padding_top( page ) == "52px", \
            "The 52px toolbar-clearing padding persists once the pane opens (still horizontal)"

    def test_toggle_back_to_vertical_clears_padding( self, logged_in_page ):
        page = logged_in_page
        _open_multiplexer( page )
        _click_layout_toggle( page )   # → horizontal
        _click_layout_toggle( page )   # → vertical
        assert page.evaluate( "() => document.body.getAttribute( 'data-layout-mode' )" ) == "vertical"
        assert _container_padding_top( page ) == "20px", \
            "Returning to vertical mode must drop the toolbar-clearing padding"
