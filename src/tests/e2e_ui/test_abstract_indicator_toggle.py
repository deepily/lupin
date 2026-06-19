"""
E2E UI — abstract-indicator click is a TOGGLE in horizontal mode (Rick, 2026-06-08).

In horizontal (master-detail) layout, clicking the abstract icon (📋) opens the
Reading Pane with the abstract; clicking the SAME indicator again CLEARS the pane
(toggle off). Clicking a DIFFERENT indicator switches the pane content instead of
toggling. Vertical mode is unaffected (legacy tooltip path).

Implemented via `_abstractAlreadyShown` in the current JS client (notifications.js);
the decision logic is unit-covered in
`src/tests/unit/notifications_js/reading_pane_scroll_anchor.test.ts`. THIS verifies
the real click → DOM behavior end to end.

Venue: :8000 (scheduled monopolize-mode via /api/test-suite/submit).

Submit via:

    POST /api/test-suite/submit
    {
        "test_types"         : "e2e",
        "pytest_args"        : "-k test_abstract_indicator_toggle",
        "scheduled_at"       : "<slot>",
        "auto_fix_on_failure": false
    }
"""

import pytest

from .conftest import BASE_URL


def _click_layout_toggle( page ):
    page.locator( "#layout-mode-toggle" ).click()
    page.wait_for_timeout( 100 )


def _inject_indicator( page, abstract_text ):
    """
    Inject a real `.abstract-indicator` into the center column so the document-level
    click delegation + the horizontal-mode branch fire on a normal Playwright click.
    A `data-test-abstract` attribute gives the test a stable locator.
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


def _locator( page, abstract_text ):
    return page.locator( f".abstract-indicator[data-test-abstract={abstract_text!r}]" )


class TestAbstractIndicatorToggle:
    """Click shows the abstract in the Reading Pane; click again clears it."""

    def test_click_shows_then_second_click_clears( self, notifications_page ):
        page = notifications_page
        _click_layout_toggle( page )                       # → horizontal, pane closed
        _inject_indicator( page, "**Toggle me**" )
        ind = _locator( page, "**Toggle me**" )

        ind.click()
        page.wait_for_timeout( 120 )
        assert _pane_open( page ), "first click must OPEN the Reading Pane"
        assert page.evaluate(
            "() => window.notificationsUI._contentPaneHistory.length"
        ) == 1, "one abstract entry on the pane history"

        ind.click()
        page.wait_for_timeout( 120 )
        assert not _pane_open( page ), \
            "second click on the SAME indicator must CLEAR the pane (toggle off)"
        assert page.evaluate( "() => document.getElementById( 'content-pane' ).hidden" ), \
            "content-pane must be hidden after toggle-off"

    def test_click_different_indicator_switches_not_clears( self, notifications_page ):
        page = notifications_page
        _click_layout_toggle( page )
        _inject_indicator( page, "**First abstract**" )
        _inject_indicator( page, "**Second abstract**" )

        _locator( page, "**First abstract**" ).click()
        page.wait_for_timeout( 120 )
        assert _pane_open( page ), "first indicator opens the pane"

        _locator( page, "**Second abstract**" ).click()
        page.wait_for_timeout( 120 )
        assert _pane_open( page ), "clicking a DIFFERENT indicator must SWITCH, not clear"
        current = page.evaluate(
            "() => { const h = window.notificationsUI._contentPaneHistory; return h[ h.length - 1 ].payload; }"
        )
        assert current == "**Second abstract**", "pane now shows the second abstract"

    def test_vertical_mode_does_not_open_pane( self, notifications_page ):
        page = notifications_page
        # Default load is vertical — the abstract click uses the legacy tooltip,
        # never the Reading Pane (toggle is horizontal-only).
        assert page.evaluate(
            "() => document.body.getAttribute( 'data-layout-mode' )"
        ) == "vertical"
        _inject_indicator( page, "**Vertical**" )
        _locator( page, "**Vertical**" ).click()
        page.wait_for_timeout( 120 )
        assert not _pane_open( page ), \
            "vertical mode must NOT open the Reading Pane (tooltip path, unaffected by the toggle)"
