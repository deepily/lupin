#!/usr/bin/env python3
"""
Unit tests for the reaped-sender exclusion in
NotificationRepository.get_sender_last_activities_visible (bug ee59d5ed, Change 1).

The operator focus bar is notification-row-derived: get_sender_last_activities_visible
GROUP BYs the Notification table by sender_id. A reaped session must DURABLY drop off
that roster across a page refresh — but WITHOUT destroying its history (is_hidden=True
would over-hide, since every history/conversation getter filters is_hidden==False). So
the durable, history-safe eviction is a ROSTER-query exclusion: any sender_id that has a
persisted `type="session_reaped"` marker row is excluded from the roster only.

The Notification ORM model carries Postgres-only column types (JSONB) that do not compile
on SQLite, so — matching the repository-test convention in this suite
(test_notification_repository_count.py) — these unit tests drive a MOCKED session to prove
the exclusion subquery is CONSTRUCTED and APPLIED, and cover the new lines. The load-
bearing roster-ABSENT-but-history-PRESENT correctness (AC-2 + AC-3) is proven against a
REAL Postgres DB in the :8000-scheduled integration test (see the design doc §9).
"""
import uuid
from unittest.mock import MagicMock

import pytest

from cosa.rest.db.repositories.notification_repository import NotificationRepository


def _chainable_query( rows ):
    """A query mock whose .filter/.group_by/.order_by all return itself, so an
    arbitrary number of chained .filter() calls resolve, and .all() yields rows."""
    q = MagicMock()
    q.filter.return_value   = q
    q.group_by.return_value = q
    q.order_by.return_value = q
    q.all.return_value      = rows
    return q


@pytest.fixture
def mock_session():
    return MagicMock()


@pytest.fixture
def repo( mock_session ):
    return NotificationRepository( mock_session )


class TestReapedSenderExclusion:

    def test_builds_reaped_exclusion_subquery( self, repo, mock_session ):
        # The reaped-exclusion issues a SECOND session.query(...) (the subquery of
        # reaped sender_ids) beyond the main aggregate query. Two query() calls is
        # the signal that the exclusion subquery was constructed.
        mock_session.query.return_value = _chainable_query( [] )

        repo.get_sender_last_activities_visible( recipient_id=uuid.uuid4() )

        assert mock_session.query.call_count == 2, \
            "expected the main aggregate query + the reaped-sender exclusion subquery"

    def test_applies_exclusion_filter_to_the_roster_query( self, repo, mock_session ):
        # The main query must gain a .filter() for the ~sender_id.in_(reaped) exclusion
        # (on top of the recipient filter). A chainable mock lets us count the filters.
        q = _chainable_query( [] )
        mock_session.query.return_value = q

        repo.get_sender_last_activities_visible( recipient_id=uuid.uuid4() )

        # recipient filter + reaped-exclusion filter = at least 2 filter() calls,
        # and the query is grouped/ordered exactly once.
        assert q.filter.call_count >= 2
        q.group_by.assert_called_once()
        q.order_by.assert_called_once()

    def test_maps_rows_to_roster_dicts( self, repo, mock_session ):
        # The return-shape processing runs after the exclusion (covers those lines).
        row = MagicMock()
        row.sender_id          = "claude.code@lupin.deepily.ai#a1b2c3d4"
        row.last_activity      = "2026-07-15T21:00:00+00:00"
        row.notification_count = 4
        row.new_count          = 2
        mock_session.query.return_value = _chainable_query( [ row ] )

        result = repo.get_sender_last_activities_visible( recipient_id=uuid.uuid4() )

        assert result == [ {
            "sender_id"     : "claude.code@lupin.deepily.ai#a1b2c3d4",
            "last_activity" : "2026-07-15T21:00:00+00:00",
            "count"         : 4,
            "new_count"     : 2,
        } ]

    def test_new_count_none_coerced_to_zero( self, repo, mock_session ):
        # func.sum over zero matching rows yields NULL → new_count None → coerced 0.
        row = MagicMock()
        row.sender_id          = "s#1"
        row.last_activity      = None
        row.notification_count = 0
        row.new_count          = None
        mock_session.query.return_value = _chainable_query( [ row ] )

        result = repo.get_sender_last_activities_visible( recipient_id=uuid.uuid4() )

        assert result[ 0 ][ "new_count" ] == 0

    def test_include_hidden_still_applies_reaped_exclusion( self, repo, mock_session ):
        # Even with include_hidden=True (skips the is_hidden filter), the reaped
        # exclusion still fires — a reaped sender is off the roster regardless of the
        # hidden-count toggle. Two query() calls confirms the subquery was built.
        mock_session.query.return_value = _chainable_query( [] )

        repo.get_sender_last_activities_visible( recipient_id=uuid.uuid4(), include_hidden=True )

        assert mock_session.query.call_count == 2

    def test_exclude_own_jobs_path_still_applies_reaped_exclusion( self, repo, mock_session ):
        # The "not mine" filter branch composes with the reaped exclusion.
        mock_session.query.return_value = _chainable_query( [] )

        repo.get_sender_last_activities_visible(
            recipient_id=uuid.uuid4(), exclude_job_ids=[ "job-a", "job-b" ]
        )

        assert mock_session.query.call_count == 2


if __name__ == "__main__":
    raise SystemExit( pytest.main( [ __file__, "-v" ] ) )
