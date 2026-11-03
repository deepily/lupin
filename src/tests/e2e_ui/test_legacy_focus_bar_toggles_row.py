"""
Legacy notifications: the Focus, All and Keep place toggles have a row of their own.

Requires:
    - The :8000 test container and the logged_in_page fixture.

Ensures:
    - The three toggles share one row inside the focus bar.
    - That row sits below the persona badges, inside the focus bar.
"""

import pytest

from .conftest import BASE_URL

SENDER_ID = "claude.code@lupin.deepily.ai#0000c001"

TOGGLE_IDS = [ "cc-strip-toggle", "cc-hide-inactive-toggle", "cc-keep-place-toggle" ]

SEED_JS = """
( args ) => {
    const ui = window.notificationsUI;
    ui.senderGroups.set( args.senderId, {
        senderId : args.senderId, project : "lupin", sessionHash : "0000c001", isActive : true,
        totalCount : 0, dateGroups : new Map(), lastActivity : new Date().toISOString()
    } );
    ui.createSenderCard( args.senderId, true );
}
"""

GEOMETRY_JS = """
( ids ) => {
    const box = ( el ) => { const r = el.getBoundingClientRect(); return { top : r.top, bottom : r.bottom, left : r.left, right : r.right }; };
    return {
        icons   : box( document.getElementById( "cc-strip-icons" ) ),
        row     : box( document.getElementById( "cc-strip-toggles" ) ),
        strip   : box( document.getElementById( "cc-session-strip" ) ),
        toggles : ids.map( ( id ) => ( { id : id, parent : document.getElementById( id ).parentElement.id, ...box( document.getElementById( id ) ) } ) )
    };
}
"""


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


class TestFocusBarTogglesRow:
    """The toggles have a row of their own."""

    def test_toggles_sit_on_their_own_row_below_the_badges( self, strip_page ):
        geo = strip_page.evaluate( GEOMETRY_JS, TOGGLE_IDS )
        assert [ t[ "id" ] for t in geo[ "toggles" ] ] == TOGGLE_IDS
        for toggle in geo[ "toggles" ]:
            assert toggle[ "parent" ] == "cc-strip-toggles", f"{toggle[ 'id' ]} is not in the toggles row"
            assert toggle[ "top" ] >= geo[ "icons" ][ "bottom" ] - 1, f"{toggle[ 'id' ]} is not below the badges: {geo}"
        assert geo[ "row" ][ "top" ] >= geo[ "icons" ][ "bottom" ] - 1, f"the toggles row overlaps the badge row: {geo}"

    def test_the_three_toggles_share_one_line_inside_the_focus_bar( self, strip_page ):
        geo  = strip_page.evaluate( GEOMETRY_JS, TOGGLE_IDS )
        tops = [ t[ "top" ] for t in geo[ "toggles" ] ]
        assert max( tops ) - min( tops ) < 2, f"the toggles are not on one line: {tops}"
        assert geo[ "row" ][ "bottom" ] <= geo[ "strip" ][ "bottom" ] + 1, "the toggles row spills out of the focus bar"
