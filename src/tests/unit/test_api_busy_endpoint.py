#!/usr/bin/env python3
"""
Row 08919110 — GET /api/busy, the unauthenticated two-integer surface the managed
bounce guard reads to decide whether a restart would destroy a running job.

This file pins the ENDPOINT's shape and its IDLE reading (0/0 on an empty run queue)
without a live server — the run queue is mocked, so both the idle and the busy paths
are asserted deterministically. The refuse-vs-proceed DECISION lives in the host script
and its probe helper and is tested in test_bounce_dev_server_busy_guard.py; here we only
prove what the endpoint returns.

WHY BOTH ARMS (Maria's catch): a guard that trips on a routinely-non-zero signal trains
everyone to reflex --force, so the idle reading must be 0 — but an idle-only assertion
cannot go red. The run queue is delete-on-done (a finished job is removed the instant it
completes), so an empty queue reads 0/0; a populated one reads non-zero. Both are asserted.
"""
import asyncio
import sys
import types
import unittest
from unittest.mock import patch


class _FakeRunQueue:
    """Stands in for main_module.jobs_run_queue: the two numbers /api/busy reads."""
    def __init__( self, inflight, run_size ):
        self._inflight = inflight
        self._run_size = run_size

    def get_pool_status( self ):
        return { "inflight_agentic_jobs": self._inflight, "max_agentic_workers": 4, "pending_in_pool": 0 }

    def size( self ):
        return self._run_size


def _call_busy( inflight, run_size ):
    """Invoke the real busy() handler with jobs_run_queue mocked to the given counts."""
    from cosa.rest.routers.system import busy
    fake = types.ModuleType( "lupin_app.main" )
    fake.jobs_run_queue = _FakeRunQueue( inflight, run_size )
    with patch.dict( sys.modules, { "lupin_app.main": fake } ):
        return asyncio.run( busy() )


class TestApiBusyEndpoint( unittest.TestCase ):

    def test_idle_returns_two_zeros( self ):
        # An idle server (empty run queue, empty pool) reads 0/0 — the reading the guard
        # must see when there is nothing to protect.
        self.assertEqual( _call_busy( 0, 0 ),
                          { "inflight_agentic_jobs": 0, "run_queue_size": 0 } )

    def test_busy_reports_both_counts( self ):
        # The red-capable arm: a populated queue must read non-zero, or the idle
        # assertion above is unfalsifiable.
        r = _call_busy( 2, 1 )
        self.assertEqual( r[ "inflight_agentic_jobs" ], 2 )
        self.assertEqual( r[ "run_queue_size" ], 1 )

    def test_shape_is_exactly_two_int_fields( self ):
        # The contract the host probe parses: exactly two keys, both ints. Nothing else
        # rides along (and, deliberately, this is NOT /health — that stays two frozen fields).
        r = _call_busy( 3, 5 )
        self.assertEqual( set( r.keys() ), { "inflight_agentic_jobs", "run_queue_size" } )
        self.assertIsInstance( r[ "inflight_agentic_jobs" ], int )
        self.assertIsInstance( r[ "run_queue_size" ], int )


if __name__ == "__main__":
    unittest.main()
