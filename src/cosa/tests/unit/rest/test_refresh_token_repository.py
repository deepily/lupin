"""
Unit tests for cosa.rest.db.repositories.refresh_token_repository.

SQLAlchemy session mocked ( chainable query ); inherited BaseRepository.create mocked.
No real DB. Covers JTI lookup, user listing ( revoked filter ), revoke / revoke-all,
cleanup, last-used ( with/without ip ), validity, counting, and delete.
"""

import unittest
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock

from cosa.rest.db.repositories.refresh_token_repository import RefreshTokenRepository


def _repo():
    """
    Ensures:
        - Returns ( repo, session, query ) with a chainable query mock
    """
    session = MagicMock()
    q = session.query.return_value
    q.filter.return_value = q
    q.order_by.return_value = q
    return RefreshTokenRepository( session ), session, q


class TestRefreshTokenRepository( unittest.TestCase ):
    """
    Tests for RefreshTokenRepository.

    Ensures:
        - Full token-lifecycle method contract with all branch arms
    """

    def test_create_token_delegates_unrevoked( self ):
        """
        Ensures:
            - create_token delegates to base.create with revoked=False
        """
        repo, _, _ = _repo()
        with patch.object( repo, "create", return_value="created" ) as mock_create:
            result = repo.create_token(
                jti=uuid.uuid4(), user_id=uuid.uuid4(), token_hash="h",
                expires_at=datetime.now( timezone.utc ), user_agent="UA", ip_address="1.2.3.4"
            )
            self.assertEqual( result, "created" )
            self.assertFalse( mock_create.call_args.kwargs[ "revoked" ] )

    def test_get_by_jti( self ):
        """
        Ensures:
            - get_by_jti returns the first match
        """
        repo, _, q = _repo()
        q.first.return_value = "tok"
        self.assertEqual( repo.get_by_jti( uuid.uuid4() ), "tok" )

    def test_get_by_user_active_only( self ):
        """
        Ensures:
            - Default applies the revoked==False filter ( two filters )
        """
        repo, _, q = _repo()
        q.all.return_value = [ "t1" ]
        self.assertEqual( repo.get_by_user( uuid.uuid4() ), [ "t1" ] )
        self.assertEqual( q.filter.call_count, 2 )

    def test_get_by_user_include_revoked( self ):
        """
        Ensures:
            - include_revoked=True applies a single filter
        """
        repo, _, q = _repo()
        q.all.return_value = [ "t1", "t2" ]
        self.assertEqual( repo.get_by_user( uuid.uuid4(), include_revoked=True ), [ "t1", "t2" ] )
        self.assertEqual( q.filter.call_count, 1 )

    def test_revoke_found( self ):
        """
        Ensures:
            - Existing token -> revoked True + flush + token returned
        """
        repo, session, q = _repo()
        token = MagicMock()
        q.first.return_value = token
        self.assertIs( repo.revoke( uuid.uuid4() ), token )
        self.assertTrue( token.revoked )
        session.flush.assert_called_once()

    def test_revoke_not_found( self ):
        """
        Ensures:
            - Missing token -> None
        """
        repo, _, q = _repo()
        q.first.return_value = None
        self.assertIsNone( repo.revoke( uuid.uuid4() ) )

    def test_revoke_all_for_user( self ):
        """
        Ensures:
            - Bulk update returns the revoked count
        """
        repo, session, q = _repo()
        q.update.return_value = 3
        self.assertEqual( repo.revoke_all_for_user( uuid.uuid4() ), 3 )
        session.flush.assert_called_once()

    def test_cleanup_expired( self ):
        """
        Ensures:
            - Bulk delete returns the count
        """
        repo, session, q = _repo()
        q.delete.return_value = 5
        self.assertEqual( repo.cleanup_expired(), 5 )
        session.flush.assert_called_once()

    def test_update_last_used_with_ip( self ):
        """
        Ensures:
            - Existing token -> last_used_at stamped, ip updated when provided
        """
        repo, _, q = _repo()
        token = MagicMock()
        q.first.return_value = token
        self.assertIs( repo.update_last_used( uuid.uuid4(), "9.9.9.9" ), token )
        self.assertEqual( token.ip_address, "9.9.9.9" )

    def test_update_last_used_without_ip( self ):
        """
        Ensures:
            - No ip provided -> ip_address not overwritten
        """
        repo, _, q = _repo()
        token = MagicMock()
        token.ip_address = "orig"
        q.first.return_value = token
        repo.update_last_used( uuid.uuid4() )
        self.assertEqual( token.ip_address, "orig" )

    def test_update_last_used_not_found( self ):
        """
        Ensures:
            - Missing token -> None
        """
        repo, _, q = _repo()
        q.first.return_value = None
        self.assertIsNone( repo.update_last_used( uuid.uuid4() ) )

    def test_is_valid_true( self ):
        """
        Ensures:
            - Existing, unrevoked, unexpired -> True
        """
        repo, _, q = _repo()
        q.first.return_value = MagicMock( revoked=False, expires_at=datetime.now( timezone.utc ) + timedelta( days=1 ) )
        self.assertTrue( repo.is_valid( uuid.uuid4() ) )

    def test_is_valid_missing( self ):
        """
        Ensures:
            - Missing token -> False
        """
        repo, _, q = _repo()
        q.first.return_value = None
        self.assertFalse( repo.is_valid( uuid.uuid4() ) )

    def test_is_valid_revoked( self ):
        """
        Ensures:
            - Revoked token -> False
        """
        repo, _, q = _repo()
        q.first.return_value = MagicMock( revoked=True, expires_at=datetime.now( timezone.utc ) + timedelta( days=1 ) )
        self.assertFalse( repo.is_valid( uuid.uuid4() ) )

    def test_is_valid_expired( self ):
        """
        Ensures:
            - Expired token -> False
        """
        repo, _, q = _repo()
        q.first.return_value = MagicMock( revoked=False, expires_at=datetime.now( timezone.utc ) - timedelta( days=1 ) )
        self.assertFalse( repo.is_valid( uuid.uuid4() ) )

    def test_count_active_for_user( self ):
        """
        Ensures:
            - count_active_for_user returns the query count
        """
        repo, _, q = _repo()
        q.count.return_value = 2
        self.assertEqual( repo.count_active_for_user( uuid.uuid4() ), 2 )

    def test_delete_found( self ):
        """
        Ensures:
            - Existing token -> session.delete + flush + True
        """
        repo, session, q = _repo()
        token = MagicMock()
        q.first.return_value = token
        self.assertTrue( repo.delete( uuid.uuid4() ) )
        session.delete.assert_called_once_with( token )

    def test_delete_not_found( self ):
        """
        Ensures:
            - Missing token -> False
        """
        repo, _, q = _repo()
        q.first.return_value = None
        self.assertFalse( repo.delete( uuid.uuid4() ) )


if __name__ == "__main__":
    unittest.main()
