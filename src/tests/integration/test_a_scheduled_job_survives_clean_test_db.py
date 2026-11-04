"""
A scheduled job is still in the table after clean_test_db, so a restart can restore it.

The pending row in job_history is what startup restores. The fixture used to empty the table
with a bulk truncate. A job scheduled across an integration run was gone by the next restart.
The row is written by the function the queue calls, and the real clean_test_db fixture runs over it.

The restart itself is not performed here. Startup first marks every running row interrupted.
That would mark the running row of this integration run too.
get_restorable_jobs() is the read startup makes next, and it is what is asserted.

The planted row removes itself in a teardown that runs even when the test fails, and the teardown
asserts the row is gone. The row also names no routing command, so a restart would skip it.
"""

from datetime import datetime, timedelta, timezone

import pytest

from cosa.rest import job_persistence as jp
from tests.helpers.job_history_cleanup import planted_job_metadata, planted_job_row, remove_job_row
from tests.helpers.job_history_seed import seed_job_history_records

OWNER_ID    = "cleanup-survival-owner"
OWNER_EMAIL = "cleanup-survival@test.local"


def _future_iso():
    return ( datetime.now( timezone.utc ) + timedelta( days=1 ) ).isoformat()


@pytest.fixture
def a_scheduled_job():
    """
    Plant a pending job scheduled a day ahead, as the queue does, and take it out afterwards.

    Requested first, so pytest builds it before clean_test_db and the real cleanup runs over it.
    """
    with planted_job_row( jp, f"ts-survival-test::{OWNER_ID}", OWNER_ID, planted_job_metadata( _future_iso() ) ) as id_hash:
        yield id_hash


@pytest.fixture
def a_finished_job():
    """A completed job row the cleanup should remove.

    The teardown removes it if the cleanup did not, and asserts it is gone."""
    seeded  = seed_job_history_records( OWNER_ID, OWNER_EMAIL, [ { "id_suffix": "survival-control", "status": "completed" } ] )
    id_hash = seeded[ 0 ][ "id_hash" ]
    try:
        assert jp.get_job_by_id_hash( id_hash ) is not None, "test setup: the control row did not insert"
        yield id_hash
    finally:
        remove_job_row( jp, id_hash )


def test_a_scheduled_job_survives_clean_test_db_and_is_still_restorable( a_scheduled_job, a_finished_job, clean_test_db ):
    row = jp.get_job_by_id_hash( a_scheduled_job )
    assert row is not None, "clean_test_db removed a pending job scheduled in the future"
    assert row[ "status" ] == "pending"
    restorable = { job[ "id_hash" ]: job for job in jp.get_restorable_jobs() }
    assert a_scheduled_job in restorable, "the scheduled job survived but startup would not restore it"
    assert not restorable[ a_scheduled_job ][ "routing_command" ], \
        "the planted row names a routing command, so a restart could run it"


def test_clean_test_db_still_removes_a_finished_job( a_scheduled_job, a_finished_job, clean_test_db ):
    assert jp.get_job_by_id_hash( a_finished_job ) is None, "the control row survived, so the cleanup removed nothing"
