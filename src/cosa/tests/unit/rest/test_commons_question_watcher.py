"""
Unit tests for CommonsQuestionWatcher (cosa.rest.commons_question_watcher).

Covers module helpers (_now_iso, _is_valid_in_reply_to all reject arcs + accept),
__init__, register_question (default/explicit ttl+ts, global-cap, per-user-cap,
collision), unregister_question (success / not-found / not-owned), is_in_flight,
_prune_expired_locked override (also clears dispatched set),
_initialize_last_seen_ts, tick (prune + snapshot + per-question fanout), and
_tick_one_question (read FNF / read-error / valid dispatch / invalid in_reply_to
debug + None-silent / mismatched qid / unregistered-mid-tick / idempotency-dup /
inject raises / entry_ts-None no-cursor-advance) — to genuine 100% L/B/F.

No threads, no disk: store + inject_fn boundary-mocked; tick helpers invoked
directly. ZERO real daemon.
"""

import unittest
from unittest.mock import Mock, patch

from cosa.rest import commons_question_watcher as cqw
from cosa.rest.commons_question_watcher import (
    CommonsQuestionWatcher, _InFlightQuestion, _now_iso, _is_valid_in_reply_to,
    CapExceededError, QuestionNotFound,
)


class TestModuleHelpers( unittest.TestCase ):
    def test_now_iso_returns_string( self ):
        self.assertIsInstance( _now_iso(), str )

    def test_is_valid_in_reply_to_arcs( self ):
        self.assertFalse( _is_valid_in_reply_to( 123 ) )          # not str
        self.assertFalse( _is_valid_in_reply_to( "" ) )           # empty
        self.assertFalse( _is_valid_in_reply_to( "x" * 65 ) )     # too long
        self.assertFalse( _is_valid_in_reply_to( "has space" ) )  # regex reject
        self.assertTrue( _is_valid_in_reply_to( "abc-123_XYZ" ) ) # valid


class _QWBase( unittest.TestCase ):
    def setUp( self ):
        self.store  = Mock( name="store" )
        self.inject = Mock( name="inject_fn" )
        self.w = CommonsQuestionWatcher( store=self.store, poll_interval_seconds=1.0,
                                         in_flight_ttl_seconds=3600.0, per_user_max=50,
                                         global_max=1000, debug=True )


class TestInit( _QWBase ):
    def test_caps_and_dispatch_map( self ):
        self.assertEqual( self.w.per_user_max, 50 )
        self.assertEqual( self.w.global_max, 1000 )
        self.assertEqual( self.w._dispatched_by_question, {} )


class TestRegisterQuestion( _QWBase ):
    def test_success_defaults( self ):
        self.w.register_question( "q1", "u1", "topic-q1", self.inject )
        self.assertTrue( self.w.is_in_flight( "q1" ) )

    def test_success_explicit_ttl_and_cursor( self ):
        self.w.register_question( "q1", "u1", "topic-q1", self.inject,
                                  ttl_seconds=10.0, last_seen_ts="t0" )
        self.assertEqual( self.w._in_flight[ "q1" ].last_seen_ts, "t0" )

    def test_global_cap( self ):
        self.w.global_max = 1
        self.w.register_question( "q1", "u1", "t", self.inject )
        with self.assertRaises( CapExceededError ):
            self.w.register_question( "q2", "u1", "t", self.inject )

    def test_per_user_cap( self ):
        self.w.per_user_max = 1
        self.w.register_question( "q1", "u1", "t", self.inject )
        with self.assertRaises( CapExceededError ):
            self.w.register_question( "q2", "u1", "t", self.inject )

    def test_collision( self ):
        self.w.register_question( "q1", "u1", "t", self.inject )
        with self.assertRaises( ValueError ):
            self.w.register_question( "q1", "u1", "t", self.inject )


class TestUnregisterQuestion( _QWBase ):
    def test_success( self ):
        self.w.register_question( "q1", "u1", "t", self.inject )
        self.w._dispatched_by_question[ "q1" ] = { "t1" }
        self.w.unregister_question( "q1", "u1" )
        self.assertNotIn( "q1", self.w._in_flight )
        self.assertNotIn( "q1", self.w._dispatched_by_question )

    def test_not_found( self ):
        with self.assertRaises( QuestionNotFound ):
            self.w.unregister_question( "ghost", "u1" )

    def test_not_owned( self ):
        self.w.register_question( "q1", "u1", "t", self.inject )
        with self.assertRaises( QuestionNotFound ):
            self.w.unregister_question( "q1", "u2" )


class TestIsInFlight( _QWBase ):
    def test_present( self ):
        self.w.register_question( "q1", "u1", "t", self.inject )
        self.assertTrue( self.w.is_in_flight( "q1" ) )

    def test_absent( self ):
        self.assertFalse( self.w.is_in_flight( "q1" ) )


class TestPruneExpiredLocked( _QWBase ):
    def test_clears_inflight_and_dispatched( self ):
        self.w.register_question( "q1", "u1", "t", self.inject )
        self.w._in_flight[ "q1" ].expires_at_monotonic = 0.0
        self.w._dispatched_by_question[ "q1" ] = { "t1" }
        self.w._prune_expired_locked( now_monotonic=1e18 )
        self.assertNotIn( "q1", self.w._in_flight )
        self.assertNotIn( "q1", self.w._dispatched_by_question )


