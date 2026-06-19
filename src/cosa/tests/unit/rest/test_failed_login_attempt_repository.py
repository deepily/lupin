"""
Unit tests for cosa.rest.db.repositories.failed_login_attempt_repository.

SQLAlchemy session mocked ( chainable query ); inherited BaseRepository.create mocked.
No real DB. Covers record + recent-by-email/ip + count + delete + cleanup.
"""

import unittest
from unittest.mock import patch, MagicMock

from cosa.rest.db.repositories.failed_login_attempt_repository import (
    FailedLoginAttemptRepository,
)


def _repo():
    """
    Ensures:
        - Returns ( repo, session, query ) with a chainable query mock
    """
    session = MagicMock()
    q = session.query.return_value
    q.filter.return_value = q
    return FailedLoginAttemptRepository( session ), session, q


class TestFailedLoginAttemptRepository( unittest.TestCase ):
    """
    Tests for FailedLoginAttemptRepository.

    Ensures:
        - Recording lowercases email; queries/counts/deletes delegate correctly
    """

    def test_record_attempt_lowercases_email( self ):
        """
        Ensures:
            - record_attempt delegates to base.create with a lowercased email
        """
        repo, _, _ = _repo()
        with patch.object( repo, "create", return_value="created" ) as mock_create:
            self.assertEqual( repo.record_attempt( "USER@Example.com", "1.2.3.4" ), "created" )
            _, kwargs = mock_create.call_args
            self.assertEqual( kwargs[ "email" ], "user@example.com" )
            self.assertEqual( kwargs[ "ip_address" ], "1.2.3.4" )

    def test_get_recent_by_email( self ):
        """
        Ensures:
            - Returns ordered attempts within the window
        """
        repo, _, q = _repo()
        q.order_by.return_value.all.return_value = [ "a1" ]
        self.assertEqual( repo.get_recent_attempts_by_email( "u@x.com" ), [ "a1" ] )

    def test_get_recent_by_ip( self ):
        """
        Ensures:
            - Returns ordered attempts within the window ( by IP )
        """
        repo, _, q = _repo()
        q.order_by.return_value.all.return_value = [ "a1", "a2" ]
        self.assertEqual( repo.get_recent_attempts_by_ip( "1.2.3.4" ), [ "a1", "a2" ] )

    def test_count_recent_by_email( self ):
        """
        Ensures:
            - Returns the COUNT result
        """
        repo, _, q = _repo()
        q.count.return_value = 4
        self.assertEqual( repo.count_recent_by_email( "u@x.com" ), 4 )

    def test_count_recent_by_ip( self ):
        """
        Ensures:
            - Returns the COUNT result ( by IP )
        """
        repo, _, q = _repo()
        q.count.return_value = 9
        self.assertEqual( repo.count_recent_by_ip( "1.2.3.4" ), 9 )

    def test_delete_by_email( self ):
        """
        Ensures:
            - Bulk-deletes by email and returns the count
        """
        repo, session, q = _repo()
        q.delete.return_value = 2
        self.assertEqual( repo.delete_by_email( "u@x.com" ), 2 )
        session.flush.assert_called_once()

    def test_cleanup_old( self ):
        """
        Ensures:
            - Bulk-deletes old attempts and returns the count
        """
        repo, session, q = _repo()
        q.delete.return_value = 11
        self.assertEqual( repo.cleanup_old( days_old=30 ), 11 )
        session.flush.assert_called_once()


if __name__ == "__main__":
    unittest.main()
