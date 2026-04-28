#!/usr/bin/env python3
"""
Unit tests for NotificationRepository.count_by_job_ids() — bulk count helper
added 2026-04-26 (Phase 1 / CJ Flow card-rendering unification).

Tests the bulk notification count used to populate `has_interactions` on the
done/dead/history endpoints accurately, replacing the old `bool(session_id)`
proxy.
"""

from unittest.mock import MagicMock

import pytest

from cosa.rest.db.repositories.notification_repository import NotificationRepository


@pytest.fixture
def mock_session():
    """Mock SQLAlchemy session."""
    return MagicMock()


@pytest.fixture
def repo( mock_session ):
    """NotificationRepository with mocked session."""
    return NotificationRepository( mock_session )


class TestCountByJobIds:
    """Tests for count_by_job_ids() — bulk notification count helper."""

    def test_empty_input_returns_empty_dict( self, repo, mock_session ):
        """Empty job_ids list → empty dict, NO database query issued."""
        result = repo.count_by_job_ids( [] )
        assert result == {}
        # Verify no query was issued
        mock_session.query.assert_not_called()

    def test_returns_zero_for_unknown_job_ids( self, repo, mock_session ):
        """When DB returns no rows, every input id is in the result with 0."""
        # Configure the chained query to return no rows
        mock_session.query.return_value \
            .filter.return_value \
            .group_by.return_value \
            .all.return_value = []

        result = repo.count_by_job_ids( [ "id-a", "id-b", "id-c" ] )

        assert result == { "id-a": 0, "id-b": 0, "id-c": 0 }
        # Verify a query WAS issued (unlike the empty-input case)
        mock_session.query.assert_called_once()

    def test_returns_actual_counts_from_db( self, repo, mock_session ):
        """When DB returns rows, exact counts are surfaced."""
        # Each row mocks a (job_id, count) tuple-like result
        row_a = MagicMock(); row_a.job_id = "id-a"; row_a.count = 5
        row_b = MagicMock(); row_b.job_id = "id-b"; row_b.count = 12
        mock_session.query.return_value \
            .filter.return_value \
            .group_by.return_value \
            .all.return_value = [ row_a, row_b ]

        result = repo.count_by_job_ids( [ "id-a", "id-b", "id-c" ] )

        assert result == { "id-a": 5, "id-b": 12, "id-c": 0 }

    def test_count_is_int( self, repo, mock_session ):
        """Counts are normalized to int (Postgres can return Decimal in some configs)."""
        row = MagicMock(); row.job_id = "id-a"; row.count = 7  # int already
        mock_session.query.return_value \
            .filter.return_value \
            .group_by.return_value \
            .all.return_value = [ row ]

        result = repo.count_by_job_ids( [ "id-a" ] )
        assert result[ "id-a" ] == 7
        assert isinstance( result[ "id-a" ], int )

    def test_idempotent( self, repo, mock_session ):
        """Calling twice with same input returns same result."""
        row = MagicMock(); row.job_id = "id-a"; row.count = 3
        mock_session.query.return_value \
            .filter.return_value \
            .group_by.return_value \
            .all.return_value = [ row ]

        first  = repo.count_by_job_ids( [ "id-a" ] )
        second = repo.count_by_job_ids( [ "id-a" ] )
        assert first == second
        assert first == { "id-a": 3 }
