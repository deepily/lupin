"""
The rule for which job_history rows survive a cleanup of the test database.

A job scheduled on :8000 keeps a pending row here until the server restarts and restores it. A bulk
truncate of the table removes that row and the job never runs. Three places empty the table: the two
clean_test_db fixtures and the between-suites reset of a multi-suite sweep. All three call this one
function, so the rule lives once.

It keeps the rows that startup would restore for a future schedule.
Those are the pending ones whose scheduled_at is still in the future.
"""

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