class TestInitializeLastSeenTs( _QWBase ):
    def test_marks_initialized( self ):
        self.w._initialize_last_seen_ts()
        self.assertTrue( self.w._initialized_last_seen )


class TestTick( _QWBase ):
    def test_fans_out_over_snapshot( self ):
        self.w.register_question( "q1", "u1", "topic-q1", self.inject, last_seen_ts="t0" )
        self.store.read.return_value = [ { "ts": "t2", "metadata": { "in_reply_to": "q1" } } ]
        self.assertEqual( self.w.tick(), 1 )
        self.inject.assert_called_once()


def _q( topic="topic-q1", user="u1", inject=None, cursor="t0" ):
    return _InFlightQuestion( topic=topic, user_id=user, inject_fn=inject or Mock(),
                              last_seen_ts=cursor, expires_at_monotonic=1e18 )


class TestTickOneQuestion( _QWBase ):
    def test_read_file_not_found_returns_zero( self ):
        self.store.read.side_effect = FileNotFoundError
        self.assertEqual( self.w._tick_one_question( "q1", _q() ), 0 )

    def test_read_error_debug_returns_zero( self ):
        self.store.read.side_effect = RuntimeError( "read boom" )
        with patch( "builtins.print" ) as mp:
            self.assertEqual( self.w._tick_one_question( "q1", _q() ), 0 )
        self.assertTrue( any( "read failed" in str( c ) for c in mp.call_args_list ) )

    def test_valid_dispatch_advances_cursor( self ):
        self.w.register_question( "q1", "u1", "topic-q1", self.inject, last_seen_ts="t0" )
        q = self.w._in_flight[ "q1" ]
        self.store.read.return_value = [
            { "ts": "t2", "metadata": { "in_reply_to": "q1" } },   # latest t0→t2, dispatch
            { "ts": "t1", "metadata": { "in_reply_to": "q1" } },   # t1>t2 False (no update), dispatch
        ]
        self.assertEqual( self.w._tick_one_question( "q1", q ), 2 )
        self.assertEqual( q.last_seen_ts, "t2" )

    def test_invalid_in_reply_to_debug_and_none_silent( self ):
        q = _q()
        self.store.read.return_value = [
            { "ts": "t1", "metadata": { "in_reply_to": "bad id!" } },   # invalid non-None → debug print
            { "ts": "t2", "metadata": {} },                            # in_reply_to None → silent skip
        ]
        with patch( "builtins.print" ) as mp:
            self.assertEqual( self.w._tick_one_question( "q1", q ), 0 )
        self.assertTrue( any( "skipping invalid in_reply_to" in str( c ) for c in mp.call_args_list ) )

    def test_mismatched_question_id_skipped( self ):
        q = _q()
        self.store.read.return_value = [ { "ts": "t1", "metadata": { "in_reply_to": "other" } } ]
        self.assertEqual( self.w._tick_one_question( "q1", q ), 0 )

    def test_unregistered_mid_tick_skips_dispatch_and_cursor( self ):
        # q1 NOT in _in_flight → current is None in both lock-guarded sections
        q = _q( cursor="t0" )
        self.store.read.return_value = [ { "ts": "t2", "metadata": { "in_reply_to": "q1" } } ]
        self.assertEqual( self.w._tick_one_question( "q1", q ), 0 )
        self.assertEqual( q.last_seen_ts, "t0" )   # cursor untouched (current None)

    def test_idempotency_duplicate_skipped( self ):
        self.w.register_question( "q1", "u1", "topic-q1", self.inject, last_seen_ts="t0" )
        q = self.w._in_flight[ "q1" ]
        self.w._dispatched_by_question[ "q1" ] = { "t2" }   # already dispatched ts t2
        self.store.read.return_value = [ { "ts": "t2", "metadata": { "in_reply_to": "q1" } } ]
        self.assertEqual( self.w._tick_one_question( "q1", q ), 0 )

    def test_inject_raises_is_isolated( self ):
        self.inject.side_effect = RuntimeError( "inject boom" )
        self.w.register_question( "q1", "u1", "topic-q1", self.inject, last_seen_ts="t0" )
        q = self.w._in_flight[ "q1" ]
        self.store.read.return_value = [ { "ts": "t2", "metadata": { "in_reply_to": "q1" } } ]
        with patch( "builtins.print" ) as mp:
            self.assertEqual( self.w._tick_one_question( "q1", q ), 0 )   # raised → not counted
        self.assertTrue( any( "inject_fn raised" in str( c ) for c in mp.call_args_list ) )

    def test_entry_ts_none_no_cursor_advance( self ):
        self.w.register_question( "q1", "u1", "topic-q1", self.inject, last_seen_ts="t0" )
        q = self.w._in_flight[ "q1" ]
        self.store.read.return_value = [ { "ts": None, "metadata": { "in_reply_to": "q1" } } ]
        self.assertEqual( self.w._tick_one_question( "q1", q ), 1 )   # dispatched
        self.assertEqual( q.last_seen_ts, "t0" )                      # latest==cursor → no advance


def isolated_unit_test():
    """
    Run the CommonsQuestionWatcher unit tests in isolation.

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
    print( f"\n{'✅ PASS' if ok else '❌ FAIL'} CommonsQuestionWatcher tests in {secs:.3f}s — {msg}" )
