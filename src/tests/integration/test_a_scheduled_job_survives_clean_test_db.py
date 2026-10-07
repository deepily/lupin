"""
A scheduled job is still in the table after clean_test_db, so a restart can restore it.

The pending row in job_history is what startup restores. The fixture used to empty the table
with a bulk truncate. A job scheduled across an integration run was gone by the next restart.
The row is written by the function the queue calls, and the real clean_test_db fixture runs over it.

The restart itself is not performed here. Startup first marks every running row interrupted.
That would mark the running row of this integration run too.
get_restorable_jobs() is the read startup makes next, and it is what is asserted.
"""

from datetime import datetime, timedelta, timezone

import pytest

from cosa.rest import job_persistence as jp
from tests.helpers.job_history_seed import seed_job_history_records

OWNER_ID    = "cleanup-survival-owner"
OWNER_EMAIL = "cleanup-survival@test.local"


def _future_iso():
    return ( datetime.now( timezone.utc ) + timedelta( days=1 ) ).isoformat()


@pytest.fixture
def a_scheduled_job():
    """
    Write a pending test_suite job scheduled a day ahead, as the queue does, and read it back.

    Requested first, so pytest builds it before clean_test_db and the real cleanup runs over it.
    """
    id_hash = f"ts-survival-test::{OWNER_ID}"
    jp.persist_job_created_from_metadata( id_hash, OWNER_ID, {
        "agent_type"      : "test_suite",
        "user_email"      : OWNER_EMAIL,
        "scheduled_at"    : _future_iso(),
        "routing_command" : "agent router go to test suite",
        "question_text"   : "scheduled job that must survive clean_test_db",
    } )
    row = jp.get_job_by_id_hash( id_hash )
    assert row is not None and row[ "status" ] == "pending", f"test setup: the scheduled row did not persist: {row}"
    yield id_hash


@pytest.fixture
def a_finished_job():
    """A completed job row the cleanup is still meant to remove."""
    seeded = seed_job_history_records( OWNER_ID, OWNER_EMAIL, [ { "id_suffix": "survival-control", "status": "completed" } ] )
    id_hash = seeded[ 0 ][ "id_hash" ]
    assert jp.get_job_by_id_hash( id_hash ) is not None, "test setup: the control row did not insert"
    yield id_hash


def test_a_scheduled_job_survives_clean_test_db_and_is_still_restorable( a_scheduled_job, a_finished_job, clean_test_db ):
    row = jp.get_job_by_id_hash( a_scheduled_job )
    assert row is not None, "clean_test_db removed a pending job scheduled in the future"
    assert row[ "status" ] == "pending"
    assert a_scheduled_job in [ job[ "id_hash" ] for job in jp.get_restorable_jobs() ], \
        "the scheduled job survived but startup would not restore it"


def test_clean_test_db_still_removes_a_finished_job( a_scheduled_job, a_finished_job, clean_test_db ):
    assert jp.get_job_by_id_hash( a_finished_job ) is None, "the control row survived, so the cleanup removed nothing"
