"""
Test helpers for job_history: plant a row, and take it out again.

The cleanup rule itself is cosa.rest.job_history_cleanup, which the fixtures and the sweep share.
It is re-exported here so the fixtures keep their import.
"""

from contextlib import contextmanager

from cosa.rest.job_history_cleanup import LOCK_WAIT, clean_job_history  # noqa: F401  the rule lives in cosa.rest

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
