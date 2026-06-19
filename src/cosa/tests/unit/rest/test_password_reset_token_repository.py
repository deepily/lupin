"""
Unit tests for cosa.rest.db.repositories.password_reset_token_repository.

Mirrors the email-verification token repo ( same token-lifecycle contract ) but with a
1-hour default expiry. SQLAlchemy session mocked ( chainable query ) + inherited
BaseRepository.create mocked; no real DB.

Covers: create_token · get_by_token · mark_used · is_valid · cleanup_expired.
"""

import unittest
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock

from cosa.rest.db.repositories.password_reset_token_repository import (
    PasswordResetTokenRepository,
)


def _repo():
    """
    Ensures:
        - Returns ( repo, mock_session )
    """
    session = MagicMock()
    return PasswordResetTokenRepository( session ), session


class TestPasswordResetTokenRepository( unittest.TestCase ):
    """
    Tests for PasswordResetTokenRepository.

    Ensures:
        - 1-hour-default token creation + lookup/mark/validity/cleanup contract
    """

    def test_create_token_delegates_with_one_hour_expiry( self ):
        """
        Ensures:
            - create_token delegates to base.create with used=False + ~1h expiry
        """
        repo, _ = _repo()
        with patch.object( repo, "create", return_value="created" ) as mock_create:
            uid = uuid.uuid4()
            result = repo.create_token( token="tok", user_id=uid )
            self.assertEqual( result, "created" )
            _, kwargs = mock_create.call_args
            self.assertEqual( kwargs[ "token" ], "tok" )
            self.assertEqual( kwargs[ "user_id" ], uid )
            self.assertFalse( kwargs[ "used" ] )
            delta = kwargs[ "expires_at" ] - datetime.now( timezone.utc )
            self.assertTrue( timedelta( minutes=59 ) < delta <= timedelta( hours=1 ) )

    def test_get_by_token( self ):
        """
        Ensures:
            - get_by_token returns the first query result
        """
        repo, session = _repo()
        session.query.return_value.filter.return_value.first.return_value = "token_obj"
        self.assertEqual( repo.get_by_token( "tok" ), "token_obj" )

    def test_mark_used_found( self ):
        """
        Ensures:
            - Existing token -> used True + flush + True
        """
        repo, session = _repo()
        token_obj = MagicMock()
        session.query.return_value.filter.return_value.first.return_value = token_obj
        self.assertTrue( repo.mark_used( "tok" ) )
        self.assertTrue( token_obj.used )
        session.flush.assert_called_once()

    def test_mark_used_not_found( self ):
        """
        Ensures:
            - Missing token -> False
        """
        repo, session = _repo()
        session.query.return_value.filter.return_value.first.return_value = None
        self.assertFalse( repo.mark_used( "tok" ) )

    def test_is_valid_true( self ):
        """
        Ensures:
            - Existing, unused, unexpired token -> True
        """
        repo, session = _repo()
        token_obj = MagicMock( used=False, expires_at=datetime.now( timezone.utc ) + timedelta( minutes=30 ) )
        session.query.return_value.filter.return_value.first.return_value = token_obj
        self.assertTrue( repo.is_valid( "tok" ) )

    def test_is_valid_missing( self ):
        """
        Ensures:
            - Missing token -> False
        """
        repo, session = _repo()
        session.query.return_value.filter.return_value.first.return_value = None
        self.assertFalse( repo.is_valid( "tok" ) )

    def test_is_valid_used( self ):
        """
        Ensures:
            - Used token -> False
        """
        repo, session = _repo()
        token_obj = MagicMock( used=True, expires_at=datetime.now( timezone.utc ) + timedelta( minutes=30 ) )
        session.query.return_value.filter.return_value.first.return_value = token_obj
        self.assertFalse( repo.is_valid( "tok" ) )

    def test_is_valid_expired( self ):
        """
        Ensures:
            - Expired token -> False
        """
        repo, session = _repo()
        token_obj = MagicMock( used=False, expires_at=datetime.now( timezone.utc ) - timedelta( minutes=1 ) )
        session.query.return_value.filter.return_value.first.return_value = token_obj
        self.assertFalse( repo.is_valid( "tok" ) )

    def test_cleanup_expired( self ):
        """
        Ensures:
            - cleanup_expired bulk-deletes and returns the count
        """
        repo, session = _repo()
        session.query.return_value.filter.return_value.delete.return_value = 3
        self.assertEqual( repo.cleanup_expired(), 3 )
        session.flush.assert_called_once()


if __name__ == "__main__":
    unittest.main()
