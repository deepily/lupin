"""
GET /api/job-history learns "Not Mine" (row 83c3ff74, Rick's ruling 2026-09-10 ~17:40 EDT).

WHAT CHANGED. The admin's "!self" filter used to be refused with a 400, because
`query_job_history` could only filter by user_id EQUALITY. The multiplexer jobs pane
needs legacy's three views — Mine / Not Mine / All Users — so the store now takes an
`exclude_user_id` and the router hands it the caller's own uid.

WHY THE QUERY TESTS RUN ON REAL ROWS. The older `query_job_history` tests patch the
session with a MagicMock, which returns the same empty page whatever WHERE clause was
built — so they cannot see an exclusion that is missing, inverted, or applied to the
wrong column. These tests build the real `job_history` table in an in-memory SQLite
database, insert rows owned by three accounts, and read back which rows came out.

THE PARITY RULE BEING PINNED. `/api/get-queue/{q}?user_filter=!self` answers from
`FifoQueue.get_jobs_excluding_user`, which drops only the caller's own jobs and keeps
every other job — including one with no real owner. `job_history.user_id` is NOT NULL,
and an ownerless job is persisted as "unknown" (`persist_job_created_from_metadata`),
so the matching SQL is a plain `user_id != <caller>`, and the "unknown" row must stay.

Generated on: 2026-09-10
"""

import asyncio
import contextlib
import unittest
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from sqlalchemy import JSON, MetaData, create_engine, insert
from sqlalchemy.orm import sessionmaker

from cosa.rest.postgres_models import JobHistory
from cosa.rest.routers.queues import get_job_history


ADMIN     = { "uid" : "admin_0001",    "roles" : [ "admin" ] }
REGULAR   = { "uid" : "user_931e9dae", "roles" : [ "user" ] }
OTHER_UID = "user_50c73ba7"

# Owner of every row in the fixture. Chosen so each view returns a DIFFERENT set:
# own = 2 rows, not-mine = 2 rows, all = 4 rows — no two views can pass on the same data.
ROWS = [
    ( "job-admin-1",   ADMIN[ "uid" ] ),
    ( "job-admin-2",   ADMIN[ "uid" ] ),
    ( "job-other-1",   OTHER_UID ),
    ( "job-unknown-1", "unknown" ),
]


@contextlib.contextmanager
def _sqlite_job_history():
    """
    Yield a `get_db` stand-in backed by an in-memory SQLite `job_history` table.

    Requires:
        - JobHistory's table is portable apart from its JSONB column

    Ensures:
        - the table is built from a COPY of JobHistory's table with JSONB swapped for
          JSON, so nothing global (no dialect compile hook) is changed for other tests
        - ROWS are inserted, and the notifications lookup is stubbed to "none"
        - `cosa.rest.job_persistence.get_db` yields a session on that database
    """
    engine   = create_engine( "sqlite://" )
    metadata = MetaData()
    table    = JobHistory.__table__.to_metadata( metadata )
    table.c.metadata_json.type = JSON()
    metadata.create_all( engine )

    with engine.begin() as conn:
        for id_hash, user_id in ROWS:
            conn.execute( insert( table ).values(
                id_hash  = id_hash,
                job_type = "claude_code",
                user_id  = user_id,
                status   = "completed",
            ) )

    Session = sessionmaker( bind=engine )

    @contextlib.contextmanager
    def _get_db():
        session = Session()
        try:
            yield session
        finally:
            session.close()

    with patch( "cosa.rest.job_persistence.get_db", _get_db ), \
         patch( "cosa.rest.job_persistence._count_notifications_for_jobs", lambda session, ids: { } ):
        yield

    engine.dispose()


def _ids( result ):
    return sorted( job[ "id_hash" ] for job in result[ "jobs" ] )


def _call( current_user, user_filter ):
    """Drive the handler directly, passing every Query-defaulted parameter explicitly."""
    return asyncio.run( get_job_history(
        current_user = current_user,
        status       = None,
        job_type     = None,
        limit        = 20,
        offset       = 0,
        days         = None,
        exclude_ids  = None,
        user_filter  = user_filter
    ) )


