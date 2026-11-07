#!/usr/bin/env python3
"""
Two concurrent bug fix expediter jobs keep their own notification identity.
"""

from unittest.mock import patch

import pytest

from cosa.agents.bug_fix_expediter.job import BugFixExpediterJob
from cosa.tests.unit.agents.dispatch_isolation import assert_each_job_keeps_its_own_identity, run_two_jobs


def _job( tag, dry_run ):
    job = BugFixExpediterJob(
        dead_job_id = f"dead-{tag}", user_id = f"id-{tag}",
        user_email = f"{tag}@test.com", session_id = f"s-{tag}", dry_run = dry_run,
    )
    job._write_final_report = lambda **kw: None
    return job


@pytest.mark.parametrize( "dry_run", [ False, True ], ids=[ "real-path", "dry-run" ] )
def test_concurrent_jobs_keep_their_own_identity( dry_run ):
    """Both paths end in the not-found notification after a pause; it must be the job's own."""
    job_a, job_b = _job( "a", dry_run ), _job( "b", dry_run )
    with patch( "cosa.agents.bug_fix_expediter.dead_job_packager.package_dead_job", return_value=None ):
        sent, outcomes = run_two_jobs( job_a, job_b )
    assert not [ o for o in outcomes if isinstance( o, Exception ) ], outcomes
    assert_each_job_keeps_its_own_identity( sent, [ job_a, job_b ], min_rows=2 )
