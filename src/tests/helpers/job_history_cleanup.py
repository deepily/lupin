"""
Row-level cleanup of job_history for the test-database fixtures.

Both clean_test_db fixtures used to empty this table with a bulk truncate. A job scheduled on :8000
keeps a pending row here until the server restarts and restores it. The first test that used the
fixture removed that row, and the job never ran.

The cleanup now keeps the rows that startup would restore for a future schedule.
Those are the pending ones whose scheduled_at is still in the future.
"""

from sqlalchemy import text

from cosa.rest.job_persistence import _is_future_scheduled


def clean_job_history( conn ):
    """
    Delete every job_history row except the pending ones scheduled in the future.

    Requires:
        - conn is an open SQLAlchemy connection to the test database, inside a transaction

    Ensures:
        - rows that are pending with a scheduled_at in the future are left in place
        - every other row is deleted, including pending rows with no or a past scheduled_at
        - the future test is the one the server applies (job_persistence._is_future_scheduled)
        - returns the list of id_hash values that were kept
    """
    candidates = conn.execute( text(
        "SELECT id_hash, metadata_json->>'scheduled_at' FROM job_history WHERE status = 'pending'"
    ) ).fetchall()
    keep = [ id_hash for id_hash, scheduled_at in candidates if scheduled_at and _is_future_scheduled( scheduled_at ) ]
    conn.execute( text( "DELETE FROM job_history WHERE id_hash <> ALL( CAST( :keep AS varchar[] ) )" ), { "keep": keep } )
    return keep
