#!/usr/bin/env python3
"""
Two concurrent test suite jobs keep their own notification identity.

Only the dry-run path is driven. The real path starts pytest subprocesses and database resets,
and it sets the identity with the same two lines the dry run does.
"""

import cosa.agents.test_suite.job as suite_job_module
from cosa.tests.unit.agents.dispatch_isolation import assert_each_job_keeps_its_own_identity, run_two_jobs


def _job( tag ):
    return suite_job_module.TestSuiteJob(
        test_types = [ "unit", "smoke" ], user_id = f"id-{tag}",
        user_email = f"{tag}@test.com", session_id = f"s-{tag}", dry_run = True,
    )


def test_concurrent_dry_runs_keep_their_own_identity():
    """Each job's breadcrumbs, spread over several pauses, keep its sender suffix and user."""
    job_a, job_b = _job( "a" ), _job( "b" )
    sent, outcomes = run_two_jobs( job_a, job_b )
    assert not [ o for o in outcomes if isinstance( o, Exception ) ], outcomes
    assert_each_job_keeps_its_own_identity( sent, [ job_a, job_b ], min_rows=4 )
