#!/usr/bin/env python3
"""
Row 08919110 — GET /api/busy, the unauthenticated surface the managed bounce guard
reads to decide whether a restart would destroy a running job.
Row e6b8fe56 — WIDENED: it is now also the venue-idle check's only unfiltered source,
so it carries the todo depth and the monopolize slot as well.

This file pins the ENDPOINT's shape and both readings (empty vs populated) without a
live server — the queues are mocked, so both arms are asserted deterministically. The
refuse-vs-proceed DECISION lives in the host script and its probe helper and is tested
in test_bounce_dev_server_busy_guard.py; the venue verdict lives in cosa.rest.venue_idle
and is tested in src/cosa/tests/unit/rest/test_venue_idle.py. Here we only prove what
the endpoint returns.

WHY BOTH ARMS (Maria's catch): a guard that trips on a routinely-non-zero signal trains
everyone to reflex --force, so the empty reading must be all-zero — but an empty-only
assertion cannot go red. The run queue is delete-on-done (a finished job is removed the
instant it completes), so an empty queue reads 0; a populated one reads non-zero. Both
are asserted.

WHY todo_queue_size IS HERE AT ALL (row e6b8fe56): measured 2026-08-25, a job QUEUED in
todo moves NO field on /api/queue/pool-status — inflight stays 0 and monopolize_id stays
null — so every reader that derived "idle" from that endpoint called a backed-up venue
free. The todo depth is the field that makes "nothing is WAITING" answerable, and it is
reported here rather than on pool-status because this door is unfiltered and needs no
credential (/api/get-queue/{q} shows only the caller's own jobs and answers 403 to a
non-admin asking for all).
"""
import asyncio
import sys
import types
import unittest
from unittest.mock import patch


class _FakeRunQueue:
    """Stands in for main_module.jobs_run_queue: the numbers /api/busy reads."""
    def __init__( self, inflight, run_size, mono_id=None ):
        self._inflight = inflight
        self._run_size = run_size
        self._mono_id  = mono_id

    def get_pool_status( self ):
        return {
            "inflight_agentic_jobs" : self._inflight,
            "max_agentic_workers"   : 4,
            "pending_in_pool"       : 0,
            "monopolize_inflight"   : self._mono_id is not None,
            "monopolize_id"         : self._mono_id,
        }

    def size( self ):
        return self._run_size


class _FakeTodoQueue:
    """Stands in for main_module.jobs_todo_queue: the ingress depth (row e6b8fe56)."""
    def __init__( self, todo_size ):
        self._todo_size = todo_size

    def size( self ):
        return self._todo_size


def _call_busy( inflight, run_size, todo_size=0, mono_id=None ):
    """Invoke the real busy() handler with both queues mocked to the given counts."""
    from cosa.rest.routers.system import busy
    fake = types.ModuleType( "lupin_app.main" )
    fake.jobs_run_queue  = _FakeRunQueue( inflight, run_size, mono_id )
    fake.jobs_todo_queue = _FakeTodoQueue( todo_size )
    with patch.dict( sys.modules, { "lupin_app.main": fake } ):
        return asyncio.run( busy() )


class TestApiBusyEndpoint( unittest.TestCase ):

    def test_idle_returns_all_zeros( self ):
        # An idle server (empty run queue, empty todo, empty pool, no monopolizer) —
        # the reading the guard must see when there is nothing to protect.
        self.assertEqual( _call_busy( 0, 0 ), {
            "inflight_agentic_jobs" : 0,
            "run_queue_size"        : 0,
            "todo_queue_size"       : 0,
            "monopolize_inflight"   : False,
            "monopolize_id"         : None,
        } )

    def test_busy_reports_both_counts( self ):
        # The red-capable arm: a populated queue must read non-zero, or the idle
        # assertion above is unfalsifiable.
        r = _call_busy( 2, 1 )
        self.assertEqual( r[ "inflight_agentic_jobs" ], 2 )
        self.assertEqual( r[ "run_queue_size" ], 1 )

    def test_queued_work_is_visible_here_and_nowhere_else( self ):
        # Row e6b8fe56, the whole point: work sitting in todo moves NO pool field —
        # inflight 0, monopolize_inflight False, monopolize_id None — and would have
        # read as idle. todo_queue_size is what makes it visible.
        r = _call_busy( 0, 0, todo_size=3 )
        self.assertEqual( r[ "todo_queue_size" ], 3 )
        self.assertEqual( r[ "inflight_agentic_jobs" ], 0 )
        self.assertEqual( r[ "run_queue_size" ], 0 )
        self.assertFalse( r[ "monopolize_inflight" ] )
        self.assertIsNone( r[ "monopolize_id" ] )

    def test_monopolize_slot_is_reported_without_credentials( self ):
        # pool-status requires get_current_user; this door does not. The venue check
        # needs the monopolize pair, so it is mirrored here.
        r = _call_busy( 0, 1, mono_id="ts-827a54cd::user" )
        self.assertTrue( r[ "monopolize_inflight" ] )
        self.assertEqual( r[ "monopolize_id" ], "ts-827a54cd::user" )

    def test_shape_is_exactly_five_fields_with_pinned_types( self ):
        # The contract both the host probe and cosa.rest.venue_idle parse. Nothing else
        # rides along (and, deliberately, this is NOT /health — that stays two frozen
        # fields). Widened from two to five by row e6b8fe56; bounce_busy_probe.py reads
        # its two by name and ignores the rest, so the widening is additive for it.
        r = _call_busy( 3, 5, todo_size=7, mono_id="m-1" )
        self.assertEqual( set( r.keys() ), {
            "inflight_agentic_jobs", "run_queue_size", "todo_queue_size",
            "monopolize_inflight", "monopolize_id",
        } )
        self.assertIsInstance( r[ "inflight_agentic_jobs" ], int )
        self.assertIsInstance( r[ "run_queue_size" ], int )
        self.assertIsInstance( r[ "todo_queue_size" ], int )
        self.assertIsInstance( r[ "monopolize_inflight" ], bool )
        self.assertIsInstance( r[ "monopolize_id" ], str )


if __name__ == "__main__":
    unittest.main()
