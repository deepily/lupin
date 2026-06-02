"""
Unit tests for the durable notify outbox (Phase 1 / lever A of the messaging plane).

Network-free + deterministic: spool to a tmp dir, deliver via an injected
`send_fn`, and inject `now_epoch` for TTL. Covers spool / list_spooled / flush
(delivered, pending, expired, corrupt, raising send_fn, FIFO) + the once-only
flusher guard. The infinite daemon `_loop` is `# pragma: no cover`.

Venue: :7999-eligible (pure unit; writes only to a pytest tmp dir).
"""

import os
import json

import pytest

from lupin_mcp import notify_outbox


class FakeReq:
    """Minimal stand-in for AsyncNotificationRequest (model_dump + idempotency_key)."""

    def __init__( self, key="k1", message="hi" ):
        self.idempotency_key = key
        self._data           = { "idempotency_key": key, "message": message }

    def model_dump( self, mode="json" ):
        return dict( self._data )


class TestSpool:

    def test_writes_file_and_returns_path( self, tmp_path ):
        d    = str( tmp_path / "outbox" )
        path = notify_outbox.spool( FakeReq( key="abc" ), d, now_epoch=1000.0 )
        assert os.path.isfile( path )
        rec = json.load( open( path ) )
        assert rec[ "idempotency_key" ] == "abc"
        assert rec[ "spooled_at" ] == 1000.0
        assert rec[ "request" ][ "message" ] == "hi"

    def test_creates_dir( self, tmp_path ):
        d = str( tmp_path / "nested" / "outbox" )
        notify_outbox.spool( FakeReq(), d )
        assert os.path.isdir( d )

    def test_synthesizes_key_when_none( self, tmp_path ):
        d    = str( tmp_path / "outbox" )
        path = notify_outbox.spool( FakeReq( key=None ), d, now_epoch=2.0 )
        assert "nokey-" in os.path.basename( path )


class TestListSpooled:

    def test_empty_when_no_dir( self, tmp_path ):
        assert notify_outbox.list_spooled( str( tmp_path / "missing" ) ) == []

    def test_only_json_and_sorted_fifo( self, tmp_path ):
        d = str( tmp_path / "outbox" )
        notify_outbox.spool( FakeReq( key="a" ), d, now_epoch=1.0 )
        notify_outbox.spool( FakeReq( key="b" ), d, now_epoch=2.0 )
        os.makedirs( d, exist_ok=True )
        with open( os.path.join( d, "ignore.txt" ), "w" ) as f:
            f.write( "x" )
        listed = notify_outbox.list_spooled( d )
        assert len( listed ) == 2                       # the .txt is ignored
        assert listed == sorted( listed )               # oldest-first
        assert listed[ 0 ].endswith( ".json" )


class TestFlush:

    def test_delivered_deletes_file( self, tmp_path ):
        d = str( tmp_path / "outbox" )
        notify_outbox.spool( FakeReq( key="a" ), d, now_epoch=10.0 )
        stats = notify_outbox.flush( lambda req: True, d, ttl_seconds=100, now_epoch=11.0 )
        assert stats[ "delivered" ] == 1
        assert notify_outbox.list_spooled( d ) == []

    def test_pending_keeps_file( self, tmp_path ):
        d = str( tmp_path / "outbox" )
        notify_outbox.spool( FakeReq( key="a" ), d, now_epoch=10.0 )
        stats = notify_outbox.flush( lambda req: False, d, ttl_seconds=100, now_epoch=11.0 )
        assert stats[ "pending" ] == 1
        assert len( notify_outbox.list_spooled( d ) ) == 1

    def test_expired_deletes_file( self, tmp_path ):
        d = str( tmp_path / "outbox" )
        notify_outbox.spool( FakeReq( key="a" ), d, now_epoch=0.0 )
        # now is well past ttl → expired, send_fn must NOT be consulted
        called = { "n": 0 }
        def send_fn( req ):
            called[ "n" ] += 1
            return True
        stats = notify_outbox.flush( send_fn, d, ttl_seconds=10, now_epoch=100.0 )
        assert stats[ "expired" ] == 1
        assert called[ "n" ] == 0
        assert notify_outbox.list_spooled( d ) == []

    def test_corrupt_file_dropped( self, tmp_path ):
        d = str( tmp_path / "outbox" )
        os.makedirs( d, exist_ok=True )
        bad = os.path.join( d, "0001-bad.json" )
        with open( bad, "w" ) as f:
            f.write( "{ not valid json" )
        stats = notify_outbox.flush( lambda req: True, d, ttl_seconds=100, now_epoch=1.0 )
        assert stats[ "dropped_corrupt" ] == 1
        assert not os.path.exists( bad )

    def test_send_fn_raising_keeps_file( self, tmp_path ):
        d = str( tmp_path / "outbox" )
        notify_outbox.spool( FakeReq( key="a" ), d, now_epoch=10.0 )
        def boom( req ):
            raise RuntimeError( "server down" )
        stats = notify_outbox.flush( boom, d, ttl_seconds=100, now_epoch=11.0 )
        assert stats[ "pending" ] == 1
        assert len( notify_outbox.list_spooled( d ) ) == 1

    def test_fifo_order( self, tmp_path ):
        d = str( tmp_path / "outbox" )
        notify_outbox.spool( FakeReq( key="first" ),  d, now_epoch=1.0 )
        notify_outbox.spool( FakeReq( key="second" ), d, now_epoch=2.0 )
        notify_outbox.spool( FakeReq( key="third" ),  d, now_epoch=3.0 )
        seen = []
        notify_outbox.flush(
            lambda req: seen.append( req[ "idempotency_key" ] ) or True,
            d, ttl_seconds=1000, now_epoch=4.0
        )
        assert seen == [ "first", "second", "third" ]

    def test_empty_dir_zero_stats( self, tmp_path ):
        stats = notify_outbox.flush( lambda req: True, str( tmp_path / "none" ), ttl_seconds=10, now_epoch=1.0 )
        assert stats == { "delivered": 0, "expired": 0, "pending": 0, "dropped_corrupt": 0, "attempted": 0 }

    def test_now_epoch_defaults_to_wall_clock( self, tmp_path ):
        # Exercises the `now_epoch is None` default branch (no spooled items).
        stats = notify_outbox.flush( lambda req: True, str( tmp_path / "none" ), ttl_seconds=10 )
        assert stats[ "attempted" ] == 0


class TestSafeRemove:

    def test_swallows_missing_file( self, tmp_path ):
        # os.remove on a nonexistent path raises FileNotFoundError (an OSError);
        # _safe_remove must swallow it (racing-flush / already-gone case).
        notify_outbox._safe_remove( str( tmp_path / "does-not-exist.json" ) )  # no raise


class TestStartFlusher:

    def setup_method( self ):
        notify_outbox._flusher_started = False

    def teardown_method( self ):
        notify_outbox._flusher_started = False

    def test_starts_once_only( self, tmp_path ):
        d = str( tmp_path / "outbox" )
        first  = notify_outbox.start_flusher( lambda req: True, d, ttl_seconds=10, interval_seconds=999999 )
        second = notify_outbox.start_flusher( lambda req: True, d, ttl_seconds=10, interval_seconds=999999 )
        assert first is True
        assert second is False
