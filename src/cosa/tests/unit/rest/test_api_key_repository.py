"""
Unit tests for cosa.rest.db.repositories.api_key_repository.

SQLAlchemy session mocked ( chainable query ); inherited BaseRepository.create /
get_by_id mocked. No real DB. Covers all ApiKey service-account methods.
"""

import unittest
import uuid
from unittest.mock import patch, MagicMock

from cosa.rest.db.repositories.api_key_repository import ApiKeyRepository


def _repo():
    """
    Ensures:
        - Returns ( repo, session, query ) with a chainable query mock
    """
    session = MagicMock()
    q = session.query.return_value
    q.filter.return_value = q
    return ApiKeyRepository( session ), session, q


class TestApiKeyRepository( unittest.TestCase ):
    """
    Tests for ApiKeyRepository.

    Ensures:
        - Creation, hash/user lookup, (de)activation, last-used, validity, counting
    """

    def test_create_key_delegates_active( self ):
        """
        Ensures:
            - create_key delegates to base.create with is_active=True
        """
        repo, _, _ = _repo()
        with patch.object( repo, "create", return_value="created" ) as mock_create:
            uid = uuid.uuid4()
            self.assertEqual( repo.create_key( uid, "hash", "desc" ), "created" )
            _, kwargs = mock_create.call_args
            self.assertEqual( kwargs[ "user_id" ], uid )
            self.assertEqual( kwargs[ "key_hash" ], "hash" )
            self.assertTrue( kwargs[ "is_active" ] )

    def test_get_by_hash( self ):
        """
        Ensures:
            - get_by_hash returns the first match
        """
        repo, _, q = _repo()
        q.first.return_value = "key"
        self.assertEqual( repo.get_by_hash( "h" ), "key" )

    def test_get_by_user_active_only( self ):
        """
        Ensures:
            - Default ( include_inactive False ) applies the is_active filter
        """
        repo, _, q = _repo()
        q.order_by.return_value.all.return_value = [ "k1" ]
        result = repo.get_by_user( uuid.uuid4() )
        self.assertEqual( result, [ "k1" ] )
        # two filter calls: user_id + is_active
        self.assertEqual( q.filter.call_count, 2 )

    def test_get_by_user_include_inactive( self ):
        """
        Ensures:
            - include_inactive=True skips the is_active filter ( single filter )
        """
        repo, _, q = _repo()
        q.order_by.return_value.all.return_value = [ "k1", "k2" ]
        result = repo.get_by_user( uuid.uuid4(), include_inactive=True )
        self.assertEqual( result, [ "k1", "k2" ] )
        self.assertEqual( q.filter.call_count, 1 )

    def test_deactivate_found( self ):
        """
        Ensures:
            - Existing key -> is_active False + flush + True
        """
        repo, session, _ = _repo()
        key = MagicMock()
        with patch.object( repo, "get_by_id", return_value=key ):
            self.assertTrue( repo.deactivate( uuid.uuid4() ) )
            self.assertFalse( key.is_active )
            session.flush.assert_called_once()

    def test_deactivate_not_found( self ):
        """
        Ensures:
            - Missing key -> False
        """
        repo, _, _ = _repo()
        with patch.object( repo, "get_by_id", return_value=None ):
            self.assertFalse( repo.deactivate( uuid.uuid4() ) )

    def test_activate_found( self ):
        """
        Ensures:
            - Existing key -> is_active True + flush + True
        """
        repo, session, _ = _repo()
        key = MagicMock()
        with patch.object( repo, "get_by_id", return_value=key ):
            self.assertTrue( repo.activate( uuid.uuid4() ) )
            self.assertTrue( key.is_active )

    def test_activate_not_found( self ):
        """
        Ensures:
            - Missing key -> False
        """
        repo, _, _ = _repo()
        with patch.object( repo, "get_by_id", return_value=None ):
            self.assertFalse( repo.activate( uuid.uuid4() ) )

    def test_update_last_used_found( self ):
        """
        Ensures:
            - Existing key -> last_used_at stamped + flush + True
        """
        repo, session, _ = _repo()
        key = MagicMock()
        with patch.object( repo, "get_by_id", return_value=key ):
            self.assertTrue( repo.update_last_used( uuid.uuid4() ) )
            self.assertIsNotNone( key.last_used_at )

    def test_update_last_used_not_found( self ):
        """
        Ensures:
            - Missing key -> False
        """
        repo, _, _ = _repo()
        with patch.object( repo, "get_by_id", return_value=None ):
            self.assertFalse( repo.update_last_used( uuid.uuid4() ) )

    def test_is_valid_active( self ):
        """
        Ensures:
            - Existing + active key -> True
        """
        repo, _, q = _repo()
        q.first.return_value = MagicMock( is_active=True )
        self.assertTrue( repo.is_valid( "h" ) )

    def test_is_valid_inactive( self ):
        """
        Ensures:
            - Existing but inactive key -> False
        """
        repo, _, q = _repo()
        q.first.return_value = MagicMock( is_active=False )
        self.assertFalse( repo.is_valid( "h" ) )

    def test_is_valid_missing( self ):
        """
        Ensures:
            - Missing key -> False
        """
        repo, _, q = _repo()
        q.first.return_value = None
        self.assertFalse( repo.is_valid( "h" ) )

    def test_count_active_for_user( self ):
        """
        Ensures:
            - count_active_for_user returns the query count
        """
        repo, _, q = _repo()
        q.count.return_value = 3
        self.assertEqual( repo.count_active_for_user( uuid.uuid4() ), 3 )

    def test_get_active_keys( self ):
        """
        Ensures:
            - get_active_keys returns all active keys
        """
        repo, _, q = _repo()
        q.all.return_value = [ "k1", "k2" ]
        self.assertEqual( repo.get_active_keys(), [ "k1", "k2" ] )


if __name__ == "__main__":
    unittest.main()
