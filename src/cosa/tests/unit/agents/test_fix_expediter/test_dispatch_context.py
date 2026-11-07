#!/usr/bin/env python3
"""
Two concurrent test fix expediter jobs keep their notification identity.

The job has no dispatcher of its own.
It sets identity on the bug fix expediter's interface module and notifies through that module's dispatcher.
The orchestrator is replaced by a fake that notifies through the real voice_io and then fails,
which also exercises the job's error notification.
"""

import asyncio
from unittest.mock import patch

import cosa.agents.test_fix_expediter.job as tfe_job_module
from cosa.agents.bug_fix_expediter import voice_io
from cosa.tests.unit.agents.dispatch_isolation import run_two_jobs


class _FakeOrchestrator:
    """Notifies in three steps, yielding to the other job between them, then fails."""

    def __init__( self, job_id, **kw ):
        self.job_id = job_id

    async def run_phase0_cluster( self ):
        voice_io.reconfigure()
        for step in range( 3 ):
            await voice_io.notify( f"{self.job_id} step {step}", priority="low", job_id=self.job_id )
            await asyncio.sleep( 0 )
        raise RuntimeError( "stop here" )


def _job( tag ):
    return tfe_job_module.TestFixExpediterJob(
        remediation_snapshot_path = f"snap-{tag}.json", source_test_suite_job_id = f"ts-{tag}",
        user_id = f"id-{tag}", user_email = f"{tag}@test.com", session_id = f"s-{tag}",
    )


def test_concurrent_jobs_keep_their_own_identity():
    """Each job's steps and its error notification carry that job's sender suffix and user."""
    jobs = [ _job( "a" ), _job( "b" ) ]
    with patch( "cosa.agents.test_fix_expediter.snapshot_loader.load_from_path", return_value=object() ), \
         patch( "cosa.agents.test_fix_expediter.orchestrator.TFEOrchestrator", _FakeOrchestrator ):
        sent, outcomes = run_two_jobs( *jobs )
    assert [ str( o ) for o in outcomes ] == [ "stop here", "stop here" ]
    for job in jobs:
        rows = [ row for row in sent if row[ 2 ] == job.id_hash ]
        assert len( rows ) == 4, "three steps and the error notification"
        for sender_id, target_user, _job_id, message in rows:
            assert target_user == job.user_email, f"{message!r} went to {target_user}"
            assert sender_id.endswith( f"#{job.base_id}" ), f"{message!r} carried sender {sender_id}"
