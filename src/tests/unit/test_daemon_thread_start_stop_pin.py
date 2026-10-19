"""
Pins start() and stop() on the four daemon-thread classes.

The classes are TurnAgeWatchdog, FollowThroughEscalationWatcher, TaskChaseConsumer and SelfRespinObserverLoop.
Their loop bodies are replaced by a wait on the stop event, so no thread does real work.
"""

import threading

import pytest

from cosa.agents.heartbeat_arbiter.self_respin_observer import SelfRespinObserverLoop
from cosa.agents.heartbeat_arbiter.turn_age_watchdog import TurnAgeWatchdog
from cosa.rest.follow_through_escalation_watcher import FollowThroughEscalationWatcher
from cosa.rest.task_chase_consumer import TaskChaseConsumer


class Cfg:
    """A config manager answering from a dict, with the real .get() signature."""

    def __init__( self, values ):
        self.values = values

    def get( self, key, default=None, return_type=None ):
        return self.values.get( key, default )


class FakeThread:
    """A thread stand-in that records the join timeout."""

    def __init__( self, alive ):
        self.alive   = alive
        self.joined  = []

    def is_alive( self ):
        return self.alive

    def join( self, timeout=None ):
        self.joined.append( timeout )


# class, enabled key, thread name
SPECS = [
    ( TurnAgeWatchdog,                "arbiter turn age watchdog enabled",   "TurnAgeWatchdog" ),
    ( FollowThroughEscalationWatcher, "follow through escalation enabled",   "FollowThroughEscalationWatcher" ),
    ( TaskChaseConsumer,              "task store chase enabled",            "TaskChaseConsumer" ),
    ( SelfRespinObserverLoop,         "arbiter self respin observer enabled", "SelfRespinObserverLoop" ),
]


def build( cls, enabled ):
    key  = next( k for c, k, _ in SPECS if c is cls )
    cfg  = Cfg( { key: enabled } )
    if cls is SelfRespinObserverLoop:
        cfg.values[ "stale mcp check delivery enabled" ] = False
    obj = cls( cfg )
    obj._loop = lambda: obj._stop_event.wait()
    return obj


@pytest.fixture( autouse=True )
def stop_every_thread():
    started = []
    yield started
    for obj in started:
        obj.stop( timeout=2 )


@pytest.mark.parametrize( "cls, key, name", SPECS )
class TestStartStop:

    def test_disabled_start_returns_false_and_spawns_nothing( self, cls, key, name ):
        obj = build( cls, False )
        assert obj.start() is False
        assert obj._thread is None

    def test_enabled_start_spawns_one_named_daemon_thread_running_the_loop( self, cls, key, name, stop_every_thread ):
        obj = build( cls, True )
        stop_every_thread.append( obj )
        assert obj.start() is True
        assert obj._thread.is_alive() and obj._thread.daemon is True
        assert obj._thread.name == name
        assert obj._stop_event.is_set() is False

    def test_a_second_start_while_alive_returns_false_and_keeps_the_thread( self, cls, key, name, stop_every_thread ):
        obj = build( cls, True )
        stop_every_thread.append( obj )
        obj.start()
        first = obj._thread
        assert obj.start() is False
        assert obj._thread is first

    def test_stop_signals_joins_and_is_idempotent( self, cls, key, name ):
        obj = build( cls, True )
        obj.start()
        thread = obj._thread
        obj.stop()
        assert obj._stop_event.is_set() and not thread.is_alive()
        obj.stop()

    def test_stop_before_start_is_safe( self, cls, key, name ):
        obj = build( cls, True )
        obj.stop()
        assert obj._stop_event.is_set() and obj._thread is None

    def test_start_after_stop_clears_the_event_and_spawns_a_new_thread( self, cls, key, name, stop_every_thread ):
        obj = build( cls, True )
        stop_every_thread.append( obj )
        obj.start()
        first = obj._thread
        obj.stop()
        assert obj.start() is True
        assert obj._thread is not first and obj._thread.is_alive()
        assert obj._stop_event.is_set() is False

    def test_a_thread_that_has_already_ended_does_not_block_a_new_start( self, cls, key, name, stop_every_thread ):
        obj = build( cls, True )
        stop_every_thread.append( obj )
        obj._thread = FakeThread( alive=False )
        assert obj.start() is True
        assert obj._thread.name == name

    def test_stop_joins_a_live_thread_with_the_timeout_it_was_given( self, cls, key, name ):
        obj = build( cls, True )
        obj._thread = FakeThread( alive=True )
        obj.stop( timeout=1.5 )
        obj.stop()
        assert obj._thread.joined == [ 1.5, 5.0 ]

    def test_stop_does_not_join_a_dead_thread( self, cls, key, name ):
        obj = build( cls, True )
        obj._thread = FakeThread( alive=False )
        obj.stop()
        assert obj._thread.joined == []

    def test_disabled_start_does_not_clear_a_set_stop_event( self, cls, key, name ):
        obj = build( cls, False )
        obj._stop_event.set()
        obj.start()
        assert obj._stop_event.is_set()


class TestSelfRespinObserverGate:
    """The observer starts when either its own flag or the stale-MCP delivery's flag is on."""

    def make( self, observer_on, stale_fn, stale_on ):
        cfg = Cfg( { "arbiter self respin observer enabled": observer_on, "stale mcp check delivery enabled": stale_on } )
        obj = SelfRespinObserverLoop( cfg, stale_mcp_fn=stale_fn )
        obj._loop = lambda: obj._stop_event.wait()
        return obj

    @pytest.mark.parametrize( "observer_on, stale_fn, stale_on, expected", [
        ( False, None,          True,  False ),
        ( False, lambda: [],    False, False ),
        ( False, lambda: [],    True,  True  ),
        ( True,  None,          True,  True  ),
        ( True,  lambda: [],    False, True  ),
    ] )
    def test_start_follows_either_flag( self, observer_on, stale_fn, stale_on, expected ):
        obj = self.make( observer_on, stale_fn, stale_on )
        try:
            assert obj.start() is expected
        finally:
            obj.stop( timeout=2 )
