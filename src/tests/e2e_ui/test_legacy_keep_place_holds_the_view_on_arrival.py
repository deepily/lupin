"""
Legacy notifications: Keep place holds the view when a notification arrives.

Requires:
    - The :8000 test container and the logged_in_page fixture.

Ensures:
    - Each test scrolls to the middle of a tall list and lets one notification arrive.
    - It then compares where the watched card sits in the viewport, not window.scrollY.
    - Scroll anchoring may change scrollY to hold the card still, so the card is what counts.
    - The control test repeats the arrival with Keep place off and must see a jump.
"""

import uuid

import pytest

from .conftest import BASE_URL

KEEP_PLACE_KEY = "notifications_keep_place"
SENDER_COUNT   = 8

SEED_AND_ARRIVE_JS = """
( args ) => {
    const ui = window.notificationsUI;
    ui.addNotificationToSenderGroup( {
        sender_id : args.senderId, message : args.message, id : args.message, priority : "low",
        state : "delivered", timestamp : new Date( Date.now() + args.offsetMs ).toISOString()
    }, false );
}
"""


@pytest.fixture( scope="function" )
def tall_list_page( logged_in_page ):
    """
    The classic notifications page with tall sender cards, scrolled to the middle of the list.

    Ensures:
        - Keep place is on before the page is reloaded, so the client reads it from storage
        - the page is scrolled well away from the top
    """
    page = logged_in_page
    page.goto( f"{BASE_URL}/app/notifications?classic=1" )
    page.wait_for_load_state( "networkidle" )
    page.evaluate( f"() => localStorage.setItem( '{KEEP_PLACE_KEY}', 'true' )" )
    page.reload()
    page.wait_for_load_state( "networkidle" )
    page.add_style_tag( content="#notifications-list > .sender-card { min-height: 420px; }" )
    for index in range( SENDER_COUNT ):
        _arrive( page, _sender( index ), f"seed-{index}", offset_ms=-100000 + index * 1000 )
    page.wait_for_timeout( 300 )
    page.evaluate(
        "( id ) => window.scrollTo( 0, document.getElementById( id ).getBoundingClientRect().top + scrollY - 150 )",
        "sender-card-" + _sender( SENDER_COUNT // 2 ).replace( "@", "-" ).replace( ".", "-" ).replace( "#", "-" )
    )
    page.wait_for_timeout( 300 )
    assert page.evaluate( "() => window.scrollY" ) > 1000, "the page did not scroll away from the top"
    assert 0 < _watched_top( page ) < 900, "the watched card is not in view"
    return page


def _watched_top( page ):
    """Viewport top of the card in the middle of the list, the one the reader is looking at."""
    sanitized = _sender( SENDER_COUNT // 2 ).replace( "@", "-" ).replace( ".", "-" ).replace( "#", "-" )
    return page.evaluate(
        "( id ) => document.getElementById( id ).getBoundingClientRect().top", f"sender-card-{sanitized}"
    )


def _sender( index ):
    return f"claude.code@lupin.deepily.ai#{0x3000 + index:08x}"


def _arrive( page, sender_id, message, offset_ms=0 ):
    page.evaluate( SEED_AND_ARRIVE_JS, { "senderId": sender_id, "message": message, "offsetMs": offset_ms } )


def _arrive_action_required( page ):
    page.evaluate(
        """( id ) => window.notificationsUI.addActionRequiredNotification( {
            id : id, sender_id : "claude.code@lupin.deepily.ai#00003000", message : "Proceed?",
            response_type : "yes_no", response_default : "yes", timeout_seconds : 600,
            priority : "high", type : "custom", timestamp : new Date().toISOString()
        } )""",
        f"kp-ar-{uuid.uuid4().hex}"
    )
    page.wait_for_timeout( 1500 )                          # the section scroll fires after 50ms and is smooth


class TestKeepPlaceHoldsTheViewOnArrival:
    """With Keep place on, an arrival leaves the watched card where it was."""

    def test_an_ordinary_notification_does_not_move_the_view( self, tall_list_page ):
        page   = tall_list_page
        before = _watched_top( page )
        _arrive( page, _sender( SENDER_COUNT - 1 ), "kp-ordinary-arrival" )
        page.wait_for_timeout( 1000 )
        assert _watched_top( page ) == pytest.approx( before, abs=2 ), \
            "an ordinary notification moved the view while Keep place was on"

    def test_an_action_required_notification_does_not_move_the_view( self, tall_list_page ):
        page   = tall_list_page
        before = _watched_top( page )
        _arrive_action_required( page )
        assert page.locator( "#action-required-section .action-required-notification" ).count() == 1, \
            "the action-required card did not arrive"
        assert _watched_top( page ) == pytest.approx( before, abs=2 ), \
            "an action-required notification moved the view while Keep place was on"

    def test_control_with_keep_place_off_an_action_required_notification_moves_the_view( self, tall_list_page ):
        page = tall_list_page
        page.evaluate( "() => window.notificationsUI._setKeepPlace( false )" )
        before = _watched_top( page )
        _arrive_action_required( page )
        assert abs( _watched_top( page ) - before ) > 200, \
            "with Keep place off the arrival should have scrolled to the action-required section"
