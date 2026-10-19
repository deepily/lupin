"""
Unit tests for cosa.utils.stoppable_daemon.StoppableDaemonMixin.
"""

import threading

from cosa.utils.stoppable_daemon import StoppableDaemonMixin


class _Daemon( StoppableDaemonMixin ):
    """A minimal loop owner: an event, a thread slot and a loop that waits on the event."""

    def __init__( self ):
        self._stop_event = threading.Event()
        self._thread     = None

    def start( self ):
        self._thread = threading.Thread( target=self._stop_event.wait, daemon=True )
        self._thread.start()


def test_stop_before_start_sets_the_event_and_does_not_fail():
    daemon = _Daemon()
    daemon.stop()
    assert daemon._stop_event.is_set()


def test_stop_joins_a_live_thread():
    daemon = _Daemon()
    daemon.start()
    assert daemon._thread.is_alive()
    daemon.stop()
    assert not daemon._thread.is_alive()


def test_stop_is_idempotent_and_skips_the_join_for_a_dead_thread():
    daemon = _Daemon()
    daemon.start()
    daemon.stop()
    daemon.stop()
    assert daemon._stop_event.is_set()


def test_stop_passes_its_timeout_to_the_join():
    joined = []
    class _Thread:
        def is_alive( self ): return True
        def join( self, timeout ): joined.append( timeout )
    daemon         = _Daemon()
    daemon._thread = _Thread()
    daemon.stop( timeout=0.25 )
    daemon.stop()
    assert joined == [ 0.25, 5.0 ]
