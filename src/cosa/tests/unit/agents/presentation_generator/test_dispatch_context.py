#!/usr/bin/env python3
"""
Two concurrent presentation generator dry runs keep their own notification identity.
"""

from cosa.agents.presentation_generator.job import PresentationGeneratorJob
from cosa.tests.unit.agents.dispatch_isolation import assert_each_job_keeps_its_own_identity, run_two_jobs


def _job( tag ):
    return PresentationGeneratorJob(
        source_path = f"/io/dr/{tag}.md", user_id = f"id-{tag}",
        user_email = f"{tag}@test.com", session_id = f"s-{tag}", dry_run = True,
    )


def test_concurrent_dry_runs_keep_their_own_identity():
    """Dry run: each job's breadcrumbs carry that job's sender suffix and user."""
    job_a, job_b = _job( "a" ), _job( "b" )
    sent, outcomes = run_two_jobs( job_a, job_b )
    assert not [ o for o in outcomes if isinstance( o, Exception ) ], outcomes
    assert_each_job_keeps_its_own_identity( sent, [ job_a, job_b ], min_rows=5 )


class _FakeOrchestrator:
    """Stands in for the orchestrator; notifies via the real voice_io, then ends cancelled."""

    def __init__( self, source_path, **kw ):
        self.tag = source_path.rsplit( "/", 1 )[ -1 ]

    async def do_all_async( self ):
        import asyncio
        from cosa.agents.presentation_generator import voice_io
        voice_io.reconfigure()
        for step in range( 3 ):
            await voice_io.notify( f"{self.tag} step {step}", priority="low" )
            await asyncio.sleep( 0 )
        return None


def test_concurrent_real_paths_keep_their_own_identity( tmp_path, monkeypatch ):
    """Real path: the orchestrator's notifications carry the job that started it."""
    from unittest.mock import patch
    from cosa.agents.presentation_generator import job as presentation_job
    # The guard and the resolver pin the source inside the project; the test files live in tmp_path.
    monkeypatch.setattr( presentation_job, "source_path_is_inside_the_project", lambda path: True )
    monkeypatch.setattr( presentation_job, "resolve_source_path", lambda path: path )
    jobs = [ ]
    for tag in ( "a", "b" ):
        doc = tmp_path / f"{tag}.md"
        doc.write_text( "outline" )
        jobs.append( PresentationGeneratorJob(
            source_path = str( doc ), user_id = f"id-{tag}",
            user_email = f"{tag}@test.com", session_id = f"s-{tag}",
        ) )
    with patch( "cosa.agents.presentation_generator.orchestrator.PresentationOrchestratorAgent", _FakeOrchestrator ):
        sent, outcomes = run_two_jobs( *jobs )
    assert not [ o for o in outcomes if isinstance( o, Exception ) ], outcomes
    for job, tag in zip( jobs, ( "a", "b" ) ):
        rows = [ row for row in sent if row[ 3 ].startswith( f"{tag}.md step" ) ]
        assert len( rows ) == 3
        for sender_id, target_user, _job_id, message in rows:
            assert target_user == job.user_email, f"{message!r} went to {target_user}"
            assert sender_id.endswith( f"#{job.base_id}" ), f"{message!r} carried sender {sender_id}"
