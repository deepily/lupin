"""
Row-level cleanup of job_history for the test-database fixtures.

Both clean_test_db fixtures used to empty this table with a bulk truncate. A job scheduled on :8000
keeps a pending row here until the server restarts and restores it. The first test that used the
fixture removed that row, and the job never ran.

The cleanup now keeps the rows that startup would restore for a future schedule.
Those are the pending ones whose scheduled_at is still in the future.

This module also holds the two helpers a test uses to plant a row and to take it out again.
"""

from contextlib import contextmanager

from sqlalchemy import text

from cosa.rest.job_persistence import _is_future_scheduled

LOCK_WAIT = "15s"


def clean_job_history( conn ):
    """
    Delete every job_history row except the pending ones scheduled in the future.

    The table is locked first, so the server cannot persist a new job between the read of the
    kept ids and the delete. Its write waits for the commit and then lands, and the job survives.

    Requires:
        - conn is an open SQLAlchemy connection to the test database, inside a transaction

    Ensures:
        - rows that are pending with a scheduled_at in the future are left in place
        - every other row is deleted, including pending rows with no or a past scheduled_at
        - the future test is the one the server applies (job_persistence._is_future_scheduled)
        - a lock that cannot be had within LOCK_WAIT raises instead of hanging
        - returns the list of id_hash values that were kept
    """
    conn.execute( text( f"SET LOCAL lock_timeout = '{LOCK_WAIT}'" ) )
    conn.execute( text( "LOCK TABLE job_history IN SHARE ROW EXCLUSIVE MODE" ) )
    candidates = conn.execute( text(
        "SELECT id_hash, metadata_json->>'scheduled_at' FROM job_history WHERE status = 'pending'"
    ) ).fetchall()
    keep = [ id_hash for id_hash, scheduled_at in candidates if scheduled_at and _is_future_scheduled( scheduled_at ) ]
    conn.execute( text( "DELETE FROM job_history WHERE id_hash <> ALL( CAST( :keep AS varchar[] ) )" ), { "keep": keep } )
    return keep


def planted_job_metadata( scheduled_at ):
    """
    The metadata of a planted job row: scheduled ahead, and unable to run if it survives.

    It names no routing command, and the restore path skips a row without one before it builds a
    job. Its agent type belongs to no job. The cleanup reads neither, so the test still proves
    what it is for: that a pending row scheduled ahead is kept and returned for restore.

    Requires:
        - scheduled_at is an ISO timestamp string in the future

    Ensures:
        - returns a dict with agent_type and scheduled_at, and no routing_command
    """
    return { "agent_type": "cleanup_survival_marker", "scheduled_at": scheduled_at }


def remove_job_row( persistence, id_hash ):
    """
    Delete one job_history row if it is there, then assert it is gone.

    Requires:
        - persistence offers delete_job_history( id_hash ) and get_job_by_id_hash( id_hash )

    Ensures:
        - returns None when the row is absent afterwards
        - raises AssertionError naming the row when it is still there, so a leftover cannot go unseen
    """
    persistence.delete_job_history( id_hash )
    left = persistence.get_job_by_id_hash( id_hash )
    assert left is None, f"the test row {id_hash} is still in job_history after its teardown; a restart could restore it"


@contextmanager
def planted_job_row( persistence, id_hash, user_id, metadata ):
    """
    Plant one pending job row, yield its id, and always remove it afterwards.

    Requires:
        - persistence offers persist_job_created_from_metadata, get_job_by_id_hash and delete_job_history
        - metadata is a dict such as planted_job_metadata returns

    Ensures:
        - the row exists and is pending before the body runs, or an AssertionError says it did not persist
        - the row is gone when the block exits, whether the body passed, failed or never started
        - a row that cannot be removed raises AssertionError at exit
    """
    persistence.persist_job_created_from_metadata( id_hash, user_id, metadata )
    try:
        row = persistence.get_job_by_id_hash( id_hash )
        assert row is not None and row[ "status" ] == "pending", f"test setup: the planted row did not persist: {row}"
        yield id_hash
    finally:
        remove_job_row( persistence, id_hash )
