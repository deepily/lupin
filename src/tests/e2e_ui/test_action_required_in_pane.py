"""
E2E UI — Action Required card in the reader pane (horizontal mode, Rick 2026-06-08).

In horizontal layout, an arriving action-required notification LIFTS-AND-MOVES the
live #action-required-content element into the reader pane at a forced 50/50 split,
hiding its home section. In vertical mode the content stays in its top section
(unchanged). Drives the real `handleNotificationUpdate` → `addActionRequiredNotification`
→ `_enterActionRequiredPaneMode` path in a live browser.

Venue: :8000 (scheduled monopolize-mode via /api/test-suite/submit).
"""

import pytest

from .conftest import BASE_URL


def _click_layout_toggle( page ):
    page.locator( "#layout-mode-toggle" ).click()
    page.wait_for_timeout( 100 )


def _emit_action_required( page, nid ):
    page.evaluate(
        """( nid ) => {
            window.notificationsUI.handleNotificationUpdate( {
                notification: {
                    id                 : nid,
                    id_hash            : nid,
                    type               : 'custom',
                    response_requested : true,
                    response_type      : 'yes_no',
                    message            : 'Deploy to prod?',
                    timeout_seconds    : 300,
                    sender_id          : 'claude.code@lupin.deepily.ai#arpane1'
                }
            } );
        }""",
        nid,
    )


class TestActionRequiredInPane:

    def test_action_required_moves_into_pane_in_horizontal( self, notifications_page ):
        page = notifications_page
        _click_layout_toggle( page )                       # → horizontal
        _emit_action_required( page, "ar-pane-test-1" )
        page.wait_for_timeout( 250 )

        info = page.evaluate(
            """() => {
                const content = document.getElementById( 'action-required-content' );
                const body    = document.getElementById( 'content-pane-body' );
                const shell   = document.querySelector( '.content-shell' );
                const section = document.getElementById( 'action-required-section' );
                return {
                    inPane    : ( content && body ) ? ( content.parentNode === body ) : null,
                    paneOpen  : !!( shell && shell.classList.contains( 'pane-open' ) ),
                    homeHidden: section ? ( section.style.display === 'none' ) : null,
                    ratio     : window.notificationsUI._paneSplitRatio,
                    flag      : window.notificationsUI._actionRequiredInPane
                };
            }"""
        )
        assert info[ "inPane" ] is True, "action-required-content must move into the pane body"
        assert info[ "paneOpen" ] is True, "pane must open"
        assert info[ "homeHidden" ] is True, "home section hidden while content is in the pane"
        assert info[ "ratio" ] == 0.5, "split forced to 50/50"
        assert info[ "flag" ] is True

    def test_vertical_mode_keeps_action_required_at_top( self, notifications_page ):
        page = notifications_page
        # Default load is vertical — the content must NOT move into the pane.
        _emit_action_required( page, "ar-vert-test-1" )
        page.wait_for_timeout( 250 )
        in_pane = page.evaluate(
            """() => {
                const content = document.getElementById( 'action-required-content' );
                const body    = document.getElementById( 'content-pane-body' );
                return ( content && body ) ? ( content.parentNode === body ) : false;
            }"""
        )
        assert in_pane is False, "vertical mode must NOT move action-required into the pane"
