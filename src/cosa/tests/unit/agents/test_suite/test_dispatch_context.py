#!/usr/bin/env python3
"""
Two concurrent test suite jobs keep their own notification identity.

The real path is driven with its heavy collaborators stubbed: the pytest subprocess, the
shared-database preflight and reset, the lineage token and the tier attestation.
"""

from unittest.mock import patch

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


_STUBBED = ( "_preflight_assert_exclusive_test_db", "_reset_state_between_suites", "_attest_tier_run" )


def test_concurrent_real_paths_keep_their_own_identity():
    """Real path: the start, per-suite and result notifications carry the job that sent them."""
    jobs = [ _job( "a" ), _job( "b" ) ]
    quiet_suite = { "passed" : 1, "failed" : 0, "errors" : 0, "skipped" : 0, "exit_code" : 0, "log_path" : None, "duration" : 0.0 }
    stubs = [ patch.object( suite_job_module.TestSuiteJob, name ) for name in _STUBBED ]
    stubs.append( patch.object( suite_job_module.TestSuiteJob, "_issue_suite_token", return_value=None ) )
    stubs.append( patch.object( suite_job_module.TestSuiteJob, "_run_suite", return_value=quiet_suite ) )
    for stub in stubs: stub.start()
    try:
        for job in jobs: job.dry_run = False
        sent, outcomes = run_two_jobs( *jobs )
    finally:
        for stub in stubs: stub.stop()
    assert not [ o for o in outcomes if isinstance( o, BaseException ) ], outcomes
    for job in jobs:
        rows = [ row for row in sent if row[ 1 ] == job.user_email or row[ 0 ].endswith( f"#{job.base_id}" ) ]
        assert len( rows ) >= 5, "start, two suite starts and two results"
        for sender_id, target_user, _job_id, message in rows:
            assert target_user == job.user_email, f"{message!r} for {job.user_email} went to {target_user}"
            assert sender_id.endswith( f"#{job.base_id}" ), f"{message!r} carried sender {sender_id}"
    assert sum( 1 for row in sent if row[ 1 ] is None ) == 0
