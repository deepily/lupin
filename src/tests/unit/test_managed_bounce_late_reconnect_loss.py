"""
Item 3 of the R5 acceptance bar: the late reconnector gets NOTHING, and is NAMED.

THE CLAIM UNDER TEST, in one sentence: a session that reconnects AFTER the
all-clear has fired receives no live push AND no durable entry — and that loss
is recorded by name rather than as a bare count.

WHY THIS IS A GATE AND NOT A LIVE E2E. The loss half has been observed twice on
real traffic (both `:8000` boots named nine sessions that never rejoined), but
observation is not assertion: tonight's `:7999` bounce fired on plateau and
missed nobody, so the naming branch did not run at all. A claim that only holds
when the fleet happens to be slow is not gated. Expressing "reconnects later" as
"absent from the fire-time snapshot" makes it deterministic — that is precisely
what late means to `perform_fanout`, which iterates the snapshot it was handed.

WHY BOTH HALVES LIVE IN ONE FILE. "The straggler gets nothing" and "the straggler
is named" are only safe TOGETHER. Straggler coverage is deliberately absent —
replay-on-connect is barred (`src/rnd/v0.1.9/2026.07.28-…-durable-notify-path.md`
line 6: "This plan is not to be executed, DO NOT implement"), so the loss is
accepted BY DESIGN. An accepted loss that stops being visible is just a loss.

THE CONTROL is `test_a_session_present_at_fire_time_is_delivered_and_not_named`:
the same machinery with the straggler PRESENT must deliver to it and name nobody.
Without that arm, a fanout that silently wrote nothing for anyone would satisfy
every assertion below.
"""

import unittest

from cosa.rest.managed_bounce_broadcast import missed_sessions
from cosa.rest.routers.commons import perform_fanout


ROSTER  = [ "sess-alpha", "sess-bravo", "sess-late" ]   # bridge files — who we EXPECT back
BACK_AT_FIRE = [ "sess-alpha", "sess-bravo" ]           # live sockets when the gate opened


class _RecordingStore:
    """Captures `broadcasts` posts so the per-recipient entries can be inspected."""

    def __init__( self ):
        self.posts = [ ]

    def post( self, **kwargs ):
        self.posts.append( kwargs )

    def targets( self ):
        return [ p[ "metadata" ][ "target_session_id" ] for p in self.posts ]


class _RecordingQueue:
    """Captures live pushes so 'reached nobody' can be distinguished from 'reached'."""

    def __init__( self ):
        self.pushes = [ ]

    def push_notification( self, **kwargs ):
        self.pushes.append( kwargs )

    def job_ids( self ):
        return [ p[ "job_id" ] for p in self.pushes ]


def _sessions( ids ):
    return [ { "session_id": sid } for sid in ids ]


def _fire( present_ids ):
    """Run one all-clear fanout against the sessions live at fire time."""
    store, queue = _RecordingStore(), _RecordingQueue()
    successful, failed = perform_fanout(
        broadcast_id       = "bc-item3",
        message            = "✅ :7999 is back up — boot #1.",
        sessions           = _sessions( present_ids ),
        sender_user_id     = "claude.code@lupin.deepily.ai",
        store              = store,
        notification_queue = queue,
        build_sender_id    = lambda sid: f"sender::{sid}",
    )
    return store, queue, successful, failed


class LateReconnectLossTests( unittest.TestCase ):

    def test_a_session_that_reconnects_after_the_fire_gets_nothing_and_is_named( self ):
        store, queue, successful, failed = _fire( BACK_AT_FIRE )

        # HALF ONE — the loss. No durable entry and no live push addressed to the
        # straggler. `perform_fanout` writes one broadcasts row per recipient in
        # the snapshot it was given, so a session absent then has no row at all —
        # there is nothing for a later reconnect to pick up.
        self.assertNotIn( "sess-late", store.targets() )
        self.assertNotIn( "sess-late"[ :8 ], queue.job_ids() )
        self.assertEqual( successful, 2 )
        self.assertEqual( failed, [ ] )

        # The two that were back DID get both halves — proving the absence above
        # is specific to the straggler, not a fanout that did nothing.
        self.assertEqual( sorted( store.targets() ), [ "sess-alpha", "sess-bravo" ] )

        # HALF TWO — the visibility. Roster minus live sockets names the straggler.
        self.assertEqual( missed_sessions( ROSTER, BACK_AT_FIRE ), [ "sess-late" ] )

    def test_a_session_present_at_fire_time_is_delivered_and_not_named( self ):
        """The control. With the straggler back in time, both assertions must invert."""
        store, queue, successful, failed = _fire( ROSTER )

        self.assertIn( "sess-late", store.targets() )
        self.assertIn( "sess-late"[ :8 ], queue.job_ids() )
        self.assertEqual( successful, 3 )
        self.assertEqual( failed, [ ] )

        self.assertEqual( missed_sessions( ROSTER, ROSTER ), [ ] )

    def test_the_named_loss_lists_every_straggler_not_just_the_first( self ):
        """
        A bare count was the thing Rio's requirement replaced.

        Nine sessions were named on the `:8000` boot; a naming path that reported
        only one of them would have read as almost-fine.
        """
        roster  = [ "s-1", "s-2", "s-3", "s-4" ]
        present = [ "s-2" ]

        self.assertEqual( missed_sessions( roster, present ), [ "s-1", "s-3", "s-4" ] )

    def test_a_straggler_is_not_resurrected_by_a_second_fanout( self ):
        """
        No re-fire: a later fanout does not retroactively address the earlier one.

        Guards the accepted-loss boundary from the obvious "just send it again"
        repair, which would be replay-on-connect wearing a different hat.
        """
        first_store,  _, _, _ = _fire( BACK_AT_FIRE )
        second_store, _, _, _ = _fire( ROSTER )

        # The FIRST broadcast's entries never gain the straggler retroactively.
        self.assertNotIn( "sess-late", first_store.targets() )
        # A genuinely new fanout is a different broadcast, not a repair of the old one.
        self.assertIn( "sess-late", second_store.targets() )


if __name__ == "__main__":
    unittest.main()
