"""
Row 4cbd4858 — the id the test harness sends as `parent_id_hash` is the id the correctness-ask
skip resolves, end to end, with the real classes at both ends.

The chain: TestSuiteJob exports its own id_hash as LUPIN_TEST_MONOPOLIZE_PARENT_ID (and as
LUPIN_TEST_SUITE_JOB_ID, the same value) -> v2_eval's client echoes it as `parent_id_hash` on
every /api/v2/ask -> the queued executor stamps it as the ask job's `spawned_by_id_hash` ->
`RunningFifoQueue._lineage_traces_to_test_suite` finds the suite job in the running queue and
reads `job_type == "test_suite"`. Each link is pinned below; a break in any one means the skip
never fires and test_v2_eval_live goes back to waiting 60s per ask.
"""

import threading
from pathlib import Path

import pytest

import cosa.utils.util as cu
from cosa.agents.test_suite.job import TestSuiteJob
from cosa.rest.running_fifo_queue import RunningFifoQueue

JOB_SOURCE = ( Path( cu.get_project_root() ) / "src/cosa/agents/test_suite/job.py" ).read_text( encoding="utf-8" )


def _queue_holding( *jobs ):
    """A RunningFifoQueue with only what the lineage walk reads: its lock and its id map."""
    queue            = object.__new__( RunningFifoQueue )
    queue._lock      = threading.RLock()
    queue.queue_dict = { job.id_hash: job for job in jobs }
    return queue


class _Ask:
    """An ask job as the executor leaves it: lineage stamped from the request's parent_id_hash."""
    def __init__( self, parent_id_hash ):
        self.id_hash            = "ask-1"
        self.spawned_by_id_hash = parent_id_hash


def _suite_job():
    return TestSuiteJob( test_types=[ "integration" ], user_id="u", user_email="e@x.y", session_id="wise penguin" )


@pytest.mark.parametrize( "env_name", [ "LUPIN_TEST_MONOPOLIZE_PARENT_ID", "LUPIN_TEST_SUITE_JOB_ID" ] )
def test_the_runner_exports_its_own_id_hash_under_both_names( env_name ):
    assert f'"{env_name}" : self.id_hash' in JOB_SOURCE, env_name


def test_the_suite_jobs_exported_id_is_the_id_the_walk_resolves():
    suite = _suite_job()
    queue = _queue_holding( suite )
    assert suite.job_type == "test_suite"
    assert queue._lineage_traces_to_test_suite( _Ask( suite.id_hash ) ) is True


def test_a_different_id_does_not_resolve():
    """Negative control: the walk keys on the exported id, not on any test-suite job being present."""
    suite = _suite_job()
    assert _queue_holding( suite )._lineage_traces_to_test_suite( _Ask( "ts-00000000" ) ) is False
