"""
E2E UI — focus-bar manager-lineage badge (Rick 2026-06-08).

A `voice_persona_assigned` event whose `payload.manager_persona` is set makes the
worker's focus-bar strip icon carry a `.cc-strip-manager-badge` (manager glyph +
initial, manager color). A worker with no manager (`manager_persona: null`) shows
none. Drives the real `handleNotificationUpdate` so the full client wiring (event →
managerPersonaMap → _addStripIcon render) is exercised in a live browser.

Venue: :8000 (scheduled monopolize-mode via /api/test-suite/submit).
"""

import pytest

from .conftest import BASE_URL


def _emit_persona( page, sender_id, session_id, manager_persona ):
    page.evaluate(
        """( args ) => {
            window.notificationsUI.handleNotificationUpdate( {
                notification: {
                    type          : 'voice_persona_assigned',
                    sender_id     : args.sender_id,
                    voice_persona : { name: 'Rio', color: '#28a745', icon: '🎙️' },
                    payload       : { session_id: args.session_id, manager_persona: args.manager_persona }
                }
            } );
        }""",
        { "sender_id": sender_id, "session_id": session_id, "manager_persona": manager_persona },
    )


class TestManagerBadgeStrip:

    def test_spawned_worker_shows_manager_badge( self, notifications_page ):
        page = notifications_page
        sid  = "claude.code@lupin.deepily.ai#wkbadge1"
        _emit_persona( page, sid, "wkbadge1",
                       { "icon": "👑", "initial": "T", "color": "#3F51B5", "name": "Tiberius" } )
        page.wait_for_timeout( 150 )

        info = page.evaluate(
            """( sender ) => {
                const icon = document.getElementById( window.notificationsUI._stripIconIdFor( sender ) );
                if ( !icon ) return null;
                const badge = icon.querySelector( '.cc-strip-manager-badge' );
                return {
                    hasManager: icon.getAttribute( 'data-has-manager' ),
                    badgeText : badge ? badge.textContent : null,
                    title     : badge ? badge.getAttribute( 'title' ) : null,
                };
            }""",
            sid,
        )
        assert info is not None, "worker strip icon must be created"
        assert info[ "hasManager" ] == "true"
        assert info[ "badgeText" ] == "👑T", "badge shows manager glyph + initial"
        assert info[ "title" ] == "Spawned by Tiberius"

    def test_root_worker_has_no_manager_badge( self, notifications_page ):
        page = notifications_page
        sid  = "claude.code@lupin.deepily.ai#rootbadge1"
        _emit_persona( page, sid, "rootbadge1", None )   # no manager
        page.wait_for_timeout( 150 )

        has_badge = page.evaluate(
            """( sender ) => {
                const icon = document.getElementById( window.notificationsUI._stripIconIdFor( sender ) );
                return icon ? !!icon.querySelector( '.cc-strip-manager-badge' ) : null;
            }""",
            sid,
        )
        assert has_badge is False, "root session (no manager) must show NO manager badge"
