"""
E2E UI — multiplexer section-toolbar + per-accordion collapse (2026-06-23,
Rachel 🕊️ / Mr. Radio lane).

Exercises the carbon-copy of the legacy `#section-toolbar` END-TO-END against
the real boot.ts wiring:

  - collapse-all / expand-all flip EVERY accordion (sender cards + date
    accordions);
  - each per-section visibility toggle hides/shows its target section pane;
  - per-accordion header click collapses/expands a single accordion;
  - a persistence ROUND-TRIP: collapse → reload → state restored from
    localStorage (ViewStateStore).

Notifications are seeded via the boot test hook
`window.__multiplexerTestHook.eventBus.emit(notification_queue_update)` (same
mechanism as the phase-5 smoke), so sender cards + date accordions render
without a live producer. The toolbar buttons + accordion headers are then
clicked through their REAL delegated handlers.

Venue: :8000 (scheduled monopolize-mode via /api/test-suite/submit). NEVER run
side-door (ad-hoc curl / direct queue push / in-process). Submit via:

    POST /api/test-suite/submit
    {
        "test_types"         : "e2e_ui",
        "pytest_args"        : "-k test_multiplexer_section_toolbar",
        "scheduled_at"       : "<verified-idle or post-queued slot>",
        "auto_fix_on_failure": false
    }
"""

from __future__ import annotations

from .conftest import BASE_URL


# notification_queue_update injector (mirrors phase-5 smoke _INJECT_JS).
_INJECT_JS = """
( fixture ) => {
    const hook = window.__multiplexerTestHook;
    if ( !hook || !hook.eventBus ) {
        throw new Error( "test hook not present — boot.ts test surface missing" );
    }
    hook.eventBus.emit( {
        type    : 'notification_queue_update',
        payload : { queue_name: 'notification', value: 1, notification: fixture },
        source  : 'section-toolbar-e2e',
        ts      : Date.now(),
    } );
    return true;
}
"""


def _open_multiplexer( page ):
    """Navigate to the multiplexer + wait for the boot test hook + the toolbar."""
    page.goto( f"{BASE_URL}/app/multiplexer" )
    page.wait_for_load_state( "networkidle" )
    page.wait_for_function(
        "() => window.__multiplexerTestHook"
        " && window.__multiplexerTestHook.eventBus"
        " && window.__multiplexerTestHook.stores"
        " && window.__multiplexerTestHook.stores.viewState",
        timeout=15000,
    )
    # The section-toolbar mounts at boot.
    page.wait_for_selector( "#section-toolbar", timeout=5000 )


def _seed_two_senders( page ):
    """Inject two plain notifications under distinct senders → two sender cards,
    each with a single date accordion."""
    page.evaluate( _INJECT_JS, {
        "id_hash"   : "stb_a",
        "sender_id" : "stb_sender_a",
        "message"   : "alpha body",
        "timestamp" : "2026-06-23T14:07:00Z",
    } )
    page.evaluate( _INJECT_JS, {
        "id_hash"   : "stb_b",
        "sender_id" : "stb_sender_b",
        "message"   : "beta body",
        "timestamp" : "2026-06-23T14:09:00Z",
    } )
    page.wait_for_selector(
        '[data-testid="multiplexer-sender-cards"] [data-id-hash="stb_sender_a"]',
        timeout=3000,
    )
    page.wait_for_selector(
        '[data-testid="multiplexer-sender-cards"] [data-id-hash="stb_sender_b"]',
        timeout=3000,
    )


