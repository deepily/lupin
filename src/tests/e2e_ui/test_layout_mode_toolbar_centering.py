"""
E2E UI tests for the layout-mode toolbar centering over the container.

Regression (fixed 2026-05-30, Speedy 🌿 session fb0bc8a5): in horizontal
layout mode the floating .section-toolbar centers itself via the
`--toolbar-center-x` CSS variable (with `transform: translateX(-50%)`).
`_updateToolbarPosition` set that variable to `paneSplitRatio / 2 * 100%`
UNCONDITIONALLY — i.e. the left-column center *as if the Reading Pane were
open*. But the pane is closed by default after a toggle to horizontal, so
the container actually spans the full width (center = 50%). The toolbar
parked at ~33% (half the 0.667 default split) — skewed wildly left.

Fix: `_updateToolbarPosition` is now pane-aware (50% when closed, ratio/2
when open) and is re-invoked when the pane opens/closes.

Venue: :8000 (scheduled monopolize-mode via /api/test-suite/submit).

Submit via:

    POST /api/test-suite/submit
    {
        "test_types"         : "e2e",
        "pytest_args"        : "-k test_layout_mode_toolbar_centering",
        "scheduled_at"       : "<user-confirmed-slot>",
        "auto_fix_on_failure": false
    }
"""

import pytest

from .conftest import BASE_URL


def _toolbar_center_var( page ):
    """Inline value of --toolbar-center-x on <html> ('' when removed)."""
    return page.evaluate(
        "() => document.documentElement.style.getPropertyValue( '--toolbar-center-x' ).trim()"
    )


def _click_layout_toggle( page ):
    page.locator( "#layout-mode-toggle" ).click()
    page.wait_for_timeout( 100 )


