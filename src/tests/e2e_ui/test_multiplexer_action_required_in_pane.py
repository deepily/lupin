"""
E2E UI — multiplexer Action-Required lifted into the Reading Pane (Lane C WP5,
2026-06-10).

Mirrors the JS-client `test_action_required_in_pane.py` against the
multiplexer. In horizontal layout, an arriving action-required notification
LIFTS-AND-MOVES the live `#action-required-section` element into the Reading
Pane at a forced 50/50 split. When the queue drains (the prompt is responded /
removed) the section moves home and the pane closes. Vertical mode never lifts.

Drives the real wire path: `notification_queue_update` (response_requested:true)
→ ActionRequiredStore → `store_action_required_changed` →
ReadingPaneRenderer.reconcileActionRequired → store.enterActionRequiredPane.
Injected via the boot test hook eventBus.

Venue: :8000 (scheduled monopolize-mode via /api/test-suite/submit). Submit via:

    POST /api/test-suite/submit
    {
        "test_types"         : "e2e_ui",
        "pytest_args"        : "-k test_multiplexer_action_required_in_pane",
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


def _emit_action_required( page, nid ):
    """Inject an action-required notification frame via the boot test hook eventBus."""
    page.evaluate(
        """( nid ) => {
            window.__multiplexerTestHook.eventBus.emit( {
                type    : 'notification_queue_update',
                payload : {
                    notification: {
                        id_hash            : nid,
                        message            : 'Deploy to prod?',
                        sender_id          : 'claude.code@lupin.deepily.ai#arpane1',
                        timestamp          : '2026-06-10T18:00:00.000Z',
                        response_requested : true,
                        response_type      : 'yes_no',
                        response_options   : [ 'yes', 'no' ],
                        timeout_seconds    : 300,
                    }
                },
                source : 'ar-pane-e2e',
                ts     : 1778169600000,
            } );
        }""",
        nid,
    )
    page.wait_for_timeout( 250 )


def _pane_state( page ):
    return page.evaluate(
        """() => {
            const section = document.getElementById( 'action-required-section' );
            const body    = document.getElementById( 'content-pane-body' );
            const shell   = document.querySelector( '.content-shell' );
            const rp      = window.__multiplexerTestHook.stores.readingPane;
            return {
                inPane   : ( section && body ) ? ( section.parentNode === body ) : null,
                paneOpen : !!( shell && shell.classList.contains( 'pane-open' ) ),
                ratio    : rp.getSplitRatio(),
                flag     : rp.isActionRequiredInPane(),
                marked   : section ? section.classList.contains( 'in-reading-pane' ) : null,
            };
        }"""
    )


class TestMultiplexerActionRequiredInPane:

    def test_action_required_moves_into_pane_in_horizontal( self, logged_in_page ):
        page = logged_in_page
        _open_multiplexer( page )
        _click_layout_toggle( page )                       # → horizontal
        _emit_action_required( page, "mux-ar-pane-1" )

        info = _pane_state( page )
        assert info[ "inPane" ] is True, "#action-required-section must move into the pane body"
        assert info[ "paneOpen" ] is True, "pane must open"
        assert info[ "ratio" ] == 0.5, "split forced to 50/50 while AR owns the pane"
        assert info[ "flag" ] is True
        assert info[ "marked" ] is True, "lifted section carries the .in-reading-pane class"

    def test_drain_restores_section_home_and_closes_pane( self, logged_in_page ):
        page = logged_in_page
        _open_multiplexer( page )
        # mux commit 75a1bad3 (Lane 0a+0c) relocated #action-required-section from
        # inside #notifications-pane to a standalone LEADING accordion under
        # <main class="container">. Capture its RESTING home parent BEFORE the lift
        # so the restore assertion is robust to WHERE that home is (and to future
        # relocations) — the point is "restored home", not a hardcoded parent id.
        home_marker = page.evaluate(
            "() => { const s = document.getElementById( 'action-required-section' );"
            "        const p = s && s.parentElement;"
            "        return p ? ( p.id || p.className || p.tagName ) : null; }"
        )
        _click_layout_toggle( page )                       # → horizontal
        _emit_action_required( page, "mux-ar-pane-2" )
        assert _pane_state( page )[ "inPane" ] is True

        # Respond → ActionRequiredStore removes the item → list empties →
        # renderer exits AR-pane mode + restores the section home.
        page.evaluate(
            "() => window.__multiplexerTestHook.stores.actionRequired.respond( 'mux-ar-pane-2', 'yes' )"
        )
        page.wait_for_timeout( 300 )

        after = page.evaluate(
            """() => {
                const section = document.getElementById( 'action-required-section' );
                const pane    = document.getElementById( 'content-pane' );
                const rp      = window.__multiplexerTestHook.stores.readingPane;
                return {
                    homeParent : section && section.parentElement
                        ? ( section.parentElement.id || section.parentElement.className || section.parentElement.tagName )
                        : null,
                    paneHidden : pane ? pane.hidden : null,
                    flag       : rp.isActionRequiredInPane(),
                    marked     : section ? section.classList.contains( 'in-reading-pane' ) : null,
                };
            }"""
        )
        assert after[ "homeParent" ] == home_marker, \
            "drained section must return to its resting home parent (mux 75a1bad3 " \
            "relocated it from #notifications-pane to a standalone accordion under " \
            "<main class=\"container\">)"
        assert after[ "flag" ] is False, "AR-in-pane flag cleared on drain"
        assert after[ "marked" ] is False, "the .in-reading-pane class is removed on restore"
        assert after[ "paneHidden" ] is True, "pane closes when nothing else was open"

    def test_vertical_mode_keeps_action_required_at_home( self, logged_in_page ):
        page = logged_in_page
        _open_multiplexer( page )
        # Default load is vertical — AR must NOT move into the pane.
        _emit_action_required( page, "mux-ar-vert-1" )
        state = _pane_state( page )
        assert state[ "inPane" ] is False, "vertical mode must NOT move action-required into the pane"
        assert state[ "flag" ] is False