class TestMultiplexerSectionToolbar:
    """The mux section-toolbar carbon-copy + per-accordion collapse, end-to-end."""

    def test_toolbar_and_section_toggles_present( self, logged_in_page ):
        page = logged_in_page
        _open_multiplexer( page )
        # Collapse-all + expand-all controls.
        assert page.locator( "#section-toolbar-collapse-all" ).count() == 1
        assert page.locator( "#section-toolbar-expand-all" ).count() == 1
        # Six per-section visibility toggles.
        assert page.locator( "#section-toolbar .toolbar-btn" ).count() == 6
        # The layout-mode ⇆ is NOT duplicated into the section-toolbar.
        assert page.locator( "#section-toolbar .layout-mode-btn" ).count() == 0

    def test_section_visibility_toggle_hides_and_shows_pane( self, logged_in_page ):
        page = logged_in_page
        _open_multiplexer( page )
        jobs_btn  = page.locator( '#section-toolbar .toolbar-btn[data-section="jobs-pane"]' )
        jobs_pane = page.locator( "#jobs-pane" )
        assert jobs_pane.is_visible()

        jobs_btn.click()
        page.wait_for_timeout( 80 )
        assert not jobs_pane.is_visible(), "jobs-pane should be hidden after toggle off"
        assert "section-hidden" in ( jobs_pane.get_attribute( "class" ) or "" )

        jobs_btn.click()
        page.wait_for_timeout( 80 )
        assert jobs_pane.is_visible(), "jobs-pane should be visible after toggle on"

    def test_per_accordion_header_click_collapses_one_accordion( self, logged_in_page ):
        page = logged_in_page
        _open_multiplexer( page )
        _seed_two_senders( page )

        card_a   = page.locator( '.sender-card[data-sender-id="stb_sender_a"]' )
        header_a = card_a.locator( ".sender-card-header" )
        assert card_a.get_attribute( "data-collapsed" ) in ( "false", None )

        header_a.click()
        page.wait_for_timeout( 80 )
        assert card_a.get_attribute( "data-collapsed" ) == "true"
        # The dates region is hidden when the card is collapsed.
        assert not card_a.locator( ".sender-card-dates" ).is_visible()

        header_a.click()
        page.wait_for_timeout( 80 )
        assert card_a.get_attribute( "data-collapsed" ) == "false"

    def test_collapse_all_then_expand_all( self, logged_in_page ):
        page = logged_in_page
        _open_multiplexer( page )
        _seed_two_senders( page )

        page.locator( "#section-toolbar-collapse-all" ).click()
        page.wait_for_timeout( 100 )
        collapsed = page.eval_on_selector_all(
            ".sender-card",
            "els => els.every( e => e.getAttribute( 'data-collapsed' ) === 'true' )",
        )
        assert collapsed, "collapse-all must collapse every sender card"
        date_collapsed = page.eval_on_selector_all(
            ".date-accordion",
            "els => els.every( e => e.getAttribute( 'data-collapsed' ) === 'true' )",
        )
        assert date_collapsed, "collapse-all must collapse every date accordion"

        page.locator( "#section-toolbar-expand-all" ).click()
        page.wait_for_timeout( 100 )
        expanded = page.eval_on_selector_all(
            ".sender-card",
            "els => els.every( e => e.getAttribute( 'data-collapsed' ) === 'false' )",
        )
        assert expanded, "expand-all must expand every sender card"

    def test_collapse_persists_across_reload( self, logged_in_page ):
        page = logged_in_page
        _open_multiplexer( page )
        _seed_two_senders( page )

        # Collapse sender A via its header.
        page.locator( '.sender-card[data-sender-id="stb_sender_a"] .sender-card-header' ).click()
        page.wait_for_timeout( 80 )
        assert page.locator( '.sender-card[data-sender-id="stb_sender_a"]' ).get_attribute( "data-collapsed" ) == "true"

        # Reload + re-seed the same senders; the persisted collapse must re-apply.
        page.reload()
        page.wait_for_load_state( "networkidle" )
        page.wait_for_function(
            "() => window.__multiplexerTestHook && window.__multiplexerTestHook.stores"
            " && window.__multiplexerTestHook.stores.viewState",
            timeout=15000,
        )
        _seed_two_senders( page )
        page.wait_for_timeout( 120 )
        assert page.locator( '.sender-card[data-sender-id="stb_sender_a"]' ).get_attribute( "data-collapsed" ) == "true", \
            "collapse state must survive a reload (ViewStateStore persistence)"
        # Sender B, never collapsed, stays expanded.
        assert page.locator( '.sender-card[data-sender-id="stb_sender_b"]' ).get_attribute( "data-collapsed" ) == "false"
