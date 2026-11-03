"""
Legacy notifications: Keep place holds the scroll inside a session's notification history.

Requires:
    - The :8000 test container and the logged_in_page fixture.

Ensures:
    - Each sender card has date lists that scroll on their own, and a message from a card below the first raises it to the top.
    - The pinned test scrolls card A's history, raises A, and checks the history is still scrolled.
    - The control repeats the arrival with Keep place off and must see the history return to the top.
    - The cause was insertBefore, which detaches the card and resets every list inside it.
"""

import pytest

from .conftest import BASE_URL

KEEP_PLACE_KEY = "notifications_keep_place"
SENDER_A       = "claude.code@lupin.deepily.ai#0000a001"
SENDER_B       = "claude.code@lupin.deepily.ai#0000b002"
SCROLLED_TO    = 100

ARRIVE_JS = """
( args ) => {
    window.notificationsUI.addNotificationToSenderGroup( {
        sender_id : args.senderId, message : args.message, id : args.message, priority : "low",
        state : "delivered", timestamp : new Date( Date.now() + args.offsetMs ).toISOString()
    }, false );
}
"""

PANE_JS = """
( id ) => {
    const pane = document.getElementById( id ).querySelector( ".date-accordion-messages" );
    return { scrollTop : pane.scrollTop, scrollHeight : pane.scrollHeight, clientHeight : pane.clientHeight };
}
"""


def _card_id( sender_id ):
    return "sender-card-" + sender_id.replace( "@", "-" ).replace( ".", "-" ).replace( "#", "-" )


def _arrive( page, sender_id, message, offset_ms=0 ):
    page.evaluate( ARRIVE_JS, { "senderId": sender_id, "message": message, "offsetMs": offset_ms } )


def _first_card_id( page ):
    return page.evaluate( "() => document.querySelector( '#notifications-list > .sender-card' ).id" )


def _page_with_scrolled_history( logged_in_page, keep_place ):
    """
    Open the classic page with card A (long history, scrolled) below card B.

    Ensures:
        - Keep place is set in storage before the reload, so the client reads it at start
        - card B is first, card A's history pane scrolls and is scrolled to SCROLLED_TO
    """
    page = logged_in_page
    page.goto( f"{BASE_URL}/app/notifications?classic=1" )
    page.wait_for_load_state( "networkidle" )
    page.evaluate( f"() => localStorage.setItem( '{KEEP_PLACE_KEY}', '{ 'true' if keep_place else 'false' }' )" )
    page.reload()
    page.wait_for_load_state( "networkidle" )
    for index in range( 20 ):
        _arrive( page, SENDER_A, f"history-a-{index}", offset_ms=-200000 + index * 1000 )
    _arrive( page, SENDER_B, "history-b-0", offset_ms=-60000 )
    page.wait_for_timeout( 300 )
    assert _first_card_id( page ) == _card_id( SENDER_B ), "precondition: B's newer message puts B's card first"
    page.evaluate(
        "( args ) => { document.getElementById( args.id ).querySelector( '.date-accordion-messages' ).scrollTop = args.top; }",
        { "id": _card_id( SENDER_A ), "top": SCROLLED_TO }
    )
    before = page.evaluate( PANE_JS, _card_id( SENDER_A ) )
    assert before[ "scrollHeight" ] - before[ "clientHeight" ] > 150, f"precondition: A's history must scroll: {before}"
    assert before[ "scrollTop" ] == SCROLLED_TO, f"precondition: the history took the scroll: {before}"
    return page


class TestKeepPlaceHoldsTheHistoryPane:
    """A message that raises a card leaves its history where the reader put it."""

    def test_pinned_history_is_not_scrolled_to_the_top_by_new_notifications( self, logged_in_page ):
        page = _page_with_scrolled_history( logged_in_page, keep_place=True )
        for index in range( 3 ):
            _arrive( page, SENDER_A, f"history-a-new-{index}" )
            page.wait_for_timeout( 200 )
        assert _first_card_id( page ) == _card_id( SENDER_A ), "the arrivals should have raised A to the top"
        after = page.evaluate( PANE_JS, _card_id( SENDER_A ) )
        assert after[ "scrollTop" ] >= SCROLLED_TO, \
            f"the pinned history went back toward the top: {SCROLLED_TO} -> {after[ 'scrollTop' ]}"

    def test_control_unpinned_history_is_scrolled_to_the_top_by_the_same_arrivals( self, logged_in_page ):
        page = _page_with_scrolled_history( logged_in_page, keep_place=False )
        for index in range( 3 ):
            _arrive( page, SENDER_A, f"history-a-new-{index}" )
            page.wait_for_timeout( 200 )
        assert _first_card_id( page ) == _card_id( SENDER_A ), "the arrivals should have raised A to the top"
        after = page.evaluate( PANE_JS, _card_id( SENDER_A ) )
        assert after[ "scrollTop" ] == 0, \
            f"with Keep place off the history should go back to the top, got {after[ 'scrollTop' ]}"