class TestLayoutModeToolbarCentering:
    """The section-toolbar centers over the container in horizontal mode."""

    def test_vertical_mode_clears_center_var( self, notifications_page ):
        page = notifications_page
        # Default load is vertical mode → the legacy left:calc() rule applies and
        # the JS variable must be absent.
        assert page.evaluate( "() => document.body.getAttribute( 'data-layout-mode' )" ) == "vertical"
        assert _toolbar_center_var( page ) == "", \
            "Vertical mode must not set --toolbar-center-x (legacy left:calc rule owns position)"

    def test_horizontal_pane_closed_centers_at_50pct( self, notifications_page ):
        page = notifications_page
        _click_layout_toggle( page )  # → horizontal, pane closed (default)

        assert page.evaluate( "() => document.body.getAttribute( 'data-layout-mode' )" ) == "horizontal"
        # The bug: this read "33.35%" (0.667/2*100). Correct value with the pane
        # closed is 50% — the full-width container's center.
        assert _toolbar_center_var( page ) == "50.00%", \
            "Pane-closed horizontal mode must center the toolbar at 50% of the viewport"

    def test_toolbar_geometrically_centered_over_container( self, notifications_page ):
        """The real user-facing property: toolbar center ≈ container center."""
        page = notifications_page
        _click_layout_toggle( page )  # → horizontal, pane closed

        geo = page.evaluate(
            """() => {
                const tb = document.querySelector( '.section-toolbar' ).getBoundingClientRect();
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

    def test_open_pane_recenters_to_left_column( self, notifications_page ):
        page = notifications_page
        _click_layout_toggle( page )  # → horizontal, pane closed

        # Open the Reading Pane → left column shrinks to `ratio` of the width;
        # the toolbar must re-center over that narrower column (ratio/2*100).
        expected = page.evaluate(
            """() => {
                const ui = window.notificationsUI;
                ui._openContentPane( 'abstract', '# Heading\\n\\nSome body text.', 'Test' );
                return ( ui._paneSplitRatio / 2 * 100 ).toFixed( 2 ) + '%';
            }"""
        )
        page.wait_for_timeout( 100 )
        assert _toolbar_center_var( page ) == expected, \
            f"Pane-open horizontal mode must center over the left column ({expected})"

    def test_close_pane_recenters_to_50pct( self, notifications_page ):
        page = notifications_page
        _click_layout_toggle( page )  # → horizontal, pane closed

        page.evaluate(
            "() => window.notificationsUI._openContentPane( 'abstract', '# H\\n\\nbody', 'T' )"
        )
        page.wait_for_timeout( 50 )
        page.evaluate( "() => window.notificationsUI._closeContentPane()" )
        page.wait_for_timeout( 50 )

        assert _toolbar_center_var( page ) == "50.00%", \
            "Closing the pane must re-center the toolbar at 50% (full-width container)"

    def test_toggle_back_to_vertical_clears_var( self, notifications_page ):
        page = notifications_page
        _click_layout_toggle( page )  # → horizontal
        _click_layout_toggle( page )  # → vertical

        assert page.evaluate( "() => document.body.getAttribute( 'data-layout-mode' )" ) == "vertical"
        assert _toolbar_center_var( page ) == "", \
            "Returning to vertical mode must remove --toolbar-center-x"


class TestReadingPaneIframeFillsContainer:
    """
    Regression (fixed 2026-05-30, Speedy 🌿): a doc opened in the Reading Pane
    rendered as a ~150px "postage stamp" because `.content-pane` had only
    `max-height` + `align-self: flex-start` (content-sized / indefinite height),
    so the iframe's `height: 100%` had no resolved parent height. Fix: definite
    `.content-pane` height (calc(100vh - 100px)) + `.content-pane-body
    { min-height: 0 }` + zero padding when the body holds an iframe.
    """

    def test_doc_iframe_fills_pane_body( self, notifications_page ):
        page = notifications_page
        _click_layout_toggle( page )  # → horizontal

        # Open a doc in the pane (iframe element is CSS-sized regardless of
        # whether the doc content finishes loading).
        page.evaluate(
            "() => window.notificationsUI._openContentPane( 'doc', '/app/docs?path=lupin/README.md', 'Doc' )"
        )
        page.wait_for_timeout( 200 )

        dims = page.evaluate(
            """() => {
                const body  = document.querySelector( '.content-pane-body' );
                const frame = body ? body.querySelector( 'iframe' ) : null;
                if ( !body || !frame ) return null;
                const b = body.getBoundingClientRect();
                const f = frame.getBoundingClientRect();
                // clientWidth = the body's CONTENT width (excludes a vertical scrollbar
                // gutter); the iframe correctly fills that, not the border-box width.
                return { bodyH: b.height, bodyW: b.width, bodyClientW: body.clientWidth,
                         frameH: f.height, frameW: f.width };
            }"""
        )
        assert dims is not None, "Pane body + iframe must exist after opening a doc"
        # Not a postage stamp: the iframe must be far taller than the ~150px
        # intrinsic default that the bug produced.
        assert dims[ "frameH" ] > 400, (
            f"Doc iframe must fill the pane height, not collapse to its intrinsic "
            f"~150px; got {dims['frameH']:.0f}px"
        )
        # Iframe fills the body in both dimensions (padding:0 for the iframe case).
        assert abs( dims[ "frameH" ] - dims[ "bodyH" ] ) < 4, (
            f"iframe height ({dims['frameH']:.0f}) must match pane-body height "
            f"({dims['bodyH']:.0f})"
        )
        # Compare against the body's CONTENT width (clientWidth), not the border-box
        # width: when the pane body shows a vertical scrollbar (~15px gutter) the iframe
        # fills the content area, which is the correct fill behavior (an iframe must not
        # overlap the scrollbar). Asserting against getBoundingClientRect width would
        # false-fail by exactly the scrollbar width.
        assert abs( dims[ "frameW" ] - dims[ "bodyClientW" ] ) < 4, (
            f"iframe width ({dims['frameW']:.0f}) must fill the pane-body content width "
            f"({dims['bodyClientW']:.0f}); border-box width was {dims['bodyW']:.0f}"
        )


class TestReadingPaneBustOut:
    """
    The header "bust out" button (⤢, 2026-05-30, Speedy 🌿) pops the pane's
    current content into a new browser tab, then closes the pane — which
    restores the centered full-width layout and re-centers the toolbar.
    (A new tab is a new Page in the same Playwright context, so
    context.expect_page() catches it the same way it would a pop-up window.)
    """

    def test_bustout_doc_opens_window_and_closes_pane( self, notifications_page ):
        page = notifications_page
        _click_layout_toggle( page )  # → horizontal

        page.evaluate(
            "() => window.notificationsUI._openContentPane( 'doc', '/app/docs?path=lupin/README.md', 'Doc' )"
        )
        page.wait_for_timeout( 100 )

        with page.context.expect_page() as popup_info:
            page.click( "#content-pane-bustout" )
        popup = popup_info.value
        assert popup is not None, "Bust-out must open a new tab for a doc"
        assert "/app/docs" in popup.url, \
            f"Pop-up should load the doc-viewer URL; got {popup.url!r}"
        popup.close()

        assert page.evaluate( "() => document.getElementById( 'content-pane' ).hidden" ), \
            "Bust-out must close the reading pane"
        assert _toolbar_center_var( page ) == "50.00%", \
            "Closing via bust-out must re-center the toolbar at 50%"

    def test_bustout_abstract_opens_window_and_closes_pane( self, notifications_page ):
        page = notifications_page
        _click_layout_toggle( page )  # → horizontal

        page.evaluate(
            "() => window.notificationsUI._openContentPane( 'abstract', '# Hello\\n\\nAbstract body text.', 'Abs' )"
        )
        page.wait_for_timeout( 100 )

        with page.context.expect_page() as popup_info:
            page.click( "#content-pane-bustout" )
        popup = popup_info.value
        assert popup is not None, "Bust-out must open a new tab for an abstract"
        popup.close()

        assert page.evaluate( "() => document.getElementById( 'content-pane' ).hidden" ), \
            "Bust-out must close the reading pane after popping out the abstract"
