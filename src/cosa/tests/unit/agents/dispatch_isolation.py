#!/usr/bin/env python3
"""
Shared harness for the concurrent-jobs notification tests.

Two jobs of one type run on one event loop, as in the agentic pool.
A recorder replaces the dispatcher's final send.
A test then sees the sender_id and target_user each job's notifications would carry.
"""

import asyncio
from unittest.mock import patch

from cosa.agents.utils import agent_notification_dispatcher as dispatcher_mod

_REAL_SLEEP = asyncio.sleep


async def _instant_sleep( delay, *args, **kw ):
    """Yield to the loop without waiting, so two jobs still interleave."""
    await _REAL_SLEEP( 0 )


def run_two_jobs( job_a, job_b, entry=lambda job: job._execute() ):
    """
    Run two jobs concurrently and return every notification that reached the wire.

    Requires:
        - job_a and job_b are jobs of one type with different user_email values
        - entry( job ) returns the coroutine that runs the job

    Ensures:
        - returns a list of ( sender_id, target_user, job_id, message ) tuples
        - the dispatcher send is recorded, never made
        - asyncio.sleep yields without waiting
    """
    sent = [ ]

    def record( request ):
        sent.append( ( request.sender_id, request.target_user, request.job_id, request.message ) )

    async def both():
        return await asyncio.gather( entry( job_a ), entry( job_b ), return_exceptions=True )

    with patch.object( dispatcher_mod, "_notify_user_async", record ), \
         patch.object( dispatcher_mod, "_notify_user_sync", lambda request: record( request ) ), \
         patch( "asyncio.sleep", new=_instant_sleep ):
        outcomes = asyncio.run( both() )
    return sent, outcomes


def rows_for( sent, job ):
    """Return the notifications that name this job by its id_hash."""
    return [ row for row in sent if row[ 2 ] == job.id_hash ]


def assert_each_job_keeps_its_own_identity( sent, jobs, min_rows=2 ):
    """
    Check that each job's notifications carry its own user and sender.

    Requires:
        - jobs is the list of jobs passed to run_two_jobs

    Raises:
        - AssertionError naming the first notification that carried another job's identity
    """
    for job in jobs:
        rows = rows_for( sent, job )
        assert len( rows ) >= min_rows, f"{job.id_hash}: only {len( rows )} notifications reached the wire"
        for sender_id, target_user, job_id, message in rows:
            assert target_user == job.user_email, f"{message!r} for {job.user_email} went to {target_user}"
            assert sender_id.endswith( f"#{job.base_id}" ), f"{message!r} for {job.base_id} carried sender {sender_id}"
