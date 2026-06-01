"""
Unit tests for cosa.rest.db.repositories.email_verification_token_repository.

The SQLAlchemy session is mocked ( chainable query ) and the inherited BaseRepository
.create is mocked, so no real DB and no coupling to base internals. The real
EmailVerificationToken model is used only for column-expression args to the mocked query.

Covers: create_token · get_by_token · mark_used · is_valid · cleanup_expired.
"""

import unittest
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock

from cosa.rest.db.repositories.email_verification_token_repository import (
    EmailVerificationTokenRepository,
)


def _repo():
    """
    Ensures:
        - Returns ( repo, mock_session ) with a chainable query mock
    """
    session = MagicMock()
    return EmailVerificationTokenRepository( session ), session


class TestEmailVerificationTokenRepository( unittest.TestCase ):
    """
    Tests for EmailVerificationTokenRepository.

    Ensures:
        - Token creation delegates to base.create with computed expiry
        - Lookup, mark-used, validity, and cleanup behave per contract
    """

    def test_create_token_delegates_with_expiry( self ):
        """
        Ensures:
            - create_token calls self.create with used=False + ~expires_hours-ahead expiry
        """
        repo, _ = _repo()
        with patch.object( repo, "create", return_value="created" ) as mock_create:
            uid = uuid.uuid4()
            result = repo.create_token( token="tok", user_id=uid, expires_hours=24 )
            self.assertEqual( result, "created" )
            _, kwargs = mock_create.call_args
            self.assertEqual( kwargs[ "token" ], "tok" )
            self.assertEqual( kwargs[ "user_id" ], uid )
            self.assertFalse( kwargs[ "used" ] )
            delta = kwargs[ "expires_at" ] - datetime.now( timezone.utc )
            self.assertTrue( timedelta( hours=23 ) < delta <= timedelta( hours=24 ) )

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
            - When the token exists, used is set True, flushed, returns True
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
            - When the token is missing, returns False
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
        token_obj = MagicMock( used=False, expires_at=datetime.now( timezone.utc ) + timedelta( hours=1 ) )
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
        token_obj = MagicMock( used=True, expires_at=datetime.now( timezone.utc ) + timedelta( hours=1 ) )
        session.query.return_value.filter.return_value.first.return_value = token_obj
        self.assertFalse( repo.is_valid( "tok" ) )

    def test_is_valid_expired( self ):
        """
        Ensures:
            - Expired token -> False
        """
        repo, session = _repo()
        token_obj = MagicMock( used=False, expires_at=datetime.now( timezone.utc ) - timedelta( hours=1 ) )
        session.query.return_value.filter.return_value.first.return_value = token_obj
        self.assertFalse( repo.is_valid( "tok" ) )

    def test_cleanup_expired( self ):
        """
        Ensures:
            - cleanup_expired issues a bulk delete and returns the count
        """
        repo, session = _repo()
        session.query.return_value.filter.return_value.delete.return_value = 5
        self.assertEqual( repo.cleanup_expired(), 5 )
        session.flush.assert_called_once()


if __name__ == "__main__":
    unittest.main()
