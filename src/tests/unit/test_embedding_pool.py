#!/usr/bin/env python3
"""
Unit — shared bounded embedding pool (bug 81854972).

InputAndOutputTable.insert_io_row( async_embedding=True ) used to spawn a NEW
daemon thread per call; under fleet load the unbounded thread count saturated the
GPU + GIL and starved the asyncio event loop (/health timeouts → docker
"unhealthy" "hang"). The pool caps GLOBAL embedding concurrency and bounds the
backlog so the event loop is never starved and memory can't grow without limit.

Pins:
    - submit runs the callable when a slot is free
    - submit drops (returns False, increments dropped) when the backlog is full —
      non-blocking; the callable does NOT run
    - the slot is released after the callable finishes (success AND failure)
    - constructor rejects illegal bounds
    - get_embedding_pool is a singleton built from the canonical config keys
    - reconfigure rebuilds the singleton with new bounds and shuts the old one down

Venue: :7999 (pure unit — real ThreadPoolExecutor, Event-synchronized, no GPU/DB).
"""

import os
import sys
import threading

import pytest

# Bootstrap
_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

import cosa.memory.embedding_pool as ep
from cosa.memory.embedding_pool import (
    BoundedEmbeddingPool, get_embedding_pool, reconfigure_embedding_pool,
)


@pytest.fixture( autouse=True )
def _reset_singleton():
    """Each test starts with a fresh module singleton (isolation)."""
    ep._pool = None
    yield
    ep._pool = None


class _StubConfigMgr:
    """Returns canned values for the two pool config keys; records the calls."""
    def __init__( self, max_workers=2, max_pending=64 ):
        self._vals = {
            "io tbl embedding pool max workers" : max_workers,
            "io tbl embedding pool max pending" : max_pending,
        }
        self.calls = []
    def get( self, key, default=None, return_type=None ):
        self.calls.append( key )
        return self._vals.get( key, default )


class TestBoundedEmbeddingPool:

    def test_submit_runs_callable_when_capacity_free( self ):
        pool = BoundedEmbeddingPool( max_workers=1, max_pending=1 )
        ran  = threading.Event()
        assert pool.submit( ran.set ) is True
        assert ran.wait( timeout=2.0 ), "callable did not run on the pool"
        assert pool.dropped == 0

    def test_submit_drops_when_backlog_full( self ):
        # workers=1, pending=0 → exactly ONE slot. Occupy it with a blocking task,
        # then a second submit must be rejected (backpressure), not block, not run.
        pool      = BoundedEmbeddingPool( max_workers=1, max_pending=0, debug=True )
        release   = threading.Event()
        started   = threading.Event()
        def _block():
            started.set()
            release.wait( timeout=2.0 )
        assert pool.submit( _block ) is True
        assert started.wait( timeout=2.0 ), "first task never started"

        second_ran = threading.Event()
        assert pool.submit( second_ran.set ) is False   # dropped
        assert pool.dropped == 1
        assert not second_ran.is_set()

        release.set()   # let the first task finish (release its slot)

    def test_slot_released_after_success_allows_resubmit( self ):
        pool  = BoundedEmbeddingPool( max_workers=1, max_pending=0 )
        first = threading.Event()
        assert pool.submit( first.set ) is True
        assert first.wait( timeout=2.0 )
        # If the slot was released, a second submit succeeds.
        second = threading.Event()
        assert pool.submit( second.set ) is True
        assert second.wait( timeout=2.0 )
        assert pool.dropped == 0

    def test_slot_released_even_when_callable_raises( self ):
        pool = BoundedEmbeddingPool( max_workers=1, max_pending=0 )
        boom = threading.Event()
        def _raise():
            boom.set()
            raise RuntimeError( "embedding blew up" )
        assert pool.submit( _raise ) is True
        assert boom.wait( timeout=2.0 )
        # Slot must be freed in the finally — wait for the worker to release it,
        # then a fresh submit succeeds.
        ok = threading.Event()
        for _ in range( 200 ):
            if pool.submit( ok.set ):
                break
            threading.Event().wait( 0.01 )
        assert ok.wait( timeout=2.0 ), "slot was not released after callable raised"

    def test_constructor_rejects_illegal_bounds( self ):
        with pytest.raises( ValueError ): BoundedEmbeddingPool( max_workers=0, max_pending=1 )
        with pytest.raises( ValueError ): BoundedEmbeddingPool( max_workers=1, max_pending=-1 )

    def test_shutdown_waits_for_inflight( self ):
        pool = BoundedEmbeddingPool( max_workers=1, max_pending=1 )
        done = threading.Event()
        pool.submit( done.set )
        pool.shutdown( wait=True )
        assert done.is_set()


class TestSingletonAndReconfigure:

    def test_get_embedding_pool_is_singleton_from_config( self ):
        cfg = _StubConfigMgr( max_workers=3, max_pending=7 )
        p1  = get_embedding_pool( config_mgr=cfg )
        p2  = get_embedding_pool( config_mgr=cfg )
        assert p1 is p2                       # same instance
        assert p1.max_workers == 3
        assert p1.max_pending == 7
        assert "io tbl embedding pool max workers" in cfg.calls
        assert "io tbl embedding pool max pending" in cfg.calls

    def test_reconfigure_replaces_singleton_with_new_bounds( self ):
        first = get_embedding_pool( config_mgr=_StubConfigMgr( 2, 4 ) )
        new   = reconfigure_embedding_pool( max_workers=5, max_pending=9 )
        assert new is not first
        assert new.max_workers == 5 and new.max_pending == 9
        # The singleton now resolves to the reconfigured pool.
        assert get_embedding_pool( config_mgr=_StubConfigMgr( 1, 1 ) ) is new

    def test_reconfigure_with_no_prior_pool_is_fine( self ):
        # old is None branch — no shutdown to perform.
        new = reconfigure_embedding_pool( max_workers=1, max_pending=0 )
        assert isinstance( new, BoundedEmbeddingPool )


if __name__ == "__main__":
    sys.exit( pytest.main( [ __file__, "-v" ] ) )
