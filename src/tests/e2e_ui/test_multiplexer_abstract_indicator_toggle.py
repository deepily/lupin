"""
E2E UI — multiplexer abstract-indicator click is a TOGGLE in horizontal mode
(Lane C WP4, 2026-06-10).

Mirrors the JS-client `test_abstract_indicator_toggle.py` against the
multiplexer's ReadingPaneRenderer. In horizontal (master-detail) layout,
clicking the abstract icon (📋) opens the Reading Pane with the abstract;
clicking the SAME indicator again CLEARS the pane (toggle off); clicking a
DIFFERENT indicator SWITCHES content. Vertical mode never opens the pane.

The decision logic is unit-covered in `reading_pane_store.test.ts`
(`isAbstractShown`) + `reading_pane_renderer.test.ts` (the document-level click
delegation); THIS verifies the real click → DOM behavior end to end.

Venue: :8000 (scheduled monopolize-mode via /api/test-suite/submit). Submit via:

    POST /api/test-suite/submit
    {
        "test_types"         : "e2e_ui",
        "pytest_args"        : "-k test_multiplexer_abstract_indicator_toggle",
        "scheduled_at"       : "<slot>",
        "auto_fix_on_failure": false
    }
"""

from __future__ import annotations

from .conftest import BASE_URL


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


def _inject_indicator( page, abstract_text ):
    """
    Inject a real `.abstract-indicator` into the center column so the
    document-level click delegation + the horizontal-mode branch fire on a
    normal Playwright click. `data-test-abstract` gives the test a stable locator.
    """
    page.evaluate(
        """( txt ) => {
            const container = document.querySelector( '.left-column .container' ) || document.body;
            const host = document.createElement( 'div' );
            host.className = 'sender-card';
            const ind = document.createElement( 'span' );
            ind.className = 'abstract-indicator';
            ind.dataset.abstract     = encodeURIComponent( txt );
            ind.dataset.testAbstract = txt;
            ind.textContent = '📋';
            host.appendChild( ind );
            container.appendChild( host );
            return true;
        }""",
        abstract_text,
    )


def _pane_open( page ):
    return page.evaluate( "() => !!document.querySelector( '.content-shell.pane-open' )" )


def _history_len( page ):
    return page.evaluate(
        "() => window.__multiplexerTestHook.stores.readingPane.getHistory().length"
    )


def _current_payload( page ):
    return page.evaluate(
        "() => { const e = window.__multiplexerTestHook.stores.readingPane.currentEntry(); return e ? e.payload : null; }"
    )


def _locator( page, abstract_text ):
    return page.locator( f".abstract-indicator[data-test-abstract={abstract_text!r}]" )


class TestMultiplexerAbstractIndicatorToggle:
    """Click shows the abstract in the Reading Pane; click again clears it."""

    def test_click_shows_then_second_click_clears( self, logged_in_page ):
        page = logged_in_page
        _open_multiplexer( page )
        _click_layout_toggle( page )                       # → horizontal, pane closed
        _inject_indicator( page, "**Toggle me**" )
        ind = _locator( page, "**Toggle me**" )

        ind.click()
        page.wait_for_timeout( 120 )
        assert _pane_open( page ), "first click must OPEN the Reading Pane"
        assert _history_len( page ) == 1, "one abstract entry on the pane history"

        ind.click()
        page.wait_for_timeout( 120 )
        assert not _pane_open( page ), \
            "second click on the SAME indicator must CLEAR the pane (toggle off)"
        assert page.evaluate( "() => document.getElementById( 'content-pane' ).hidden" ), \
            "content-pane must be hidden after toggle-off"

    def test_click_different_indicator_switches_not_clears( self, logged_in_page ):
        page = logged_in_page
        _open_multiplexer( page )
        _click_layout_toggle( page )
        _inject_indicator( page, "**First abstract**" )
        _inject_indicator( page, "**Second abstract**" )

        _locator( page, "**First abstract**" ).click()
        page.wait_for_timeout( 120 )
        assert _pane_open( page ), "first indicator opens the pane"

        _locator( page, "**Second abstract**" ).click()
        page.wait_for_timeout( 120 )
        assert _pane_open( page ), "clicking a DIFFERENT indicator must SWITCH, not clear"
        assert _current_payload( page ) == "**Second abstract**", \
            "pane now shows the second abstract"

    def test_vertical_mode_does_not_open_pane( self, logged_in_page ):
        page = logged_in_page
        _open_multiplexer( page )
        # Default load is vertical — the abstract click must NOT open the pane
        # (toggle is horizontal-only).
        assert page.evaluate(
            "() => document.body.getAttribute( 'data-layout-mode' )"
        ) == "vertical"
        _inject_indicator( page, "**Vertical**" )
        _locator( page, "**Vertical**" ).click()
        page.wait_for_timeout( 120 )
        assert not _pane_open( page ), \
            "vertical mode must NOT open the Reading Pane"