class TestTheStoreCanExcludeOneAccount( unittest.TestCase ):
    """`query_job_history( exclude_user_id=... )` against real rows."""

    def test_the_fixture_is_what_the_other_tests_assume( self ):
        """Positive control: with no filter all four rows come back, so a smaller set below is the filter's doing."""
        from cosa.rest.job_persistence import query_job_history

        with _sqlite_job_history():
            result = query_job_history()

        assert result[ "total" ] == 4
        assert _ids( result ) == sorted( id_hash for id_hash, _ in ROWS )

    def test_excluding_the_caller_drops_only_the_callers_rows( self ):
        from cosa.rest.job_persistence import query_job_history

        with _sqlite_job_history():
            result = query_job_history( exclude_user_id=ADMIN[ "uid" ] )

        assert _ids( result ) == [ "job-other-1", "job-unknown-1" ]
        assert result[ "total" ] == 2

    def test_an_ownerless_job_survives_the_exclusion_like_the_live_queue( self ):
        """Parity with FifoQueue.get_jobs_excluding_user, which keeps every job it does not track for the caller."""
        from cosa.rest.job_persistence import query_job_history

        with _sqlite_job_history():
            result = query_job_history( exclude_user_id=ADMIN[ "uid" ] )

        assert "job-unknown-1" in _ids( result )

    def test_equality_filtering_is_unchanged( self ):
        from cosa.rest.job_persistence import query_job_history

        with _sqlite_job_history():
            result = query_job_history( user_id=ADMIN[ "uid" ] )

        assert _ids( result ) == [ "job-admin-1", "job-admin-2" ]
        assert result[ "total" ] == 2

    def test_the_exclusion_is_anded_with_the_other_filters( self ):
        """A second filter still narrows: exclusion is one more AND clause, not a replacement."""
        from cosa.rest.job_persistence import query_job_history

        with _sqlite_job_history():
            result = query_job_history( exclude_user_id=ADMIN[ "uid" ], exclude_ids=[ "job-other-1" ] )

        assert _ids( result ) == [ "job-unknown-1" ]
        assert result[ "total" ] == 1


class TestTheRouterHandsNotMineToTheStore( unittest.TestCase ):
    """What `get_job_history` asks the store for, per filter word."""

    def _capture( self, current_user, user_filter ):
        capture = { }

        def _fake_query( **kwargs ):
            capture.update( kwargs )
            return { "jobs" : [], "total" : 0 }

        with patch( "cosa.rest.job_persistence.query_job_history", _fake_query ):
            body = _call( current_user, user_filter )
        return capture, body

    def test_admin_not_mine_asks_to_exclude_the_callers_uid( self ):
        capture, body = self._capture( ADMIN, "!self" )

        assert capture[ "exclude_user_id" ] == ADMIN[ "uid" ]
        assert capture[ "user_id" ] is None
        assert body[ "filtered_by" ] == "!" + ADMIN[ "uid" ]

    def test_admin_own_is_an_equality_filter_with_no_exclusion( self ):
        capture, body = self._capture( ADMIN, ADMIN[ "uid" ] )

        assert capture[ "user_id" ] == ADMIN[ "uid" ]
        assert capture[ "exclude_user_id" ] is None
        assert body[ "filtered_by" ] == ADMIN[ "uid" ]

    def test_admin_all_has_no_exclusion( self ):
        capture, body = self._capture( ADMIN, "*" )

        assert capture[ "user_id" ] is None
        assert capture[ "exclude_user_id" ] is None
        assert body[ "filtered_by" ] == "all"

    def test_the_bare_default_has_no_exclusion( self ):
        """No param still means what it meant: admin sees every user, and nothing is excluded."""
        capture, body = self._capture( ADMIN, None )

        assert capture[ "user_id" ] is None
        assert capture[ "exclude_user_id" ] is None
        assert body[ "filtered_by" ] == "all"

    def test_a_regular_user_asking_for_not_mine_is_still_refused_403( self ):
        with pytest.raises( HTTPException ) as exc:
            self._capture( REGULAR, "!self" )

        assert exc.value.status_code == 403


class TestNotMineEndToEndThroughTheHandler( unittest.TestCase ):
    """The layer the pane enters at: the real handler over the real query, on real rows."""

    def test_admin_not_mine_returns_other_accounts_jobs_and_none_of_their_own( self ):
        with _sqlite_job_history():
            body = _call( ADMIN, "!self" )

        assert _ids( body ) == [ "job-other-1", "job-unknown-1" ]
        assert body[ "total" ] == 2

    def test_the_three_views_are_three_different_sets( self ):
        """Mine, Not Mine and All Users partition the fixture: own + not-mine == all, with no overlap."""
        with _sqlite_job_history():
            own      = _ids( _call( ADMIN, ADMIN[ "uid" ] ) )
            not_mine = _ids( _call( ADMIN, "!self" ) )
            every    = _ids( _call( ADMIN, "*" ) )

        assert own == [ "job-admin-1", "job-admin-2" ]
        assert set( own ).isdisjoint( not_mine )
        assert sorted( own + not_mine ) == every


if __name__ == "__main__":
    unittest.main()
