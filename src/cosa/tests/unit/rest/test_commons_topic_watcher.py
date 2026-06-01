"""
Unit tests for the commons topic watcher base class
(cosa.rest.commons_topic_watcher.CommonsTopicWatcher).

Covers __init__, _register (insert / collision-raise / prune-on-insert),
_unregister (pop / silent-unknown), _prune_expired_locked (expired vs live),
start (thread None / alive-early-return / not-alive-respawn / init-skip-when-seeded),
stop (no-thread / with-thread-join), _run_loop (tick-ok / tick-raises with
debug-on print + debug-off silent / clean stop), and the two abstract methods
(_initialize_last_seen_ts / tick raise NotImplementedError) — to genuine 100%
line + branch + function.

No real threads, no real sleeps: threading.Thread is patched and _stop_event.wait
is driven via side_effect. ZERO network, ZERO disk.
"""

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

from cosa.rest import commons_topic_watcher as ctw
from cosa.rest.commons_topic_watcher import CommonsTopicWatcher


class _Concrete( CommonsTopicWatcher ):
    """Minimal concrete subclass that satisfies the abstract contract."""
    def __init__( self, *a, **k ):
        super().__init__( *a, **k )
        self.init_called = False
    def _initialize_last_seen_ts( self ):
        self.init_called = True
    def tick( self ):
        return 0


def _rec( exp ):
    return SimpleNamespace( expires_at_monotonic=exp )


class TestInit( unittest.TestCase ):
    def test_defaults( self ):
        w = CommonsTopicWatcher( store=Mock() )
        self.assertEqual( w.poll_interval_seconds, 1.0 )
        self.assertEqual( w.in_flight_ttl_seconds, 300.0 )
        self.assertEqual( w._in_flight, {} )
        self.assertIsNone( w._thread )


class TestRegister( unittest.TestCase ):
    def setUp( self ):
        self.w = _Concrete( store=Mock() )

    def test_insert( self ):
        self.w._register( "r1", _rec( 1e18 ) )
        self.assertIn( "r1", self.w._in_flight )

    def test_collision_raises( self ):
        self.w._register( "r1", _rec( 1e18 ) )
        with self.assertRaises( ValueError ):
            self.w._register( "r1", _rec( 1e18 ) )

    def test_prune_runs_on_insert( self ):
        # Pre-seed an already-expired record; the next _register prunes it.
        self.w._in_flight[ "old" ] = _rec( 0.0 )
        self.w._register( "new", _rec( 1e18 ) )
        self.assertNotIn( "old", self.w._in_flight )
        self.assertIn( "new", self.w._in_flight )


class TestUnregister( unittest.TestCase ):
    def setUp( self ):
        self.w = _Concrete( store=Mock() )

    def test_pop_existing( self ):
        self.w._in_flight[ "r1" ] = _rec( 1e18 )
        self.w._unregister( "r1" )
        self.assertNotIn( "r1", self.w._in_flight )

    def test_silent_on_unknown( self ):
        self.w._unregister( "nope" )   # no raise


class TestPruneExpiredLocked( unittest.TestCase ):
    def test_removes_only_expired( self ):
        w = _Concrete( store=Mock() )
        w._in_flight = { "live": _rec( 100.0 ), "dead": _rec( 10.0 ) }
        w._prune_expired_locked( now_monotonic=50.0 )
        self.assertIn( "live", w._in_flight )
        self.assertNotIn( "dead", w._in_flight )


