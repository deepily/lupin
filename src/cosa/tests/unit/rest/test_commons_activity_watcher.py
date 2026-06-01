"""
Unit tests for CommonsActivityWatcher (cosa.rest.commons_activity_watcher).

Covers __init__, _initialize_last_seen_ts (FileNotFoundError-skip / empty /
ts-None / max-update / outer-exception), tick (enum-fail-zero / full-dispatch /
read-FNF + read-error + empty-zero / bridge-resolver-exception / dispatch-error-
continue), _dedupe_for_dispatch (broadcasts keep/drop/non-str-passthrough,
broadcast-acks keep/drop/non-str-passthrough, other passthrough),
_resolve_recipient_user_id (sender_user_id / bridge / none), and
_dispatch_activity_event (reserved+user_id / free-form+no-user_id) — to genuine
100% line + branch + function.

No threads, no disk: store / push_notification_fn / bridge resolver are
boundary-mocked; tick + helpers invoked directly. ZERO real daemon.
"""

import unittest
from unittest.mock import Mock, patch

from cosa.rest.commons_activity_watcher import CommonsActivityWatcher


class _ActBase( unittest.TestCase ):
    def setUp( self ):
        self.store    = Mock( name="store" )
        self.push     = Mock( name="push_fn" )
        self.resolver = Mock( name="resolver", return_value={ "s": "user-1" } )
        self.w = CommonsActivityWatcher(
            store=self.store, push_notification_fn=self.push,
            excluded_topics=[ "presence" ], bridge_owner_resolver_fn=self.resolver,
            poll_interval_seconds=1.0, debug=True,
        )


class TestInit( _ActBase ):
    def test_excluded_topics_is_set( self ):
        self.assertEqual( self.w.excluded_topics, { "presence" } )
        self.assertEqual( self.w._thread_name, "CommonsActivityWatcher" )


class TestInitializeLastSeenTs( _ActBase ):
    def test_walks_topics_for_max_ts( self ):
        self.store._all_topic_names.return_value = [ "a", "b", "c", "d", "e", "f", "presence" ]
        reads = {
            "a": [ { "ts": "t1" } ],     # max None → t1
            "c": [],                     # empty → skip
            "d": [ { "ts": "t3" } ],     # t3 > t1 → t3
            "e": [ { "ts": "t0" } ],     # t0 > t3 False → skip
            "f": [ { "ts": None } ],     # ts None → skip
        }
        def _read( topic, limit=1 ):
            if topic == "b":
                raise FileNotFoundError
            return reads.get( topic, [] )
        self.store.read.side_effect = _read
        self.w._initialize_last_seen_ts()
        self.assertEqual( self.w._last_seen_ts, "t3" )
        self.assertTrue( self.w._initialized_last_seen )
        self.store.read.assert_any_call( "a", limit=1 )   # excluded "presence" never read

    def test_outer_exception_debug_prints( self ):
        self.store._all_topic_names.side_effect = RuntimeError( "boom" )
        with patch( "builtins.print" ) as mp:
            self.w._initialize_last_seen_ts()
        self.assertTrue( self.w._initialized_last_seen )
        self.assertIsNone( self.w._last_seen_ts )
        self.assertTrue( any( "startup _last_seen_ts init failed" in str( c ) for c in mp.call_args_list ) )


class TestTick( _ActBase ):
    def test_topic_enumeration_failure_returns_zero( self ):
        self.store._all_topic_names.side_effect = RuntimeError( "enum boom" )
        with patch( "builtins.print" ):
            self.assertEqual( self.w.tick(), 0 )

    def test_full_dispatch_advances_cursor( self ):
        self.store._all_topic_names.return_value = [ "free1" ]
        self.store.read.return_value = [
            { "ts": "t2", "metadata": { "sender_user_id": "user-1" }, "sender_session_id": "s", "body": "hi" },
            { "ts": "t1", "metadata": {}, "sender_session_id": "s", "body": "lo" },
        ]
        dispatched = self.w.tick()
        self.assertEqual( dispatched, 2 )
        self.assertEqual( self.w._last_seen_ts, "t2" )
        self.assertEqual( self.push.call_count, 2 )

    def test_read_fnf_and_error_and_empty_returns_zero( self ):
        self.store._all_topic_names.return_value = [ "fnf", "err" ]
        def _read( topic, since=None, limit=100 ):
            if topic == "fnf":
                raise FileNotFoundError
            raise RuntimeError( "read boom" )
        self.store.read.side_effect = _read
        with patch( "builtins.print" ):
            self.assertEqual( self.w.tick(), 0 )

    def test_bridge_resolver_exception_dispatches_without_user( self ):
        self.store._all_topic_names.return_value = [ "free1" ]
        self.store.read.return_value = [
            { "ts": "t2", "metadata": {}, "sender_session_id": "ghost", "body": "hi" },
        ]
        self.resolver.side_effect = RuntimeError( "resolver boom" )
        with patch( "builtins.print" ):
            self.assertEqual( self.w.tick(), 1 )
        # user_id unresolved (empty bridge map) → push called WITHOUT user_id kwarg
        self.assertNotIn( "user_id", self.push.call_args.kwargs )

    def test_dispatch_exception_is_skipped( self ):
        self.store._all_topic_names.return_value = [ "free1" ]
        self.store.read.return_value = [
            { "ts": "t2", "metadata": { "sender_user_id": "user-1" }, "sender_session_id": "s" },
        ]
        self.push.side_effect = RuntimeError( "push boom" )
        with patch( "builtins.print" ):
            self.assertEqual( self.w.tick(), 0 )       # dispatch failed → not counted
        self.assertEqual( self.w._last_seen_ts, "t2" )  # cursor still advances (pre-dedupe)

    def test_dispatch_exception_debug_off_silent( self ):
        self.w.debug = False                            # exercises the if-debug FALSE arc (175->178)
        self.store._all_topic_names.return_value = [ "free1" ]
        self.store.read.return_value = [
            { "ts": "t2", "metadata": { "sender_user_id": "user-1" }, "sender_session_id": "s" },
        ]
        self.push.side_effect = RuntimeError( "push boom" )
        with patch( "builtins.print" ) as mp:
            self.assertEqual( self.w.tick(), 0 )
        mp.assert_not_called()


