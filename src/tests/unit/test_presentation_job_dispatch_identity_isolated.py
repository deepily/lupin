#!/usr/bin/env python3
"""
Two presentation jobs running together each notify as their own user.

The presentation interface kept the target user in module globals. One dispatcher served
every job in the pool, so the job that started last overwrote them for the rest.
The live test, submitted as the test user, had its two presentation asks sent to another
account and they waited out their ten minute timeouts.

Each job now also sets per-task context variables, which the dispatcher reads first.
This test runs two real jobs at once through the real interface wrapper.
Only the dispatcher's network send is replaced.
"""

import asyncio
from unittest.mock import patch

import pytest

from cosa.agents.presentation_generator import cosa_interface, voice_io
from cosa.agents.presentation_generator.job import PresentationGeneratorJob

REAL_SLEEP = asyncio.sleep


def _job( email ):
    return PresentationGeneratorJob(
        source_path = "/io/deep-research/x/article.md",
        user_id     = f"uid-{email}",
        user_email  = email,
        session_id  = f"session-{email}",
        dry_run     = True,
    )


@pytest.mark.asyncio
async def test_concurrent_jobs_address_their_own_user():
    seen = []

    async def record( message, **kwargs ):
        # Same read the dispatcher makes when it addresses a notification
        seen.append( ( cosa_interface._dispatcher._resolve_target_user(), message ) )

    async def notify_via_interface( message, **kwargs ):
        await cosa_interface.notify_progress( message )

    async def quick_sleep( seconds, *a, **kw ):
        await REAL_SLEEP( 0.01 )

    job_tester = _job( "interactive.job.tester@test.com" )
    job_rick   = _job( "rick@example.com" )

    with patch.object( cosa_interface._dispatcher, "notify_progress", side_effect=record ), \
         patch.object( voice_io, "notify", side_effect=notify_via_interface ), \
         patch( "asyncio.sleep", quick_sleep ):
        # Start the tester's job, let it get going, then start Rick's: the later start
        # is the one that used to overwrite the shared globals.
        t1 = asyncio.create_task( job_tester._execute_dry_run( voice_io, cosa_interface ) )
        await REAL_SLEEP( 0.005 )
        t2 = asyncio.create_task( job_rick._execute_dry_run( voice_io, cosa_interface ) )
        await asyncio.gather( t1, t2 )

    users = [ u for u, _ in seen ]
    assert len( users ) > 4, "the loop must have found notifications to check"
    assert set( users ) == { "interactive.job.tester@test.com", "rick@example.com" }
    # each user got the same number of notifications: no call was addressed to the other
    assert users.count( "interactive.job.tester@test.com" ) == users.count( "rick@example.com" )
    assert users.count( "rick@example.com" ) > 2