class TestStart( unittest.TestCase ):
    def test_spawns_and_initializes( self ):
        w = _Concrete( store=Mock() )
        with patch.object( ctw.threading, "Thread" ) as MkThread:
            w.start()
        self.assertTrue( w.init_called )
        MkThread.assert_called_once()
        self.assertEqual( MkThread.call_args.kwargs[ "target" ], w._run_loop )
        self.assertTrue( MkThread.call_args.kwargs[ "daemon" ] )
        MkThread.return_value.start.assert_called_once_with()

    def test_early_return_when_alive( self ):
        w = _Concrete( store=Mock() )
        alive = Mock()
        alive.is_alive.return_value = True
        w._thread = alive
        with patch.object( ctw.threading, "Thread" ) as MkThread:
            w.start()
        MkThread.assert_not_called()       # no respawn
        self.assertFalse( w.init_called )

    def test_respawn_when_thread_dead( self ):
        w = _Concrete( store=Mock() )
        dead = Mock()
        dead.is_alive.return_value = False
        w._thread = dead
        with patch.object( ctw.threading, "Thread" ) as MkThread:
            w.start()
        MkThread.assert_called_once()

    def test_skips_init_when_already_seeded( self ):
        w = _Concrete( store=Mock() )
        w._initialized_last_seen = True
        with patch.object( ctw.threading, "Thread" ):
            w.start()
        self.assertFalse( w.init_called )   # _initialize_last_seen_ts NOT called


class TestStop( unittest.TestCase ):
    def test_no_thread_just_sets_event( self ):
        w = _Concrete( store=Mock() )
        w.stop()
        self.assertTrue( w._stop_event.is_set() )

    def test_with_thread_joins( self ):
        w = _Concrete( store=Mock() )
        t = Mock()
        w._thread = t
        w.stop( join_timeout=2.0 )
        t.join.assert_called_once_with( timeout=2.0 )


class TestRunLoop( unittest.TestCase ):
    def test_tick_ok_then_stop( self ):
        w = _Concrete( store=Mock() )
        w.tick = Mock( return_value=0 )
        w._stop_event = MagicMock()
        w._stop_event.wait.side_effect = [ False, True ]   # one iteration, then stop
        w._run_loop()
        w.tick.assert_called_once_with()

    def test_tick_raises_with_debug_prints( self ):
        w = _Concrete( store=Mock(), debug=True )
        w.tick = Mock( side_effect=RuntimeError( "boom" ) )
        w._stop_event = MagicMock()
        w._stop_event.wait.side_effect = [ False, True ]
        with patch( "builtins.print" ) as mp:
            w._run_loop()
        self.assertTrue( any( "tick raised" in str( c ) for c in mp.call_args_list ) )

    def test_tick_raises_without_debug_silent( self ):
        w = _Concrete( store=Mock(), debug=False )
        w.tick = Mock( side_effect=RuntimeError( "boom" ) )
        w._stop_event = MagicMock()
        w._stop_event.wait.side_effect = [ False, True ]
        with patch( "builtins.print" ) as mp:
            w._run_loop()
        mp.assert_not_called()


class TestAbstractMethods( unittest.TestCase ):
    def test_initialize_last_seen_ts_raises( self ):
        base = CommonsTopicWatcher( store=Mock() )
        with self.assertRaises( NotImplementedError ):
            base._initialize_last_seen_ts()

    def test_tick_raises( self ):
        base = CommonsTopicWatcher( store=Mock() )
        with self.assertRaises( NotImplementedError ):
            base.tick()


def isolated_unit_test():
    """
    Run the CommonsTopicWatcher unit tests in isolation.

    Ensures:
        - Returns (success, duration, message) for the smoke-runner harness
    """
    import time
    start_time = time.time()
    suite = unittest.TestLoader().loadTestsFromModule( __import__( __name__ ) )
    result = unittest.TextTestRunner( verbosity=2 ).run( suite )
    duration = time.time() - start_time
    success = result.wasSuccessful()
    message = f"{result.testsRun} run, {len( result.failures )} failed, {len( result.errors )} errors"
    return success, duration, message


if __name__ == "__main__":
    ok, secs, msg = isolated_unit_test()
    print( f"\n{'✅ PASS' if ok else '❌ FAIL'} CommonsTopicWatcher tests in {secs:.3f}s — {msg}" )
