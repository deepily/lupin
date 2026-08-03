"""
Shared bounded embedding pool (bug 81854972).

Every InputAndOutputTable.insert_io_row( async_embedding=True ) previously spawned
a NEW daemon thread to generate GPU embeddings. Under fleet load (many concurrent
CC-listener sessions hammering /api/notify) the unbounded thread count saturated
the GPU + GIL and starved the asyncio event loop — /health timed out, docker
flagged the container "unhealthy" (the intermittent dev-server "hang").

This module provides ONE process-wide, bounded, runtime-reconfigurable pool that
ALL embedding work routes through, so global concurrency is capped (the event loop
is never starved) and a pending-slot budget bounds the backlog (a sustained burst
can't grow memory without limit). When the backlog is full the work is dropped
(backpressure) rather than blocking the caller — the notify path must return
immediately.

Runtime-configurable: pool size is read from config keys
'io tbl embedding pool max workers' (default 2) and
'io tbl embedding pool max pending' (default 64), and can be re-tuned live via
reconfigure_embedding_pool( ... ) without a code change.
"""

import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Optional

from cosa.config.configuration_manager import ConfigurationManager

# Process-wide singleton + the lock guarding its (re)creation.
_POOL_LOCK = threading.Lock()
_pool      = None


class BoundedEmbeddingPool:
    """
    A fixed-size thread pool with a pending-slot budget for backpressure.
    """

    def __init__( self, max_workers: int, max_pending: int, debug: bool = False ) -> None:
        """
        Construct the bounded pool.

        Requires:
            - max_workers is an int >= 1
            - max_pending is an int >= 0

        Ensures:
            - A ThreadPoolExecutor capped at max_workers backs all submissions
            - At most ( max_workers + max_pending ) tasks may be in-flight-or-queued
              at once; further submissions are dropped (backpressure)
            - dropped starts at 0

        Raises:
            - ValueError if max_workers < 1 or max_pending < 0
        """
        if max_workers < 1:  raise ValueError( "max_workers must be >= 1" )
        if max_pending < 0:  raise ValueError( "max_pending must be >= 0" )

        self.max_workers = max_workers
        self.max_pending = max_pending
        self.debug       = debug
        self.dropped     = 0
        self._executor   = ThreadPoolExecutor( max_workers=max_workers, thread_name_prefix="io-embed" )
        # permits = concurrent workers + queued allowance → total backlog cap
        self._slots      = threading.BoundedSemaphore( max_workers + max_pending )

    def submit( self, fn: Callable[ [], Any ] ) -> bool:
        """
        Submit a zero-arg callable to run on the pool.

        Requires:
            - fn is a zero-arg callable

        Ensures:
            - Returns True and schedules fn when a backlog slot is free
            - Returns False and increments dropped (WITHOUT running fn) when the
              backlog is full — non-blocking; the caller never waits
            - The slot is released when fn finishes, whether it returns or raises

        Raises:
            - None
        """
        if not self._slots.acquire( blocking=False ):
            self.dropped += 1
            if self.debug: print( f"[EMBED-POOL] ⚠️ backlog full ({self.max_workers}+{self.max_pending}) — dropped 1 (total={self.dropped})" )
            return False

        def _run():
            try:
                fn()
            finally:
                self._slots.release()

        self._executor.submit( _run )
        return True

    def shutdown( self, wait: bool = False ) -> None:
        """
        Stop accepting new work and release idle workers.

        Ensures:
            - In-flight tasks finish; idle worker threads exit
            - wait=True blocks until all in-flight tasks complete
        """
        self._executor.shutdown( wait=wait )


def get_embedding_pool( config_mgr: Optional[ Any ] = None, debug: bool = False ) -> BoundedEmbeddingPool:
    """
    Return the process-wide bounded embedding pool, creating it on first call.

    Requires:
        - config_mgr is a ConfigurationManager-like object or None

    Ensures:
        - First call builds the singleton from config keys
          'io tbl embedding pool max workers' (default 2) and
          'io tbl embedding pool max pending' (default 64)
        - Subsequent calls return the same instance (config args ignored once built)

    Raises:
        - None
    """
    global _pool
    with _POOL_LOCK:
        if _pool is None:
            cm          = config_mgr if config_mgr is not None else ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )
            max_workers = cm.get( "io tbl embedding pool max workers", default=2,  return_type="int" )
            max_pending = cm.get( "io tbl embedding pool max pending", default=64, return_type="int" )
            _pool       = BoundedEmbeddingPool( max_workers, max_pending, debug=debug )
        return _pool


def reconfigure_embedding_pool( max_workers: int, max_pending: int, debug: bool = False ) -> BoundedEmbeddingPool:
    """
    Runtime knob (bug 81854972): rebuild the shared pool with new bounds so the
    concurrency / backlog can be re-tuned live without a code change.

    Requires:
        - max_workers is an int >= 1
        - max_pending is an int >= 0

    Ensures:
        - The module singleton is replaced with a fresh pool and returned
        - The prior pool (if any) is shut down (in-flight tasks drain, idle workers
          exit) so its threads are not leaked

    Raises:
        - ValueError if max_workers < 1 or max_pending < 0 (from the constructor)
    """
    global _pool
    new_pool = BoundedEmbeddingPool( max_workers, max_pending, debug=debug )
    with _POOL_LOCK:
        old   = _pool
        _pool = new_pool
    if old is not None:
        old.shutdown( wait=False )
    return new_pool
