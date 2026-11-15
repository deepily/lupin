"""
E2E UI: the legacy client and a quiet worker's priorities.

A quiet worker's notifications carry `worker_quiet: true`. The legacy client lowers its
`high` to `medium` and keeps the ding. Its `urgent` is untouched, so it still queues for speech.
A manager that Rick quieted by hand has no stamp, so its `urgent` is lowered as before.
Each test drives the real `handleNotificationUpdate`, replacing only the two outputs
(the ding and the speech queue) with recorders.

Venue: :8000 (scheduled monopolize-mode via /api/v2/submit).
"""

import pytest

from .conftest import BASE_URL

WORKER  = "claude.code@lupin.deepily.ai#quietwk1"
MANAGER = "claude.code@lupin.deepily.ai#quietmg1"

RECORD_JS = """
    () => {
        const ui = window.notificationsUI;
        window.__dings  = [];
        window.__spoken = [];
        ui.playNotificationSoundByPriority = async ( p ) => { window.__dings.push( p ); };
        ui.addToTTSQueue                   = ( item ) => { window.__spoken.push( item.notification && item.notification.priority ); };
    }
"""

SEND_JS = """
    ( args ) => {
        window.__dings.length  = 0;
        window.__spoken.length = 0;
        return window.notificationsUI.handleNotificationUpdate( { notification: {
            id_hash   : args.id,
            type      : 'task',
            sender_id : args.sender,
            message   : 'hello from ' + args.sender,
            priority  : args.priority,
            timestamp : new Date().toISOString(),
            ...( args.quiet ? { worker_quiet: true } : {} )
        } } ).then( () => ( { dings: window.__dings.slice(), spoken: window.__spoken.slice() } ) );
    }
"""


def _send( page, sender, priority, quiet ):
    result = page.evaluate( SEND_JS, { "id": f"q-{sender[-3:]}-{priority}-{int( quiet )}", "sender": sender, "priority": priority, "quiet": quiet } )
    page.wait_for_timeout( 450 )  # the speech queue is fed after a 300 ms settle for the ding
    return page.evaluate( "() => ( { dings: window.__dings.slice(), spoken: window.__spoken.slice() } )" ) if result is None else result


@pytest.fixture
def recorded_page( notifications_page ):
    notifications_page.evaluate( RECORD_JS )
    return notifications_page


class TestQuietWorkerPriorities:

    def test_medium_is_never_spoken( self, recorded_page ):
        out = _send( recorded_page, WORKER, "medium", True )
        assert out[ "spoken" ] == []

    def test_high_from_a_quiet_worker_dings_as_medium_and_is_not_spoken( self, recorded_page ):
        out = _send( recorded_page, WORKER, "high", True )
        assert out[ "spoken" ] == [], "a quiet worker's high must not reach the speech queue"
        assert out[ "dings" ] == [ "medium" ], "the ding is kept, at medium"

    def test_urgent_from_a_quiet_worker_still_speaks( self, recorded_page ):
        out = _send( recorded_page, WORKER, "urgent", True )
        assert out[ "spoken" ] == [ "urgent" ], "Rick's rule: a quiet worker's urgent notify speaks"
        assert out[ "dings" ] == [ "urgent" ]

    def test_the_stamp_makes_the_card_and_strip_icon_quiet( self, recorded_page ):
        _send( recorded_page, WORKER, "medium", True )
        mode = recorded_page.evaluate( "() => window.notificationsUI.conversationModes[ 'quietwk1' ]" )
        assert mode is False

    def test_a_high_without_the_stamp_speaks_as_before( self, recorded_page ):
        out = _send( recorded_page, "claude.code@lupin.deepily.ai#loudwk01", "high", False )
        assert out[ "spoken" ] == [ "high" ]

    def test_a_manager_quieted_by_hand_has_its_urgent_lowered( self, recorded_page ):
        """Maria's pin: no stamp, stored quiet, so urgent is rewritten to medium as before."""
        recorded_page.evaluate( "() => window.notificationsUI._setConversationModeLocal( 'quietmg1', false )" )
        out = _send( recorded_page, MANAGER, "urgent", False )
        assert out[ "spoken" ] == []
        assert out[ "dings" ] == [ "medium" ]
