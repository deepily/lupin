"""
Legacy notifications: the Keep place toggle looks like the Active toggle, on and off.

Requires:
    - The :8000 test container and the logged_in_page fixture.

Ensures:
    - A click flips data-keep-place and aria-checked on the toggle.
    - On, the toggle's computed background is the Active toggle's on background.
    - Off, the toggle has the same background as the Active toggle when it is off.
    - Snapshots of the toggles row, on and off.
"""

import pytest

from .conftest import BASE_URL

SENDER_ID = "claude.code@lupin.deepily.ai#0000c002"
KEEP_ID   = "cc-keep-place-toggle"
ACTIVE_ID = "cc-hide-inactive-toggle"

SEED_JS = """
( args ) => {
    const ui = window.notificationsUI;
    ui.senderGroups.set( args.senderId, {
        senderId : args.senderId, project : "lupin", sessionHash : "0000c002", isActive : true,
        totalCount : 0, dateGroups : new Map(), lastActivity : new Date().toISOString()
    } );
    ui.createSenderCard( args.senderId, true );
}
"""

STATE_JS  = "( id ) => { const el = document.getElementById( id ); return { keep : el.getAttribute( 'data-keep-place' ), checked : el.getAttribute( 'aria-checked' ) }; }"
ATTR_JS   = "( [ id, name ] ) => document.getElementById( id ).getAttribute( name )"
COLOUR_JS = "( id ) => getComputedStyle( document.getElementById( id ) ).backgroundColor"


@pytest.fixture( scope="function" )
def strip_page( logged_in_page ):
    """The classic page with one session card, so the focus bar is showing."""
    page = logged_in_page
    page.goto( f"{BASE_URL}/app/notifications?classic=1" )
    page.wait_for_load_state( "networkidle" )
    page.evaluate( SEED_JS, { "senderId": SENDER_ID } )
    page.wait_for_selector( "#cc-session-strip:not([hidden])", timeout=5_000 )
    page.wait_for_selector( "#cc-strip-icons .cc-strip-icon", timeout=5_000 )
    return page


def _set( page, toggle_id: str, attribute: str, on: bool ):
    """Click the toggle until it reads the wanted state, then move the mouse away."""
    if ( page.evaluate( ATTR_JS, [ toggle_id, attribute ] ) == "true" ) != on:
        page.click( f"#{ toggle_id }" )
    page.mouse.move( 0, 0 )
    page.wait_for_function( f"() => document.getElementById( '{ toggle_id }' ).getAttribute( '{ attribute }' ) === '{ str( on ).lower() }'" )
    page.wait_for_timeout( 400 )


class TestKeepPlaceToggleStyle:
    """The Keep place pill reads on and off the way the Active pill does."""

    def test_a_click_flips_the_attribute_and_aria_checked( self, strip_page ):
        _set( strip_page, KEEP_ID, "data-keep-place", False )
        assert strip_page.evaluate( STATE_JS, KEEP_ID ) == { "keep": "false", "checked": "false" }
        strip_page.click( f"#{KEEP_ID}" )
        assert strip_page.evaluate( STATE_JS, KEEP_ID ) == { "keep": "true", "checked": "true" }
        strip_page.click( f"#{KEEP_ID}" )
        assert strip_page.evaluate( STATE_JS, KEEP_ID ) == { "keep": "false", "checked": "false" }

    def test_keep_place_on_has_the_active_toggles_on_background( self, strip_page ):
        page = strip_page
        _set( page, KEEP_ID, "data-keep-place", False )
        _set( page, ACTIVE_ID, "data-hide-inactive", False )
        keep_off, active_off = page.evaluate( COLOUR_JS, KEEP_ID ), page.evaluate( COLOUR_JS, ACTIVE_ID )
        _set( page, KEEP_ID, "data-keep-place", True )
        _set( page, ACTIVE_ID, "data-hide-inactive", True )
        keep_on, active_on = page.evaluate( COLOUR_JS, KEEP_ID ), page.evaluate( COLOUR_JS, ACTIVE_ID )
        assert keep_off == active_off, f"off: keep {keep_off} vs active {active_off}"
        assert keep_on == active_on, f"on: keep {keep_on} vs active {active_on}"
        assert keep_on != keep_off, f"Keep place looks the same on and off: {keep_on}"

    @pytest.mark.parametrize( "state", [ "off", "on" ] )
    def test_toggles_row_visual( self, strip_page, assert_snapshot, state ):
        _set( strip_page, KEEP_ID, "data-keep-place", state == "on" )
        assert_snapshot( strip_page.locator( "#cc-strip-toggles" ), name=f"legacy_toggles_row_keep_place_{state}.png" )