class TestDedupeForDispatch( _ActBase ):
    def test_broadcasts_keep_strip_and_drop( self ):
        entries = [
            { "_topic": "broadcasts", "metadata": { "broadcast_id": "x", "target_session_id": "s1", "k": 1 } },
            { "_topic": "broadcasts", "metadata": { "broadcast_id": "x", "target_session_id": "s2" } },  # dup → drop
            { "_topic": "broadcasts", "metadata": { "broadcast_id": None } },                            # non-str → passthrough
        ]
        out = self.w._dedupe_for_dispatch( entries )
        self.assertEqual( len( out ), 2 )
        self.assertNotIn( "target_session_id", out[ 0 ][ "metadata" ] )   # stripped on kept copy
        self.assertEqual( out[ 0 ][ "metadata" ][ "k" ], 1 )

    def test_broadcast_acks_keep_drop_and_passthrough( self ):
        entries = [
            { "_topic": "broadcast-acks", "metadata": { "broadcast_id": "x", "status": "ok" }, "sender_session_id": "s1" },
            { "_topic": "broadcast-acks", "metadata": { "broadcast_id": "x", "status": "ok" }, "sender_session_id": "s1" },  # dup → drop
            { "_topic": "broadcast-acks", "metadata": { "broadcast_id": "x", "status": None }, "sender_session_id": "s1" },  # non-str → passthrough
        ]
        out = self.w._dedupe_for_dispatch( entries )
        self.assertEqual( len( out ), 2 )

    def test_other_topic_passthrough( self ):
        entries = [ { "_topic": "free", "metadata": {} } ]
        self.assertEqual( self.w._dedupe_for_dispatch( entries ), entries )


class TestResolveRecipientUserId( _ActBase ):
    def test_sender_user_id_wins( self ):
        entry = { "metadata": { "sender_user_id": "u-direct" }, "sender_session_id": "s" }
        self.assertEqual( self.w._resolve_recipient_user_id( entry, { "s": "u-bridge" } ), "u-direct" )

    def test_bridge_fallback( self ):
        entry = { "metadata": {}, "sender_session_id": "s" }
        self.assertEqual( self.w._resolve_recipient_user_id( entry, { "s": "u-bridge" } ), "u-bridge" )

    def test_none_when_unresolvable( self ):
        entry = { "metadata": {} }
        self.assertIsNone( self.w._resolve_recipient_user_id( entry, {} ) )


class TestDispatchActivityEvent( _ActBase ):
    def test_reserved_topic_with_user_id( self ):
        entry = { "_topic": "broadcasts", "ts": "t1", "metadata": { "sender_user_id": "u1" },
                  "sender_session_id": "s", "body": "b" }
        self.w._dispatch_activity_event( entry, { } )
        kwargs = self.push.call_args.kwargs
        self.assertEqual( kwargs[ "payload" ][ "topic_kind" ], "reserved" )
        self.assertEqual( kwargs[ "user_id" ], "u1" )

    def test_free_form_topic_without_user_id( self ):
        entry = { "ts": "t1", "metadata": {}, "sender_session_id": None, "body": "b" }   # no _topic → "unknown"
        self.w._dispatch_activity_event( entry, { } )
        kwargs = self.push.call_args.kwargs
        self.assertEqual( kwargs[ "payload" ][ "topic_kind" ], "free-form" )
        self.assertNotIn( "user_id", kwargs )


def isolated_unit_test():
    """
    Run the CommonsActivityWatcher unit tests in isolation.

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
    print( f"\n{'✅ PASS' if ok else '❌ FAIL'} CommonsActivityWatcher tests in {secs:.3f}s — {msg}" )
