#!/usr/bin/env python3
"""
Two concurrent SWE Team jobs keep their own notification identity.

Only the dry-run path is driven; the live path hands the same identity to an orchestrator that needs real model clients.
The proxy-decision database write at the end of a dry run is replaced by a failure the job already tolerates.
"""

from unittest.mock import patch

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
