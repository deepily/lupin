#!/usr/bin/env python3
"""
Two concurrent SWE Team jobs keep their own notification identity.

The dry run's proxy-decision database write is replaced by a failure the job already tolerates.
The live path is driven with the orchestrator replaced by a fake that notifies through the real voice_io.
"""

import asyncio
from unittest.mock import patch

from cosa.agents.swe_team import voice_io
from cosa.agents.swe_team.job import SweTeamJob
from cosa.tests.unit.agents.dispatch_isolation import assert_each_job_keeps_its_own_identity, run_two_jobs


def _job( tag ):
    return SweTeamJob(
        task = f"task {tag}", user_id = f"id-{tag}", user_email = f"{tag}@test.com",
        session_id = f"s-{tag}", dry_run = True, dry_run_phases = 4, dry_run_delay = 0.0,
    )


def test_concurrent_dry_runs_keep_their_own_identity():
    """Each job's phase breadcrumbs carry that job's sender suffix and user."""
    job_a, job_b = _job( "a" ), _job( "b" )
    with patch( "cosa.rest.db.database.get_db", side_effect=RuntimeError( "no database in unit tests" ) ):
        sent, outcomes = run_two_jobs( job_a, job_b )
    assert not [ o for o in outcomes if isinstance( o, Exception ) ], outcomes
    assert_each_job_keeps_its_own_identity( sent, [ job_a, job_b ], min_rows=4 )


class _FakeOrchestrator:
    """Stands in for the orchestrator; notifies in three steps, then reports a failed run."""

    def __init__( self, task_description, job_id, **kw ):
        self.job_id = job_id

    async def run( self ):
        voice_io.reconfigure()
        for step in range( 3 ):
            await voice_io.notify( f"{self.job_id} step {step}", priority="low", job_id=self.job_id )
            await asyncio.sleep( 0 )
        return None


def test_concurrent_live_paths_keep_their_own_identity():
    """Live path: the orchestrator's notifications carry the job that started it."""
    jobs = [ _job( "a" ), _job( "b" ) ]
    for job in jobs: job.dry_run = False
    with patch( "cosa.agents.swe_team.orchestrator.SweTeamOrchestrator", _FakeOrchestrator ), \
         patch.object( SweTeamJob, "_start_notification_client", return_value=None ):
        sent, outcomes = run_two_jobs( *jobs )
    assert [ o for o in outcomes ] == [ "SWE Team task failed or was cancelled." ] * 2
    for job in jobs:
        rows = [ row for row in sent if row[ 2 ] == job.id_hash ]
        assert len( rows ) == 3
        for sender_id, target_user, _job_id, message in rows:
            assert target_user == job.user_email, f"{message!r} went to {target_user}"
            assert sender_id.endswith( f"#{job.base_id}" ), f"{message!r} carried sender {sender_id}"
