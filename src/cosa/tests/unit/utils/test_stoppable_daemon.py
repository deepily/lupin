"""
Unit tests for cosa.utils.stoppable_daemon.StoppableDaemonMixin, start and stop.
"""

import threading

import pytest

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


class _Bare( StoppableDaemonMixin ):
    """A class that takes both halves from the mixin."""

    THREAD_NAME = "BareThread"

    def __init__( self, enabled=True ):
        self.enabled     = enabled
        self._stop_event = threading.Event()
        self._thread     = None
        self.loops       = 0

    def _enabled( self ):
        return self.enabled

    def _loop( self ):
        self.loops += 1
        self._stop_event.wait()


class _GateOverride( _Bare ):
    """A class whose start gate is more than _enabled()."""

    def _should_start( self ):
        return True


class _NoName( StoppableDaemonMixin ):
    """A class that forgot THREAD_NAME."""

    def __init__( self ):
        self._stop_event = threading.Event()
        self._thread     = None

    def _enabled( self ):
        return True

    def _loop( self ):
        pass


def test_the_default_gate_is_enabled():
    assert _Bare( True )._should_start() is True
    assert _Bare( False )._should_start() is False


def test_start_runs_the_loop_on_a_named_daemon_thread_and_stop_ends_it():
    daemon = _Bare()
    assert daemon.start() is True
    assert daemon._thread.name == "BareThread" and daemon._thread.daemon is True
    daemon.stop( timeout=2 )
    assert not daemon._thread.is_alive() and daemon.loops == 1


def test_a_disabled_instance_never_spawns():
    daemon = _Bare( enabled=False )
    assert daemon.start() is False and daemon._thread is None


def test_a_second_start_while_alive_is_refused_and_a_dead_thread_does_not_block_one():
    daemon = _Bare()
    assert daemon.start() is True
    first = daemon._thread
    assert daemon.start() is False and daemon._thread is first
    daemon.stop( timeout=2 )
    assert daemon.start() is True and daemon._thread is not first
    daemon.stop( timeout=2 )


def test_an_overridden_gate_decides_instead_of_enabled():
    daemon = _GateOverride( enabled=False )
    try:
        assert daemon.start() is True
    finally:
        daemon.stop( timeout=2 )


def test_a_class_without_a_thread_name_fails_loudly_at_start():
    with pytest.raises( AttributeError ):
        _NoName().start()
