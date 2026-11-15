"""
Legacy notifications: Keep place holds the scroll inside a session's notification history.

Requires:
    - The :8000 test container and the logged_in_page fixture.

Ensures:
    - Each sender card has date lists that scroll on their own, and a message from a card below the first raises it to the top.
    - The pinned test scrolls card A's history, raises A, and checks the history is still scrolled.
    - The control repeats the arrival with Keep place off and must see the history return to the top.
    - The cause was insertBefore, which detaches the card and resets every list inside it.
    - Every message carries a fixed timestamp on one display-zone day, so the run never depends on the wall clock.
      The first version used "now" minus 200 seconds, and a run that crossed local midnight split the card into two
      date accordions and measured the one with 3 messages in it.
"""

from datetime import datetime, timedelta, timezone

from .conftest import BASE_URL

KEEP_PLACE_KEY = "notifications_keep_place"
SENDER_A       = "claude.code@lupin.deepily.ai#0000a001"
SENDER_B       = "claude.code@lupin.deepily.ai#0000b002"
SCROLLED_TO    = 100

# One fixed moment, 13:00 in New York on a day after the clock change (17:00Z), so a few minutes either way stay on one date.
BASE_TIME      = datetime( 2026, 3, 10, 17, 0, 0, tzinfo=timezone.utc )

ARRIVE_JS = """
( args ) => {
    window.notificationsUI.addNotificationToSenderGroup( {
        sender_id : args.senderId, message : args.message, id : args.message, priority : "low",
        state : "delivered", timestamp : args.timestamp
    }, false );
}
"""

DATE_ACCORDIONS_JS = """
( id ) => document.getElementById( id ).querySelectorAll( ".date-accordion-messages" ).length
"""

PANE_JS = """
( id ) => {
    const pane = document.getElementById( id ).querySelector( ".date-accordion-messages" );
    return { scrollTop : pane.scrollTop, scrollHeight : pane.scrollHeight, clientHeight : pane.clientHeight };
}
"""


def _card_id( sender_id ):
    return "sender-card-" + sender_id.replace( "@", "-" ).replace( ".", "-" ).replace( "#", "-" )


def _at( seconds ):
    """The timestamp `seconds` after BASE_TIME, as the ISO string the client reads."""
    return ( BASE_TIME + timedelta( seconds=seconds ) ).isoformat().replace( "+00:00", "Z" )


def _arrive( page, sender_id, message, at_seconds ):
    page.evaluate( ARRIVE_JS, { "senderId": sender_id, "message": message, "timestamp": _at( at_seconds ) } )


def _assert_one_date_accordion( page, sender_id, when ):
    """Guard: the card has one date accordion, so the measured pane holds the whole history."""
    count = page.evaluate( DATE_ACCORDIONS_JS, _card_id( sender_id ) )
    assert count == 1, f"{when}: the card has {count} date accordions, so the seeded and the new messages fell on different days"


def _first_card_id( page ):
    return page.evaluate( "() => document.querySelector( '#notifications-list > .sender-card' ).id" )


def _page_with_scrolled_history( logged_in_page, keep_place, clock_at=None ):
    """
    Open the classic page with card A (long history, scrolled) below card B.

    Ensures:
        - Keep place is set in storage before the reload, so the client reads it at start
        - card B is first, card A's history pane scrolls and is scrolled to SCROLLED_TO
        - clock_at, when given, is the page's clock for the whole test; it keeps running from that moment
    """
    page = logged_in_page
    if clock_at is not None: page.clock.install( time=clock_at )
    page.goto( f"{BASE_URL}/app/notifications?classic=1" )
    page.wait_for_load_state( "networkidle" )
    page.evaluate( f"() => localStorage.setItem( '{KEEP_PLACE_KEY}', '{ 'true' if keep_place else 'false' }' )" )
    page.reload()
    page.wait_for_load_state( "networkidle" )
    for index in range( 20 ):
        _arrive( page, SENDER_A, f"history-a-{index}", index )
    _arrive( page, SENDER_B, "history-b-0", 60 )
    _assert_one_date_accordion( page, SENDER_A, "after seeding" )
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
            _arrive( page, SENDER_A, f"history-a-new-{index}", 120 + index )
            page.wait_for_timeout( 200 )
        assert _first_card_id( page ) == _card_id( SENDER_A ), "the arrivals should have raised A to the top"
        _assert_one_date_accordion( page, SENDER_A, "after the arrivals" )
        after = page.evaluate( PANE_JS, _card_id( SENDER_A ) )
        assert after[ "scrollTop" ] >= SCROLLED_TO, \
            f"the pinned history went back toward the top: {SCROLLED_TO} -> {after[ 'scrollTop' ]}"

    def test_control_unpinned_history_is_scrolled_to_the_top_by_the_same_arrivals( self, logged_in_page ):
        page = _page_with_scrolled_history( logged_in_page, keep_place=False )
        for index in range( 3 ):
            _arrive( page, SENDER_A, f"history-a-new-{index}", 120 + index )
            page.wait_for_timeout( 200 )
        assert _first_card_id( page ) == _card_id( SENDER_A ), "the arrivals should have raised A to the top"
        _assert_one_date_accordion( page, SENDER_A, "after the arrivals" )
        after = page.evaluate( PANE_JS, _card_id( SENDER_A ) )
        assert after[ "scrollTop" ] == 0, \
            f"with Keep place off the history should go back to the top, got {after[ 'scrollTop' ]}"

    def test_the_pinned_history_holds_when_the_page_clock_sits_just_before_midnight( self, logged_in_page ):
        """
        The page clock is set to 23:59:50 New York time and keeps running through midnight.

        The run that failed had crossed local midnight.
        The fixed timestamps keep every message on one date.
        """
        page = _page_with_scrolled_history( logged_in_page, keep_place=True, clock_at=datetime( 2026, 3, 11, 3, 59, 50, tzinfo=timezone.utc ) )
        for index in range( 3 ):
            _arrive( page, SENDER_A, f"history-a-new-{index}", 120 + index )
            page.wait_for_timeout( 200 )
        _assert_one_date_accordion( page, SENDER_A, "after the arrivals" )
        after = page.evaluate( PANE_JS, _card_id( SENDER_A ) )
        assert after[ "scrollTop" ] >= SCROLLED_TO, f"the pinned history went back toward the top: {SCROLLED_TO} -> {after[ 'scrollTop' ]}"
